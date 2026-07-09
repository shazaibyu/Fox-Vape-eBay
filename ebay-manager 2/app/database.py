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
    # Lightweight migrations: create_all doesn't add new columns to tables
    # that already exist (e.g. the Neon database from an earlier version),
    # so add them manually and ignore "already exists" errors.
    from sqlalchemy import text
    migrations = [
        "ALTER TABLE orders ADD COLUMN refunded BOOLEAN DEFAULT FALSE",
        "ALTER TABLE settings ADD COLUMN low_stock_threshold INTEGER DEFAULT 3",
        "ALTER TABLE orders ADD COLUMN ship_by_date TIMESTAMP",
        "ALTER TABLE orders ADD COLUMN shipped_date TIMESTAMP",
        "ALTER TABLE orders ADD COLUMN max_delivery_date TIMESTAMP",
        "ALTER TABLE orders ADD COLUMN stock_deducted BOOLEAN DEFAULT FALSE",
    ]
    with engine.connect() as conn:
        for stmt in migrations:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception:
                conn.rollback()  # column already exists - fine
    # ensure a single settings row always exists, and seed default
    # tracking-prefix shipping rates (F/Y/H) if none are configured yet
    from .models import TrackingPrefixRate
    db = SessionLocal()
    try:
        if not db.query(Settings).first():
            db.add(Settings(id=1))
        if not db.query(TrackingPrefixRate).first():
            db.add(TrackingPrefixRate(prefix="F", cost=3.50))
            db.add(TrackingPrefixRate(prefix="Y", cost=2.44))
            db.add(TrackingPrefixRate(prefix="H", cost=3.10))
        db.commit()
    finally:
        db.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
