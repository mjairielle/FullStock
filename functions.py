"""
FullStock Data Access Layer — MySQL-backed

All function signatures are preserved from the original JSON-based version.
Modules that import from here (app.py, calculations.py, alerts.py, ml_forecasting.py)
require ZERO code changes.
"""

from datetime import datetime, timezone

from database import (
    get_session, init_db, TABLE_MAP, ID_FIELD_MAP
)


# ── Row Conversion ───────────────────────────────────────────────

def row_to_dict(row):
    """Convert a SQLAlchemy model instance to a plain dict.
    
    Converts datetime columns to ISO strings for backward compatibility
    with existing code that does string comparisons on dates.
    """
    if row is None:
        return None
    d = {}
    for col in row.__table__.columns:
        val = getattr(row, col.name)
        if isinstance(val, datetime):
            d[col.name] = val.isoformat() + "Z"
        else:
            d[col.name] = val
    return d


def _parse_dt(value):
    """Ensure datetime columns get Python datetime objects, not strings."""
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, str):
        for fmt in (
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ):
            try:
                return datetime.strptime(value, fmt)
            except (ValueError, TypeError):
                continue
    return value


def dict_to_model(model_class, data):
    """Convert a dict to a SQLAlchemy model instance.
    
    Only includes keys that are valid columns on the model.
    Parses datetime strings into datetime objects for MySQL compatibility.
    """
    from sqlalchemy import DateTime
    valid = {}
    col_map = {c.name: c for c in model_class.__table__.columns}
    for k, v in data.items():
        if k in col_map:
            # Parse datetime strings for DateTime columns
            if isinstance(col_map[k].type, DateTime):
                v = _parse_dt(v)
            valid[k] = v
    return model_class(**valid)


# ── CORE I/O (backward-compatible adapters) ──────────────────────

def load_json(filename):
    """Load all records from a DB table as a list of dicts.
    
    Preserves the original signature so calculations.py and alerts.py
    continue to work without modification.
    """
    model = TABLE_MAP.get(filename)
    if model is None:
        return []
    with get_session() as db:
        rows = db.query(model).all()
        return [row_to_dict(r) for r in rows]


def save_json(filename, data):
    """Replace all records in a DB table with the provided list.
    
    This is the backward-compatible adapter for the load→filter→save
    pattern used in calculations.py and alerts.py.
    """
    model = TABLE_MAP.get(filename)
    if model is None:
        return
    with get_session() as db:
        db.query(model).delete()
        for record in data:
            obj = dict_to_model(model, record)
            db.add(obj)


# ── CRUD OPS ─────────────────────────────────────────────────────

def add_record(table, record):
    """Add record + timestamps."""
    now = datetime.now(timezone.utc)
    record["created_at"] = now
    record["updated_at"] = now

    model = TABLE_MAP.get(table)
    if model is None:
        return record

    with get_session() as db:
        obj = dict_to_model(model, record)
        db.add(obj)

    return record


def update_record(table, id_field, id_val, updates):
    """Update record. Set updated_at."""
    now = datetime.utcnow()
    updates["updated_at"] = now

    model = TABLE_MAP.get(table)
    if model is None:
        return

    with get_session() as db:
        row = db.query(model).filter(
            getattr(model, id_field) == id_val
        ).first()
        if row:
            for k, v in updates.items():
                if hasattr(row, k):
                    setattr(row, k, v)


def update_record_compound(table, filters, updates):
    """Update record matching ALL filter key-value pairs. Prevents IDOR."""
    now = datetime.utcnow()
    updates["updated_at"] = now

    model = TABLE_MAP.get(table)
    if model is None:
        return

    with get_session() as db:
        query = db.query(model)
        for k, v in filters.items():
            if hasattr(model, k):
                query = query.filter(getattr(model, k) == v)
        row = query.first()
        if row:
            for k, v in updates.items():
                if hasattr(row, k):
                    setattr(row, k, v)


def get_records(table, filt_field=None, filt_val=None):
    """Fetch records. Filter optional."""
    model = TABLE_MAP.get(table)
    if model is None:
        return []

    with get_session() as db:
        query = db.query(model)
        if filt_field and hasattr(model, filt_field):
            query = query.filter(getattr(model, filt_field) == filt_val)
        return [row_to_dict(r) for r in query.all()]


def get_one(table, id_field, id_val):
    """Fetch single record."""
    model = TABLE_MAP.get(table)
    if model is None:
        return None

    with get_session() as db:
        row = db.query(model).filter(
            getattr(model, id_field) == id_val
        ).first()
        return row_to_dict(row) if row else None


def delete_records(table, filt_field, filt_val):
    """Delete all records matching a filter. Used for clean cascade deletes."""
    model = TABLE_MAP.get(table)
    if model is None:
        return 0

    with get_session() as db:
        count = db.query(model).filter(
            getattr(model, filt_field) == filt_val
        ).delete()
        return count


# ── HELPERS ──────────────────────────────────────────────────────

def gen_id(prefix, table):
    """Generate next ID. e.g. USR001, STR001.
    
    Finds the max existing numeric suffix to avoid collisions after deletes.
    """
    model = TABLE_MAP.get(table)
    id_field = ID_FIELD_MAP.get(table)
    if model is None or id_field is None:
        return f"{prefix}001"

    with get_session() as db:
        col = getattr(model, id_field)
        results = db.query(col).all()

    if not results:
        return f"{prefix}001"

    max_num = 0
    for (val,) in results:
        if val and isinstance(val, str) and val.startswith(prefix):
            try:
                num = int(val[len(prefix):])
                if num > max_num:
                    max_num = num
            except ValueError:
                pass

    return f"{prefix}{max_num + 1:03d}"


def init_data_dir():
    """Initialize database tables."""
    init_db()


def add_audit_log(user_id, store_id, action, details):
    """Log an action to the audit log."""
    log = {
        "log_id": gen_id("LOG", "audit_log"),
        "user_id": user_id,
        "store_id": store_id,
        "action": action,
        "details": details,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    }
    add_record("audit_log", log)
    return log