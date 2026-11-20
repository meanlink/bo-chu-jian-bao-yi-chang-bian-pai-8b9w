import time, json
from sqlalchemy import select, func
from src.config.database import Session
from migrations.initial import migrate
from src.models import User, Dataset, Job, Report, Delivery, Audit, BulletinSeries, BulletinVersion
from src.services.business import metadata, seed_records, analyze
from src.services.reports import deliver
from src.services import bulletins
from src.utils.security import hash_password
from src.utils.serialization import checksum


def seed():
    migrate()
    with Session() as db:
        for role, name in [('admin', '林知 · 业务负责人'), ('analyst', '陈舟 · 分析员'), ('viewer', '周禾 · 观察员')]:
            email = role + '@demo.local'
            if not db.scalar(select(User).where(User.email == email)):
                db.add(User(email=email, name=name, role=role, password=hash_password('Demo123!')))
        db.flush()
        m = metadata()
        d = db.scalar(select(Dataset).where(Dataset.name == m['dataset_name']))
        if not d:
            rows = seed_records()
            d = Dataset(name=m['dataset_name'], source=m['short'] + '-202611.csv', records=rows,
                        checksum=checksum(rows), created_at=time.time())
            db.add(d); db.flush()
        if not db.scalar(select(Job).where(Job.name == '基线复核 · ' + m['name'])):
            params = {p['key']: p['default'] for p in m.get('parameters', [])}
            result = analyze(d.records, params)
            json.dumps(result, ensure_ascii=False, allow_nan=False)
            admin = db.scalar(select(User).where(User.role == 'admin'))
            j = Job(name='基线复核 · ' + m['name'], dataset_id=d.id, params=params, status='completed',
                    result=result, created_by=admin.id, created_at=time.time() - 3600,
                    finished_at=time.time() - 3595, approved=True)
            db.add(j); db.flush()
            r = Report(name='每日业务复核简报', job_id=j.id, destination='业务复核组 · 本地收件箱',
                       interval_seconds=86400, next_run=time.time() + 86400, enabled=True, run_count=0)
            db.add(r); db.flush()
            # 首发全量投递并签收，作为该系列底稿；后续定时投递即按播出日发增删改。
            delivery = deliver(db, r, actor='seed',
                               attempt_key=bulletins.scheduled_attempt_key(r.id, 1))
            r.run_count = 1  # 与首发占用的第 1 轮对齐，worker 下一轮从第 2 轮开始
            version = db.get(BulletinVersion, delivery.bulletin_version_id)
            bulletins.sign(db, version.id, admin)
            db.add(Audit(actor='seed', action='demo.baseline',
                         detail={'dataset': d.id, 'bulletin': version.id}, at=time.time()))
        db.commit()
        models_ = [User, Dataset, Job, Report, Delivery, BulletinSeries, BulletinVersion, Audit]
        counts = {model.__tablename__: db.scalar(select(func.count()).select_from(model)) for model in models_}
        print(json.dumps(counts, ensure_ascii=False))
        return counts


if __name__ == '__main__':
    seed()
