from sqlalchemy import String, Double, ForeignKey, Integer, Text, JSON, Computed, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base


class BulletinSeries(Base):
    """同接收组、同播出链路、同监测口径构成一个简报系列。"""
    __tablename__ = 'bulletin_series'
    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey('reports.id'), unique=True)
    series_key: Mapped[str] = mapped_column(String(180), unique=True)
    destination: Mapped[str] = mapped_column(String(120))
    channel: Mapped[str] = mapped_column(String(80))
    metric: Mapped[str] = mapped_column(String(40))
    # 最近一次签收（底稿）版本；无签收时为 None，表示下一份是首发全量。
    baseline_id: Mapped[int | None] = mapped_column(ForeignKey('bulletin_versions.id'), nullable=True)
    created_at: Mapped[float] = mapped_column(Double)


class BulletinVersion(Base):
    """一份简报：首发全量，或相对底稿的增删改更正；同时是本地收件箱条目。"""
    __tablename__ = 'bulletin_versions'
    __table_args__ = (
        # 并发约束：一个系列同时只能有一份待签收（pending）版本。
        # 生成列 pending_slot 仅在 status='pending' 时取 series_id，否则为 NULL；
        # 唯一索引里多个 NULL 不冲突（MySQL 8 与 SQLite 语义一致），
        # 因此只有“同系列第二份待签收”会被数据库拒绝。
        UniqueConstraint('pending_slot', name='uq_series_one_pending'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    series_id: Mapped[int] = mapped_column(ForeignKey('bulletin_series.id'))
    seq: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20))          # initial 首发全量 | correction 增删改更正
    status: Mapped[str] = mapped_column(String(20), default='pending')  # pending|signed|rejected
    # 持久化生成列，配合上面的唯一约束实现“同系列仅一份待签收”。
    pending_slot: Mapped[int | None] = mapped_column(
        Integer, Computed("CASE WHEN status = 'pending' THEN series_id ELSE NULL END", persisted=True),
        nullable=True)
    baseline_id: Mapped[int | None] = mapped_column(ForeignKey('bulletin_versions.id'), nullable=True)
    job_id: Mapped[int] = mapped_column(ForeignKey('jobs.id'))
    report_id: Mapped[int] = mapped_column(ForeignKey('reports.id'))
    destination: Mapped[str] = mapped_column(String(120))
    # 幂等键：定时投递为 report:周期序号，手工更正为 correction:uuid；中断重试复用同一键。
    attempt_key: Mapped[str] = mapped_column(String(160), unique=True)
    issue_at: Mapped[float] = mapped_column(Double)
    signed_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    signed_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    rejected_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    rejected_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 完整快照（全量越限日 + 基准口径），用于按底稿还原整份。
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    # 相对底稿的增删改；首发为空列表。
    delta: Mapped[dict] = mapped_column(JSON, default=dict)
    summary: Mapped[str] = mapped_column(String(500), default='')
    created_by: Mapped[str] = mapped_column(String(150), default='worker')

