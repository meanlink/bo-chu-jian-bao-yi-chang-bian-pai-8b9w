from sqlalchemy import inspect, text
from src.config.database import Base, engine
from src import models  # noqa: F401  确保所有模型已注册到 Base.metadata


def _ensure_columns():
    """create_all 只建新表；对既有表幂等补齐新增列，老数据卷可平滑升级。"""
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    existing = {table: {col['name'] for col in inspector.get_columns(table)} for table in tables}
    additions = {
        'reports': [('run_count', 'INTEGER NOT NULL DEFAULT 0')],
        'deliveries': [
            ('bulletin_version_id', 'INTEGER NULL'),
            ('attempt_key', 'VARCHAR(160) NULL'),
        ],
    }
    with engine.begin() as conn:
        for table, columns in additions.items():
            if table not in existing:
                continue
            for name, ddl_type in columns:
                if name not in existing[table]:
                    conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {ddl_type}'))
        if 'deliveries' in existing and 'attempt_key' not in existing['deliveries']:
            try:
                conn.execute(text('CREATE UNIQUE INDEX ix_deliveries_attempt_key ON deliveries (attempt_key)'))
            except Exception:
                pass


def migrate():
    Base.metadata.create_all(engine)
    _ensure_columns()


if __name__ == '__main__':
    migrate()
