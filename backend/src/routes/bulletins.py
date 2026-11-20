from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from src.config.database import get_db
from src.models import Report, BulletinSeries, BulletinVersion
from src.middlewares.auth import current_user, admin_only
from src.services import bulletins
from src.services.audit import record
from src.utils.serialization import bulletin_version_dict, bulletin_series_dict

router = APIRouter(prefix='/bulletins')


class RejectInput(BaseModel):
    reason: str = Field(default='', max_length=900)


class CorrectionInput(BaseModel):
    report_id: int
    reason: str = Field(default='', max_length=900)


@router.get('/series')
def series_list(db=Depends(get_db), u=Depends(current_user)):
    rows = db.scalars(select(BulletinSeries).order_by(BulletinSeries.id.desc()))
    return [bulletin_series_dict(db, s) for s in rows]


@router.get('/inbox')
def inbox(db=Depends(get_db), u=Depends(current_user), status: str | None = None,
          series_id: int | None = None):
    stmt = select(BulletinVersion).order_by(BulletinVersion.id.desc()).limit(200)
    if status:
        if status not in ('pending', 'signed', 'rejected'):
            raise HTTPException(422, '未知收件箱状态')
        stmt = stmt.where(BulletinVersion.status == status)
    if series_id:
        stmt = stmt.where(BulletinVersion.series_id == series_id)
    return [bulletin_version_dict(v) for v in db.scalars(stmt)]


@router.get('/versions/{vid}')
def version_detail(vid: int, db=Depends(get_db), u=Depends(current_user)):
    v = db.get(BulletinVersion, vid)
    if not v:
        raise HTTPException(404, '收件箱简报不存在')
    return bulletin_version_dict(v, full=True)


@router.post('/versions/{vid}/sign')
def sign(vid: int, db=Depends(get_db), u=Depends(admin_only)):
    v = bulletins.sign(db, vid, u)
    record(db, u.email, 'bulletin.signed', {'id': vid, 'series': v.series_id, 'seq': v.seq})
    db.commit()
    return bulletin_version_dict(v, full=True)


@router.post('/versions/{vid}/reject')
def reject(vid: int, data: RejectInput, db=Depends(get_db), u=Depends(admin_only)):
    v = bulletins.reject(db, vid, data.reason, u)
    record(db, u.email, 'bulletin.rejected',
           {'id': vid, 'series': v.series_id, 'seq': v.seq, 'reason': v.reject_reason})
    db.commit()
    return bulletin_version_dict(v, full=True)


@router.get('/versions/{vid}/restore')
def restore(vid: int, db=Depends(get_db), u=Depends(current_user)):
    """按底稿还原整份全量越限日（沿底稿链回放增删改），只读，不改变任何归档。"""
    v = db.get(BulletinVersion, vid)
    if not v:
        raise HTTPException(404, '收件箱简报不存在')
    full = bulletins.build_full_snapshot(db, v)
    record(db, u.email, 'bulletin.restored', {'id': vid, 'series': v.series_id})
    db.commit()
    return full


@router.post('/corrections', status_code=201)
def create_correction(data: CorrectionInput, db=Depends(get_db), u=Depends(admin_only)):
    """手工并发生成：同一底稿已有待签收更正时 409，不挂第二份。"""
    report = db.get(Report, data.report_id)
    if not report:
        raise HTTPException(404, '分发计划不存在')
    key = bulletins.new_correction_key()
    v = bulletins.issue_version(db, report, attempt_key=key, actor=u.email)
    record(db, u.email, 'bulletin.correction.created',
           {'id': v.id, 'series': v.series_id, 'seq': v.seq, 'reason': data.reason})
    db.commit()
    return bulletin_version_dict(v, full=True)
