from sqlalchemy import String, Double, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base
class Report(Base):
    __tablename__ = 'reports'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    job_id: Mapped[int] = mapped_column(ForeignKey('jobs.id'))
    destination: Mapped[str] = mapped_column(String(120))
    interval_seconds: Mapped[int]
    next_run: Mapped[float] = mapped_column(Double)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # 已完成的定时投递轮次，用于生成稳定的幂等 attempt_key（中断重启不回退、不重复）。
    run_count: Mapped[int] = mapped_column(default=0)
class Delivery(Base):
    __tablename__ = 'deliveries'
    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey('reports.id'))
    created_at: Mapped[float] = mapped_column(Double)
    checksum: Mapped[str] = mapped_column(String(64))
    filename: Mapped[str] = mapped_column(String(160))
    destination: Mapped[str] = mapped_column(String(120))
    # 每次归档对应一份简报版本；同 attempt_key 重试复用版本与归档，不新增收件箱条目。
    bulletin_version_id: Mapped[int | None] = mapped_column(ForeignKey('bulletin_versions.id'), nullable=True)
    attempt_key: Mapped[str | None] = mapped_column(String(160), unique=True, nullable=True)
