import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from .models import Base, Settings

# Locally: no DATABASE_URL set -> falls back to a SQLite file.
# On Render (or any host): set DATABASE_URL to your Postgres connection
# string (e.g. from Neon.tech's free tier) and it's used automatically -
# this is what makes your data survive restarts/redeploys on a free host,
# since free-tier disks on most platforms are wiped on every restart.

DATABASE_URL = os.environ.get("DATABASE_URL", "")

if DATABASE_URL:
    # Some providers hand out "postgres://" - SQLAlchemy 2.x requires "postgresql://"
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
else:
    DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ebay_manager.db")
    engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db():
    Base.metadata.create_all(engine)
    # ensure a single settings row always exists
    db = SessionLocal()
    try:
        if not db.query(Settings).first():
            db.add(Settings(id=1))
            db.commit()
    finally:
        db.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
