import time, json, logging
from pathlib import Path
from fastapi import HTTPException
from sqlalchemy import select
from redis import Redis
from src.config.database import Session
from src.config.settings import REDIS_URL
from src.models import Job, Dataset, Report
from src.services.business import analyze
from src.services.reports import deliver
from src.services.audit import record
logging.basicConfig(level=logging.INFO)
def execute(job_id):
    with Session() as db:
        j=db.get(Job,job_id)
        if not j or j.status!='queued':return
        j.status='running'; db.commit()
        try:
            d=db.get(Dataset,j.dataset_id)
            result=analyze(d.records,j.params)
            json.dumps(result,allow_nan=False)
            j.result=result;j.status='completed';j.finished_at=time.time()
            record(db,'worker','job.completed',{'id':j.id})
        except Exception as e:
            logging.exception('Analysis failed')
            j.status='failed';j.error=str(e)[:990];j.finished_at=time.time()
            record(db,'worker','job.failed',{'id':j.id,'error':j.error})
        db.commit()
def tick():
    with Session() as db:
        queued=list(db.scalars(select(Job.id).where(Job.status=='queued').limit(3)))
    for job_id in queued:execute(job_id)
    with Session() as db:
        due=list(db.scalars(select(Report).where(Report.enabled==True,Report.next_run<=time.time())))
        for r in due:
            # 先确定稳定轮次键再投递；attempt_key 唯一约束保证中断重启不产生重复归档。
            r.run_count += 1
            attempt_key=f'scheduled:{r.id}:{r.run_count}'
            try:
                d=deliver(db,r,attempt_key=attempt_key)
                if d:record(db,'worker','report.delivered',{'id':r.id,'delivery':d.id,'attempt':attempt_key,'bulletin':d.bulletin_version_id})
            except HTTPException as e:
                # 业务级跳过：待签收占用或无增删改。本轮不产生归档，推进到下一周期再评估。
                r.next_run=time.time()+r.interval_seconds
                record(db,'worker','report.skipped',{'id':r.id,'attempt':attempt_key,'reason':str(e.detail)[:200]})
            except Exception:
                # 系统故障：回退轮次计数且不推进 next_run，下轮以同一 attempt_key 重试原更正。
                r.run_count -= 1
                logging.exception('Delivery failed; will retry the same bulletin')
        db.commit()
def main():
    r=Redis.from_url(REDIS_URL,socket_timeout=3)
    # This Compose stack has a single worker. A crash must not strand its jobs.
    with Session() as db:
        for j in db.scalars(select(Job).where(Job.status=='running')):
            j.status='queued';record(db,'worker','job.recovered',{'id':j.id})
        db.commit()
    while True:
        Path('/tmp/heartbeat').touch()
        try:
            item=r.blpop('analysis:queue',timeout=1)
            if item:execute(int(item[1]))
            tick()
        except Exception:
            logging.exception('Worker retry');time.sleep(2)
if __name__=='__main__':main()
