import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./ad_material.db")
IS_SQLITE = DATABASE_URL.startswith("sqlite")
# timeout: 等待写锁的秒数；批量任务与请求并发时避免立刻 "database is locked"
connect_args = {"check_same_thread": False, "timeout": 30} if IS_SQLITE else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


if IS_SQLITE:
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):
        """WAL 让读写互不阻塞；busy_timeout 让写-写冲突排队等待而不是立刻失败。"""
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
