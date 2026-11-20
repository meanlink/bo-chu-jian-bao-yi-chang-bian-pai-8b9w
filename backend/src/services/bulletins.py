"""简报系列：首发送全量、后续按播出日发增删改；以上一份已签收简报为底稿。

并发：同一底稿（即同一系列）同时只允许一份待签收更正，Redis 锁 + 数据库部分唯一索引双保险。
幂等：每次生成携带 attempt_key，发件中断后重试复用同一键，恢复原更正，不新增收件箱归档。
"""
import time
import uuid
import contextlib

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from redis import Redis

from src.config.settings import REDIS_URL
from src.models import Job, Report, BulletinSeries, BulletinVersion
from src.constants.enums import BulletinKind, BulletinStatus

# 越限日进入增删改比对的口径字段（播出日之外）。
DAY_FIELDS = ("actual", "ewma", "lower", "upper", "status")


class PendingConflict(HTTPException):
    def __init__(self):
        super().__init__(409, "该底稿已有一份待签收更正，请先签收或退回后再生成")


@contextlib.contextmanager
def series_lock(series_id: int):
    """系列级互斥锁，覆盖并发生成；Redis 不可用时退化为仅靠数据库唯一索引兜底。"""
    key = f"bulletin:lock:series:{series_id}"
    client = None
    try:
        client = Redis.from_url(REDIS_URL, socket_timeout=2)
        if not client.set(key, "1", nx=True, ex=30):
            client.close()
            raise PendingConflict()
    except PendingConflict:
        raise
    except Exception:
        # Redis 不可用：不阻塞流程，数据库部分唯一索引仍是最终防线。
        client = None
    try:
        yield
    finally:
        if client is not None:
            with contextlib.suppress(Exception):
                client.delete(key)
            client.close()


def make_series_key(destination: str, channel: str, metric: str) -> str:
    return f"{destination}|{channel}|{metric}"


def get_or_create_series(db, report: Report) -> BulletinSeries:
    job = db.get(Job, report.job_id)
    channel = str(job.params.get("channel", ""))
    metric = str(job.params.get("metric", ""))
    key = make_series_key(report.destination, channel, metric)
    series = db.scalar(select(BulletinSeries).where(BulletinSeries.series_key == key))
    if series is None:
        series = BulletinSeries(
            report_id=report.id, series_key=key, destination=report.destination,
            channel=channel, metric=metric, baseline_id=None, created_at=time.time(),
        )
        db.add(series)
        db.flush()
    return series


def _anomaly_index(anomalies: list[dict]) -> dict[str, dict]:
    return {str(row["day"]): row for row in anomalies}


def compute_delta(baseline_rows: list[dict], current_rows: list[dict]) -> dict:
    """按播出日比对两份全量越限日清单，产出 added / removed / changed。"""
    old, new = _anomaly_index(baseline_rows), _anomaly_index(current_rows)
    added = [{"day": day, "after": new[day]} for day in sorted(new.keys() - old.keys())]
    removed = [{"day": day, "before": old[day]} for day in sorted(old.keys() - new.keys())]
    changed = []
    for day in sorted(old.keys() & new.keys()):
        before, after = old[day], new[day]
        changes = {f: {"before": before.get(f), "after": after.get(f)}
                   for f in DAY_FIELDS if before.get(f) != after.get(f)}
        if changes:
            changed.append({"day": day, "changes": changes})
    return {"added": added, "removed": removed, "changed": changed,
            "counts": {"added": len(added), "removed": len(removed), "changed": len(changed)}}


def _snapshot_from_job(job: Job) -> dict:
    result = job.result or {}
    return {
        "job_id": job.id,
        "job_name": job.name,
        "params": job.params,
        "baseline": result.get("baseline", {}),
        "summary": result.get("summary", ""),
        "anomalies": result.get("anomalies", []),
    }


def issue_version(db, report: Report, *, attempt_key: str, actor: str = "worker") -> BulletinVersion:
    """生成一份简报（首发全量或更正增删改）。attempt_key 保证中断重试幂等。"""
    job = db.get(Job, report.job_id)
    if not job or job.status != "completed" or not job.approved:
        raise HTTPException(409, "分发计划绑定的分析结果未完成或未批准，无法出简报")

    # 幂等：同一 attempt_key 直接返回已生成版本（发件中断恢复原更正，不新增归档）。
    existing = db.scalar(select(BulletinVersion).where(BulletinVersion.attempt_key == attempt_key))
    if existing is not None:
        return existing

    series = get_or_create_series(db, report)
    with series_lock(series.id):
        # 锁内复查，避免并发双写。
        dup = db.scalar(select(BulletinVersion).where(BulletinVersion.attempt_key == attempt_key))
        if dup is not None:
            return dup
        # 行级锁串行化同系列并发生成（Redis 失效时仍可靠）。
        locked_series = db.scalar(
            select(BulletinSeries).where(BulletinSeries.id == series.id).with_for_update())
        pending = db.scalar(select(BulletinVersion).where(
            BulletinVersion.series_id == locked_series.id,
            BulletinVersion.status == BulletinStatus.pending.value,
        ))
        if pending is not None:
            raise PendingConflict()

        baseline = db.get(BulletinVersion, locked_series.baseline_id) if locked_series.baseline_id else None
        snapshot = _snapshot_from_job(job)
        last_seq = db.scalar(
            select(BulletinVersion.seq).where(BulletinVersion.series_id == locked_series.id)
            .order_by(BulletinVersion.seq.desc()).limit(1)
        ) or 0

        if baseline is None:
            kind = BulletinKind.initial.value
            delta = {"added": [], "removed": [], "changed": [],
                     "counts": {"added": 0, "removed": 0, "changed": 0}}
            base_id = None
            summary = f"首发全量：给齐全部 {len(snapshot['anomalies'])} 个越限日（同组、同链路、同口径）。"
        else:
            kind = BulletinKind.correction.value
            base_id = baseline.id
            delta = compute_delta(baseline.snapshot.get("anomalies", []), snapshot["anomalies"])
            c = delta["counts"]
            if c["added"] == c["removed"] == c["changed"] == 0:
                raise HTTPException(409, "相对底稿没有越限日增删改，无需生成更正")
            summary = (f"更正（底稿 #{baseline.seq}，{date_text(baseline.issue_at)} 签收）："
                       f"新增 {c['added']} 日、删除 {c['removed']} 日、口径变化 {c['changed']} 日。")

        version = BulletinVersion(
            series_id=locked_series.id, seq=last_seq + 1, kind=kind,
            status=BulletinStatus.pending.value, baseline_id=base_id,
            job_id=job.id, report_id=report.id, destination=report.destination,
            attempt_key=attempt_key, issue_at=time.time(),
            snapshot=snapshot, delta=delta, summary=summary,
            created_by=actor,
        )
        db.add(version)
        try:
            db.flush()
        except IntegrityError:
            # 数据库唯一约束兜底：同一系列已有待签收版本。
            db.rollback()
            raise PendingConflict()
        return version


def sign(db, version_id: int, user) -> BulletinVersion:
    v = db.get(BulletinVersion, version_id)
    if not v:
        raise HTTPException(404, "收件箱简报不存在")
    if v.status != BulletinStatus.pending.value:
        raise HTTPException(409, "仅待签收简报可以签收")
    v.status = BulletinStatus.signed.value
    v.signed_at = time.time()
    v.signed_by = user.email
    series = db.get(BulletinSeries, v.series_id)
    # 签收后成为该系列新底稿；退回的版本永远不会走到这里，故不会接续退回件。
    series.baseline_id = v.id
    return v


def reject(db, version_id: int, reason: str, user) -> BulletinVersion:
    v = db.get(BulletinVersion, version_id)
    if not v:
        raise HTTPException(404, "收件箱简报不存在")
    if v.status != BulletinStatus.pending.value:
        raise HTTPException(409, "仅待签收简报可以退回")
    v.status = BulletinStatus.rejected.value
    v.rejected_at = time.time()
    v.rejected_by = user.email
    v.reject_reason = (reason or "").strip()[:900] or "未填写退回原因"
    # 不动 series.baseline_id：底稿仍指向上一份签收件，退回版本不接续。
    return v


def build_full_snapshot(db, version: BulletinVersion) -> dict:
    """沿 baseline 链回溯到首发，回放增删改，还原该版本对应的整份全量越限日。

    链上只可能出现首发件与被签收的更正件——退回件从不成为底稿，故不会进入链路。
    """
    chain = []
    cur = version
    seen = set()
    while cur is not None and cur.id not in seen:
        seen.add(cur.id)
        chain.append(cur)
        cur = db.get(BulletinVersion, cur.baseline_id) if cur.baseline_id else None
    chain.reverse()  # 首发在前

    rows: dict[str, dict] = {}
    for node in chain:
        if node.kind == BulletinKind.initial.value:
            rows = _anomaly_index(node.snapshot.get("anomalies", []))
            continue
        for item in node.delta.get("added", []):
            rows[item["day"]] = item["after"]
        for item in node.delta.get("removed", []):
            rows.pop(item["day"], None)
        for item in node.delta.get("changed", []):
            day = item["day"]
            if day in rows:
                for field, pair in item["changes"].items():
                    rows[day][field] = pair["after"]
    head = chain[0]
    return {
        "series_id": version.series_id,
        "version_id": version.id,
        "seq": version.seq,
        "restored_from": {"version_id": head.id, "seq": head.seq, "kind": head.kind},
        "baseline": version.snapshot.get("baseline", {}),
        "params": version.snapshot.get("params", {}),
        "anomalies": [rows[day] for day in sorted(rows)],
        "applied_versions": [{"id": n.id, "seq": n.seq, "kind": n.kind} for n in chain],
        "restored_at": time.time(),
    }


def date_text(ts: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


def new_correction_key() -> str:
    return f"correction:{uuid.uuid4().hex}"


def scheduled_attempt_key(report_id: int, run_index: int) -> str:
    return f"scheduled:{report_id}:{run_index}"
