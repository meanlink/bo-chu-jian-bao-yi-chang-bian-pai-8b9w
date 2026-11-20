import hashlib, json
from sqlalchemy import select, func
from src.models import BulletinVersion


def checksum(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def dataset_dict(d):
    return {'id': d.id, 'name': d.name, 'source': d.source, 'rows': len(d.records),
            'checksum': d.checksum, 'created_at': d.created_at}


def job_dict(j):
    return {k: getattr(j, k) for k in ['id', 'name', 'dataset_id', 'params', 'status',
                                       'result', 'error', 'approved', 'created_at', 'finished_at']}


def report_dict(r):
    return {k: getattr(r, k) for k in ['id', 'name', 'job_id', 'destination',
                                       'interval_seconds', 'next_run', 'enabled', 'run_count']}


def delivery_dict(d):
    return {k: getattr(d, k) for k in ['id', 'report_id', 'created_at', 'checksum', 'filename',
                                       'destination', 'bulletin_version_id', 'attempt_key']}


def bulletin_series_dict(db, s):
    baseline = db.get(BulletinVersion, s.baseline_id) if s.baseline_id else None
    pending_count = db.scalar(select(func.count()).select_from(BulletinVersion).where(
        BulletinVersion.series_id == s.id, BulletinVersion.status == 'pending'))
    total = db.scalar(select(func.count()).select_from(BulletinVersion).where(
        BulletinVersion.series_id == s.id))
    return {
        'id': s.id, 'report_id': s.report_id, 'series_key': s.series_key,
        'destination': s.destination, 'channel': s.channel, 'metric': s.metric,
        'baseline_id': s.baseline_id, 'baseline_seq': baseline.seq if baseline else None,
        'pending_count': pending_count, 'total_versions': total, 'created_at': s.created_at,
    }


def bulletin_version_dict(v, full=False):
    data = {k: getattr(v, k) for k in [
        'id', 'series_id', 'seq', 'kind', 'status', 'baseline_id', 'job_id',
        'report_id', 'destination', 'attempt_key', 'issue_at', 'signed_at',
        'signed_by', 'rejected_at', 'rejected_by', 'reject_reason', 'summary',
        'created_by', 'delta']}
    data['anomaly_count'] = len(v.snapshot.get('anomalies', []))
    data['caliber'] = v.snapshot.get('baseline', {})
    if full:
        data['snapshot'] = v.snapshot
    return data
