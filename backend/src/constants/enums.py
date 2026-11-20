from enum import Enum
class Role(str, Enum):
    admin = 'admin'
    analyst = 'analyst'
    viewer = 'viewer'
class JobStatus(str, Enum):
    queued = 'queued'
    running = 'running'
    completed = 'completed'
    failed = 'failed'
class BulletinKind(str, Enum):
    initial = 'initial'        # 首发：给齐全部越限日
    correction = 'correction'  # 后续：按播出日发增删改
class BulletinStatus(str, Enum):
    pending = 'pending'        # 待签收
    signed = 'signed'          # 已签收，可作底稿
    rejected = 'rejected'      # 已退回，不作底稿、不接续
