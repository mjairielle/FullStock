"""
FullStock Database Layer — MySQL via SQLAlchemy ORM

Models for: users, stores, skus, stock, sales_log, metrics, alerts, audit_log
Engine: MySQL (via PyMySQL driver)
"""

import os
from sqlalchemy import create_engine, Column, Integer, Float, String, DateTime, Boolean, Text, Index
from sqlalchemy.orm import declarative_base, sessionmaker
from contextlib import contextmanager
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv(override=True)

# ── Connection ────────────────────────────────────────────────────
_url = os.environ.get("DATABASE_URL", "mysql+pymysql://root:@localhost/fullstock")

# Auto-fix for common missing driver prefix
if _url.startswith("mysql://"):
    _url = _url.replace("mysql://", "mysql+pymysql://", 1)

# Strip query parameters like ?ssl-mode=REQUIRED which cause PyMySQL to crash
if "?" in _url:
    _url = _url.split("?")[0]

DATABASE_URL = _url

# SSL Configuration (Required for Aiven and other secure hosts)
connect_args = {}
if "ssl-mode=REQUIRED" in os.environ.get("DATABASE_URL", "") or "aivencloud.com" in DATABASE_URL:
    # For Aiven, we explicitly request REQUIRED mode to match their service settings.
    connect_args["ssl"] = {"ssl_mode": "REQUIRED"} 
    print("[INFO] Database SSL connection enabled.")

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_size=5,
    max_overflow=10,
    pool_recycle=3600,
    echo=False
)

SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


# ── Session Helper ────────────────────────────────────────────────
@contextmanager
def get_session():
    """Context manager for DB sessions with auto-commit/rollback."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ── Models ────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    user_id        = Column(String(20), primary_key=True)
    name           = Column(String(100), nullable=False)
    email          = Column(String(255), nullable=False, unique=True)
    password_hash  = Column(String(255), nullable=True)  # Nullable for OAuth-only users
    oauth_provider = Column(String(50), nullable=True)   # e.g. "google"
    oauth_id       = Column(String(255), nullable=True)  # Provider's user ID
    created_at     = Column(DateTime, default=datetime.now(timezone.utc))
    updated_at     = Column(DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))

    __table_args__ = (
        Index('idx_users_email', 'email'),
    )


class Store(Base):
    __tablename__ = "stores"

    store_id   = Column(String(20), primary_key=True)
    user_id    = Column(String(20), nullable=False)
    store_name = Column(String(100), nullable=False)
    location   = Column(String(100))
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))

    __table_args__ = (
        Index('idx_stores_user_id', 'user_id'),
    )


class SKU(Base):
    __tablename__ = "skus"

    sku_id           = Column(String(20), primary_key=True)
    store_id         = Column(String(20), nullable=False)
    product_name     = Column(String(150), nullable=False)
    category         = Column(String(100))
    unit_cost        = Column(Float, default=0)
    order_cost       = Column(Float, default=0)
    hold_cost_annual = Column(Float, default=0)
    lead_time_days   = Column(Integer, default=7)
    created_at       = Column(DateTime, default=datetime.now(timezone.utc))
    updated_at       = Column(DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))

    __table_args__ = (
        Index('idx_skus_store_id', 'store_id'),
        Index('idx_skus_category', 'category'),
    )


class Stock(Base):
    __tablename__ = "stock"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    stock_id    = Column(String(20), nullable=True)
    sku_id      = Column(String(20), nullable=False)
    store_id    = Column(String(20), nullable=False)
    qty_on_hand = Column(Integer, default=0)
    created_at  = Column(DateTime, default=datetime.now(timezone.utc))
    updated_at  = Column(DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))

    __table_args__ = (
        Index('idx_stock_sku_id', 'sku_id'),
        Index('idx_stock_store_id', 'store_id'),
        Index('idx_stock_sku_store', 'sku_id', 'store_id'),
    )


class SalesLog(Base):
    __tablename__ = "sales_log"

    sale_id    = Column(String(20), primary_key=True)
    sku_id     = Column(String(20), nullable=False)
    store_id   = Column(String(20), nullable=False)
    qty_sold   = Column(Integer, nullable=False)
    sale_date  = Column(String(50), nullable=False)  # Keep as string for backward compat
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))

    __table_args__ = (
        Index('idx_sales_sku_id', 'sku_id'),
        Index('idx_sales_store_id', 'store_id'),
        Index('idx_sales_date', 'sale_date'),
        Index('idx_sales_sku_store', 'sku_id', 'store_id'),
    )


class Metric(Base):
    __tablename__ = "metrics"

    id                    = Column(Integer, primary_key=True, autoincrement=True)
    sku_id                = Column(String(20), nullable=False)
    store_id              = Column(String(20), nullable=False)
    timestamp             = Column(String(50))
    daily_demand_simple   = Column(Float, default=0)
    daily_demand_weighted = Column(Float, default=0)
    safety_stock          = Column(Float, default=0)
    eoq                   = Column(Float, default=0)
    rop                   = Column(Float, default=0)
    days_of_cover         = Column(Float, default=0)
    trend_14d             = Column(Float, default=0)

    __table_args__ = (
        Index('idx_metrics_sku_store', 'sku_id', 'store_id'),
    )


class Alert(Base):
    __tablename__ = "alerts"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    sku_id          = Column(String(20), nullable=False)
    store_id        = Column(String(20), nullable=False)
    product_name    = Column(String(150))
    qty_on_hand     = Column(Integer, default=0)
    rop             = Column(Float, default=0)
    eoq             = Column(Float, default=0)
    days_of_cover   = Column(Float, default=0)
    trend_14d       = Column(Float, default=0)
    severity        = Column(String(20))
    should_buy      = Column(Boolean, default=False)
    qty_to_buy      = Column(Integer, default=0)
    low_demand_flag = Column(Boolean, default=False)
    reason          = Column(String(255))
    timestamp       = Column(String(50))

    __table_args__ = (
        Index('idx_alerts_store_id', 'store_id'),
        Index('idx_alerts_sku_store', 'sku_id', 'store_id'),
    )


class AuditLog(Base):
    __tablename__ = "audit_log"

    log_id    = Column(String(20), primary_key=True)
    user_id   = Column(String(20), nullable=False)
    store_id  = Column(String(20))
    action    = Column(String(50), nullable=False)
    details   = Column(Text)
    timestamp = Column(String(50))
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))

    __table_args__ = (
        Index('idx_audit_user_id', 'user_id'),
        Index('idx_audit_store_id', 'store_id'),
    )


# ── Table Registry ───────────────────────────────────────────────
TABLE_MAP = {
    "users": User,
    "stores": Store,
    "skus": SKU,
    "stock": Stock,
    "sales_log": SalesLog,
    "metrics": Metric,
    "alerts": Alert,
    "audit_log": AuditLog,
}

# Primary ID field for each table (used by gen_id)
ID_FIELD_MAP = {
    "users": "user_id",
    "stores": "store_id",
    "skus": "sku_id",
    "stock": "stock_id",
    "sales_log": "sale_id",
    "audit_log": "log_id",
}


# ── Init ─────────────────────────────────────────────────────────
def init_db():
    """Create all tables if they don't exist."""
    Base.metadata.create_all(engine)
    print("[OK] Database tables created/verified.")
