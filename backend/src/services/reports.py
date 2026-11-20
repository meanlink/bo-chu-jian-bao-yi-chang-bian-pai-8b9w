import time, os, csv, io, hashlib, json
from fastapi import HTTPException
from sqlalchemy import select
from src.models import Job, Report, Delivery, BulletinVersion
from src.config.settings import ARTIFACT_DIR
from src.services import bulletins


def create(db, data):
    j = db.get(Job, data.job_id)
    if not j or j.status != 'completed' or not j.approved:
        raise HTTPException(409, '请先选择已完成且获批准的分析结果')
    r = Report(name=data.name, job_id=j.id, destination=data.destination,
               interval_seconds=data.interval_seconds,
               next_run=time.time() + data.delay_seconds, enabled=True, run_count=0)
    db.add(r); db.flush()
    return r


def _safe(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v
    text = str(v)
    return "'" + text if text.startswith(('=', '+', '-', '@', '\t', '\r')) else text


def _write_artifact(delivery: Delivery, payload: dict, rows: list, columns: list):
    out = io.StringIO()
    out.write('﻿')
    writer = csv.writer(out)
    writer.writerow([_safe(c['label']) for c in columns])
    keys = [c['key'] for c in columns]
    for row in rows:
        writer.writerow([_safe(row.get(k, '')) for k in keys])
    data = out.getvalue().encode('utf-8')
    delivery.checksum = hashlib.sha256(data).hexdigest()
    os.makedirs(ARTIFACT_DIR, exist_ok=True)
    with open(os.path.join(ARTIFACT_DIR, delivery.filename), 'wb') as f:
        f.write(data)
    with open(os.path.join(ARTIFACT_DIR, delivery.filename + '.json'), 'w') as f:
        json.dump(payload, f, ensure_ascii=False, allow_nan=False)
    return data


def _version_payload(version: BulletinVersion) -> tuple[dict, list, list]:
    """构造归档内容：首发=全量；更正=增删改明细 + 可还原的整份快照。"""
    snap = version.snapshot
    base = snap.get('baseline', {})
    if version.kind == 'initial':
        columns = [
            {'key': 'day', 'label': '播出日'}, {'key': 'actual', 'label': '实测'},
            {'key': 'ewma', 'label': 'EWMA'}, {'key': 'lower', 'label': '下控制限'},
            {'key': 'upper', 'label': '上控制限'}, {'key': 'status', 'label': '简报标记'},
        ]
        rows = snap.get('anomalies', [])
    else:
        columns = [
            {'key': 'op', 'label': '变更类型'}, {'key': 'day', 'label': '播出日'},
            {'key': 'field', 'label': '口径字段'}, {'key': 'before', 'label': '底稿值'},
            {'key': 'after', 'label': '最新值'},
        ]
        rows = []
        for item in version.delta.get('added', []):
            rows.append({'op': '新增', 'day': item['day'], 'field': '整行',
                         'before': '', 'after': json.dumps(item['after'], ensure_ascii=False)})
        for item in version.delta.get('removed', []):
            rows.append({'op': '删除', 'day': item['day'], 'field': '整行',
                         'before': json.dumps(item['before'], ensure_ascii=False), 'after': ''})
        for item in version.delta.get('changed', []):
            for field, pair in item['changes'].items():
                rows.append({'op': '变化', 'day': item['day'], 'field': field,
                             'before': pair['before'], 'after': pair['after']})
    payload = {
        'version_id': version.id, 'series_id': version.series_id, 'seq': version.seq,
        'kind': version.kind, 'status': version.status, 'destination': version.destination,
        'baseline_version_id': version.baseline_id, 'attempt_key': version.attempt_key,
        'issue_at': version.issue_at, 'summary': version.summary,
        'caliber': base, 'params': snap.get('params', {}),
        'delta': version.delta, 'full_snapshot_anomalies': snap.get('anomalies', []),
        'checksum_input': snap.get('anomalies', []),
    }
    return payload, rows, columns


def deliver(db, report: Report, *, actor: str = 'worker', attempt_key: str | None = None):
    """一轮投递：生成（或幂等恢复）简报版本并写归档；重试不新增收件箱归档。"""
    j = db.get(Job, report.job_id)
    if not j or not j.approved:
        return None

    if attempt_key is None:
        report.run_count += 1
        attempt_key = bulletins.scheduled_attempt_key(report.id, report.run_count)

    # 中断恢复：该轮已建过归档则原样返回，绝不新增收件箱条目。
    existed = db.scalar(select(Delivery).where(Delivery.attempt_key == attempt_key))
    if existed is not None:
        report.next_run = time.time() + report.interval_seconds
        return existed

    version = bulletins.issue_version(db, report, attempt_key=attempt_key, actor=actor)
    payload, rows, columns = _version_payload(version)

    delivery = Delivery(report_id=report.id, created_at=time.time(), checksum='',
                        filename='', destination=report.destination,
                        bulletin_version_id=version.id, attempt_key=attempt_key)
    db.add(delivery); db.flush()
    delivery.filename = f'report-{report.id}-delivery-{delivery.id}.csv'
    _write_artifact(delivery, payload, rows, columns)
    report.next_run = time.time() + report.interval_seconds
    return delivery
