import os
import re
import secrets
from flask import Flask, jsonify, request, render_template, redirect, session, url_for
from datetime import datetime, timedelta, timezone
from functools import wraps
from collections import defaultdict, Counter
from werkzeug.security import generate_password_hash, check_password_hash
from flask_wtf.csrf import CSRFProtect
from flask_talisman import Talisman
from dotenv import load_dotenv
from authlib.integrations.flask_client import OAuth
from werkzeug.middleware.proxy_fix import ProxyFix

from functions import (
    get_one, get_records, load_json,
    init_data_dir, gen_id, add_record, update_record,
    update_record_compound, add_audit_log, delete_records
)
from calculations import get_metrics, calc_all_metrics, refresh_all_metrics
from alerts import run_all_alerts
from test_data import seed_test_data
from ml_forecasting import predict_demand

# Load environment variables from .env
load_dotenv()

# Allow insecure transport for local development (OAuth over HTTP)
if os.environ.get('FLASK_DEBUG') == '1':
    os.environ['AUTHLIB_INSECURE_TRANSPORT'] = '1'

app = Flask(__name__, template_folder='.')
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# ── Security Config ──────────────────────────────────────────────
app.secret_key = os.environ.get('SECRET_KEY') or secrets.token_hex(32)

app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)

# CSRF Protection
csrf = CSRFProtect(app)

# Security Headers via Talisman
csp = {
    'default-src': "'self'",
    'script-src': ["'self'", "'unsafe-inline'", "cdn.tailwindcss.com", "cdn.jsdelivr.net", "unpkg.com"],
    'style-src': ["'self'", "'unsafe-inline'", "fonts.googleapis.com", "cdn.tailwindcss.com"],
    'font-src': ["'self'", "fonts.gstatic.com"],
    'img-src': ["'self'", "data:"],
    'connect-src': "'self'",
}
Talisman(
    app,
    content_security_policy=csp,
    force_https=os.environ.get('FORCE_HTTPS', '0') == '1',
    session_cookie_secure=os.environ.get('FORCE_HTTPS', '0') == '1',
)

# ── Email Validation ─────────────────────────────────────────────
def is_valid_email(email):
    """Validate email format using a robust regex pattern."""
    if not email or not isinstance(email, str):
        return False
    if len(email) > 254:
        return False
    pattern = r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,63}$'
    return bool(re.match(pattern, email))


# ── Google OAuth Setup ───────────────────────────────────────────
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.environ.get('GOOGLE_CLIENT_ID'),
    client_secret=os.environ.get('GOOGLE_CLIENT_SECRET'),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'},
)

# ── Auth Decorator ───────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated_function

def _init_session(user_id, user_name, store_id=None):
    """Set up a fresh, authenticated session. Prevents session fixation."""
    session.clear()
    session['user_id'] = user_id
    session['user_name'] = user_name
    session.permanent = True
    if store_id:
        session['store_id'] = store_id

def get_current_store_id():
    store_id = session.get('store_id')
    if not store_id:
        stores = get_records("stores", "user_id", session.get('user_id'))
        if stores:
            store_id = stores[0]['store_id']
            session['store_id'] = store_id
    return store_id

@app.context_processor
def inject_user_stores():
    if 'user_id' in session:
        stores = get_records("stores", "user_id", session['user_id'])
        return dict(user_stores=stores, current_store_id=session.get('store_id'), current_user=session.get('user_name'))
    return dict(user_stores=[])

# ── Auth Routes ──────────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not email or not password:
            return render_template("login.html", error="Email and password are required.")

        user = get_one("users", "email", email)
        if not user:
            return render_template("login.html", error="Invalid email or password.")

        pw_hash = user.get("password_hash") or ""
        if not pw_hash:
            return render_template("login.html", error="This account uses Google Sign-In. Please use the Google button below.")

        if not check_password_hash(pw_hash, password):
            return render_template("login.html", error="Invalid email or password.")

        _init_session(user['user_id'], user.get('name', 'User'))

        stores = get_records("stores", "user_id", user['user_id'])
        if stores:
            session['store_id'] = stores[0]['store_id']
        add_audit_log(user['user_id'], session.get('store_id', ''), "LOGIN", "User logged in.")
        return redirect("/dashboard")
    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        if not name or not email or not password:
            return render_template("register.html", error="All fields are required.")

        if len(password) < 8:
            return render_template("register.html", error="Password must be at least 8 characters.")

        if password != confirm:
            return render_template("register.html", error="Passwords do not match.")

        if not is_valid_email(email):
            return render_template("register.html", error="Please enter a valid email address.")

        if get_one("users", "email", email):
            return render_template("register.html", error="Email already exists.")

        user_id = gen_id("USR", "users")
        add_record("users", {
            "user_id": user_id,
            "name": name,
            "email": email,
            "password_hash": generate_password_hash(password)
        })

        store_id = gen_id("STR", "stores")
        add_record("stores", {"store_id": store_id, "user_id": user_id, "store_name": f"{name}'s Store", "location": "Default"})

        _init_session(user_id, name, store_id)
        add_audit_log(user_id, store_id, "REGISTER", "User registered.")
        return redirect("/dashboard")
    return render_template("register.html")

@app.route("/login/google")
def login_google():
    redirect_uri = url_for('authorize_google', _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route("/login/google/callback")
def authorize_google():
    try:
        token = google.authorize_access_token()
        user_info = token.get('userinfo')
        if not user_info:
            user_info = google.userinfo()
    except Exception:
        return render_template("login.html", error="Google sign-in failed. Please try again.")

    email = user_info.get('email', '').strip().lower()
    name = user_info.get('name', email.split('@')[0])
    oauth_id = user_info.get('sub', '')

    if not email:
        return render_template("login.html", error="Could not retrieve email from Google.")

    user = get_one("users", "email", email)

    if not user:
        user_id = gen_id("USR", "users")
        add_record("users", {
            "user_id": user_id,
            "name": name,
            "email": email,
            "password_hash": "",
            "oauth_provider": "google",
            "oauth_id": oauth_id,
        })

        store_id = gen_id("STR", "stores")
        add_record("stores", {
            "store_id": store_id,
            "user_id": user_id,
            "store_name": f"{name}'s Store",
            "location": "Default",
        })

        _init_session(user_id, name, store_id)
        add_audit_log(user_id, store_id, "REGISTER", "User registered via Google OAuth.")
        return redirect("/dashboard")

    if user.get("oauth_provider") != "google":
        return render_template("login.html", error="This email is registered with a password. Please use the normal login form.")

    _init_session(user['user_id'], user.get('name', 'User'))
    stores = get_records("stores", "user_id", user['user_id'])
    if stores:
        session['store_id'] = stores[0]['store_id']
    add_audit_log(user['user_id'], session.get('store_id', ''), "LOGIN", "User logged in via Google OAuth.")
    return redirect("/dashboard")

@app.route("/logout", methods=["POST"])
def logout():
    if 'user_id' in session:
        add_audit_log(session['user_id'], session.get('store_id', ''), "LOGOUT", "User logged out.")
    session.clear()
    return redirect("/login")

@app.route("/switch-store/<store_id>")
@login_required
def switch_store(store_id):
    store = get_one("stores", "store_id", store_id)
    if store and store.get("user_id") == session["user_id"]:
        session['store_id'] = store_id
    return redirect("/dashboard")

@app.route("/add-store", methods=["GET", "POST"])
@login_required
def add_store():
    if request.method == "POST":
        store_name = request.form.get("store_name")
        location = request.form.get("location")
        if not store_name or not location:
            return render_template("add_store.html", error="All fields are required.")
        store_id = gen_id("STR", "stores")
        user_id = session['user_id']
        add_record("stores", {"store_id": store_id, "user_id": user_id, "store_name": store_name, "location": location})
        session['store_id'] = store_id
        add_audit_log(user_id, store_id, "CREATE_STORE", f"Created store: {store_name}")
        return redirect("/dashboard")
    return render_template("add_store.html")

@app.route("/health")
def health_check():
    return jsonify({"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}), 200

@app.route("/")
def index():
    if 'user_id' in session:
        return redirect("/dashboard")
    return redirect("/login")

@app.route("/dashboard")
@login_required
def dashboard():
    store_id = get_current_store_id()
    if not store_id: return "No store available."
    alerts = load_json("alerts")
    store_alerts = [a for a in alerts if a.get("store_id") == store_id]
    if not store_alerts:
        run_all_alerts(store_id)
    return render_template("dashboard.html")

@app.route("/stocks")
@login_required
def stocks_page():
    return render_template("stocks.html")

@app.route("/add-item")
@login_required
def add_item_page():
    return render_template("add_item.html")

@app.route("/audit")
@login_required
def audit_page():
    store_id = get_current_store_id()
    logs = get_records("audit_log", "store_id", store_id)
    users_cache = {}
    for log in logs:
        uid = log.get("user_id")
        if uid not in users_cache:
            user = get_one("users", "user_id", uid)
            users_cache[uid] = user.get("name", uid) if user else uid
        log["username"] = users_cache[uid]
    return render_template("audit.html", logs=logs)

@app.route("/api/summary")
@login_required
def api_summary():
    store_id = get_current_store_id()
    alerts = get_records("alerts", "store_id", store_id)
    skus = get_records("skus", "store_id", store_id)
    stock_records = get_records("stock", "store_id", store_id)
    sku_map = {s["sku_id"]: s for s in skus}
    total_stock_value = 0.0
    for stk in stock_records:
        sku_info = sku_map.get(stk["sku_id"])
        if sku_info:
            total_stock_value += stk.get("qty_on_hand", 0) * sku_info.get("unit_cost", 0)
    severity_counts = Counter(a.get("severity") for a in alerts)
    return jsonify({
        "total_skus": len(alerts),
        "critical": severity_counts.get("critical", 0),
        "warning":  severity_counts.get("warning", 0),
        "info":     severity_counts.get("info", 0),
        "ok":       severity_counts.get("ok", 0),
        "total_stock_value": round(total_stock_value, 2)
    })

@app.route("/api/alerts")
@login_required
def api_alerts():
    store_id = get_current_store_id()
    alerts = get_records("alerts", "store_id", store_id)
    severity_order = ["critical", "warning", "info", "ok"]
    alerts.sort(key=lambda x: severity_order.index(x["severity"]) if x["severity"] in severity_order else 99)
    return jsonify(alerts)

@app.route("/api/refresh", methods=["POST"])
@login_required
def api_refresh():
    store_id = get_current_store_id()
    if store_id:
        refresh_all_metrics(store_id)
        run_all_alerts(store_id)
    return jsonify({"status": "ok", "refreshed_at": datetime.now(timezone.utc).isoformat()})

@app.route("/api/stocks")
@login_required
def api_stocks():
    store_id = get_current_store_id()
    if not store_id: return jsonify([])
    skus = get_records("skus", "store_id", store_id)
    alerts = get_records("alerts", "store_id", store_id)
    stock_records = get_records("stock", "store_id", store_id)
    stock_map = {s["sku_id"]: s for s in stock_records}
    alert_map = {a["sku_id"]: a for a in alerts}
    all_metrics = get_records("metrics", "store_id", store_id)
    metrics_map = {}
    now = datetime.now(timezone.utc)
    for m in all_metrics:
        try:
            ts_str = m.get("timestamp", "").replace("Z", "+00:00")
            if ts_str.count(':') > 3 and '+' in ts_str: ts_str = ts_str.split('+')[0] + "+" + ts_str.split('+')[1][:5]
            ts = datetime.fromisoformat(ts_str)
            if (now - ts).total_seconds() < 3600: metrics_map[m["sku_id"]] = m
        except Exception: continue
    merged = []
    for sku in skus:
        sku_id = sku["sku_id"]
        metrics = metrics_map.get(sku_id) or get_metrics(sku_id, store_id)
        alert = alert_map.get(sku_id)
        merged.append({
            "sku_id": sku_id,
            "product_name": sku["product_name"],
            "category": sku.get("category", ""),
            "unit_cost": sku.get("unit_cost", 0),
            "lead_time_days": sku.get("lead_time_days", 7),
            "qty_on_hand": stock_map.get(sku_id, {}).get("qty_on_hand", 0),
            "rop": metrics.get("rop", 0),
            "eoq": metrics.get("eoq", 0),
            "days_of_cover": metrics.get("days_of_cover", 0),
            "trend_14d": metrics.get("trend_14d", 0),
            "severity": alert["severity"] if alert else "info"
        })
    return jsonify(merged)

@app.route("/api/sku/new", methods=["POST"])
@login_required
def api_sku_new():
    data = request.json
    store_id = get_current_store_id()
    sku_id = gen_id("SKU", "skus")
    
    product_name = data.get("product_name", "Unknown Product")
    qty_on_hand = int(data.get("qty_on_hand") or 0)
    
    add_record("skus", {
        "sku_id": sku_id, 
        "store_id": store_id, 
        "product_name": product_name, 
        "category": data.get("category"), 
        "unit_cost": float(data.get("unit_cost") or 0), 
        "order_cost": float(data.get("order_cost") or 0), 
        "hold_cost_annual": float(data.get("hold_cost_annual") or 0), 
        "lead_time_days": int(data.get("lead_time_days") or 7)
    })
    
    add_record("stock", {
        "sku_id": sku_id, 
        "store_id": store_id, 
        "qty_on_hand": qty_on_hand
    })
    
    calc_all_metrics(sku_id, store_id)
    run_all_alerts(store_id)
    
    add_audit_log(session['user_id'], store_id, "CREATE", f"Added new SKU: {sku_id} ({product_name}) with {qty_on_hand} units.")
    
    return jsonify({"status": "ok", "sku_id": sku_id})

@app.route("/api/sku/sell", methods=["POST"])
@login_required
def api_sku_sell():
    data = request.json
    store_id = get_current_store_id()
    sku_id, qty = data.get("sku_id"), int(data.get("qty_to_sell", 0))
    if not sku_id or qty <= 0:
        return jsonify({"status": "error"}), 400
        
    stock = get_one("stock", "sku_id", sku_id)
    if stock and stock.get("store_id") == store_id:
        current_qty = stock.get("qty_on_hand", 0)
        if qty > current_qty:
            return jsonify({"status": "error", "error": "Not enough stock"}), 400
            
        new_qty = current_qty - qty
        update_record_compound("stock", {"sku_id": sku_id, "store_id": store_id}, {"qty_on_hand": new_qty})
        
        sale_id = gen_id("SAL", "sales_log")
        add_record("sales_log", {
            "sale_id": sale_id,
            "sku_id": sku_id,
            "store_id": store_id,
            "qty_sold": qty,
            "sale_date": datetime.now(timezone.utc).isoformat() + "Z"
        })
        
        calc_all_metrics(sku_id, store_id)
        run_all_alerts(store_id)
        
        add_audit_log(session['user_id'], store_id, "SALE", f"Sold {qty} units of SKU: {sku_id}. New total: {new_qty}.")
        
        return jsonify({"status": "ok", "new_qty": new_qty})
    return jsonify({"status": "error"}), 404

@app.route("/api/sku/restock", methods=["POST"])
@login_required
def api_sku_restock():
    data = request.json
    sku_id, qty = data.get("sku_id"), int(data.get("qty_to_add", 0))
    store_id = get_current_store_id()
    stock = next((s for s in get_records("stock", "sku_id", sku_id) if s["store_id"] == store_id), None)
    if stock:
        new_qty = stock["qty_on_hand"] + qty
        update_record_compound("stock", {"sku_id": sku_id, "store_id": store_id}, {"qty_on_hand": new_qty})
        calc_all_metrics(sku_id, store_id)
        run_all_alerts(store_id)
        
        add_audit_log(session['user_id'], store_id, "RESTOCK", f"Restocked SKU: {sku_id} by {qty}. New total: {new_qty}.")
        
        return jsonify({"status": "ok", "new_qty": new_qty})
    return jsonify({"status": "error"}), 404

@app.route("/api/sku/update", methods=["POST"])
@login_required
def api_sku_update():
    data = request.json
    sku_id, store_id = data.get("sku_id"), get_current_store_id()
    
    sku = get_one("skus", "sku_id", sku_id)
    if not sku or sku.get("store_id") != store_id:
        return jsonify({"status": "error", "error": "SKU not found"}), 404

    updates = {}
    if "product_name" in data: updates["product_name"] = data["product_name"]
    if "category" in data:     updates["category"]     = data["category"]
    if "unit_cost" in data:    updates["unit_cost"]    = float(data["unit_cost"] or 0)
    
    if updates:
        update_record_compound("skus", {"sku_id": sku_id, "store_id": store_id}, updates)
    
    if "qty_on_hand" in data:
        update_record_compound("stock", {"sku_id": sku_id, "store_id": store_id}, {"qty_on_hand": int(data["qty_on_hand"] or 0)})
    
    calc_all_metrics(sku_id, store_id)
    add_audit_log(session['user_id'], store_id, "UPDATE", f"Updated details for SKU: {sku_id}.")
    
    return jsonify({"status": "ok"})

@app.route("/api/sku/delete", methods=["POST"])
@login_required
def api_sku_delete():
    data = request.json
    sku_id, store_id = data.get("sku_id"), get_current_store_id()
    delete_records("skus", "sku_id", sku_id)
    delete_records("stock", "sku_id", sku_id)
    delete_records("metrics", "sku_id", sku_id)
    
    add_audit_log(session['user_id'], store_id, "DELETE", f"Deleted SKU: {sku_id} from inventory.")
    
    return jsonify({"status": "ok"})

@app.route("/analytics")
@login_required
def analytics_page():
    return render_template("analytics.html")

@app.route("/api/analytics/sales_history")
@login_required
def api_sales_history():
    store_id = get_current_store_id()
    period = min(max(request.args.get("period", 30, type=int), 1), 365)
    sales = get_records("sales_log", "store_id", store_id)
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=period)
    daily_sales = defaultdict(int)
    for s in sales:
        try:
            ts_str = s["sale_date"].replace("Z", "+00:00")
            if ts_str.count(':') > 3 and '+' in ts_str: ts_str = ts_str.split('+')[0] + "+" + ts_str.split('+')[1][:5]
            dt = datetime.fromisoformat(ts_str)
            if start_date <= dt <= end_date: daily_sales[dt.strftime("%Y-%m-%d")] += s["qty_sold"]
        except Exception: continue
    dates = [(start_date + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(period + 1)]
    return jsonify({"dates": dates, "quantities": [daily_sales[d] for d in dates]})

@app.route("/api/analytics/abc")
@login_required
def api_abc_analysis():
    store_id = get_current_store_id()
    skus = get_records("skus", "store_id", store_id)
    sales = get_records("sales_log", "store_id", store_id)
    sku_revenue = defaultdict(float)
    for s in sales:
        sku = next((x for x in skus if x["sku_id"] == s["sku_id"]), None)
        if sku: sku_revenue[s["sku_id"]] += s["qty_sold"] * sku.get("unit_cost", 0) * 1.5
    sorted_skus = sorted(skus, key=lambda x: sku_revenue[x["sku_id"]], reverse=True)
    total_rev = sum(sku_revenue.values())
    abc, cum = [], 0
    for s in sorted_skus:
        cum += sku_revenue[s["sku_id"]]
        pct = cum / total_rev if total_rev > 0 else 0
        abc.append({"sku_id": s["sku_id"], "product_name": s["product_name"], "revenue": round(sku_revenue[s["sku_id"]], 2), "category": "A" if pct <= 0.8 else "B" if pct <= 0.95 else "C"})
    return jsonify(abc)

@app.route("/api/analytics/dead_stock")
@login_required
def api_dead_stock():
    store_id = get_current_store_id()
    skus, stock, sales = get_records("skus", "store_id", store_id), get_records("stock", "store_id", store_id), get_records("sales_log", "store_id", store_id)
    recent = set()
    now = datetime.now(timezone.utc)
    for s in sales:
        try:
            ts_str = s["sale_date"].replace("Z", "+00:00")
            if ts_str.count(':') > 3 and '+' in ts_str:
                ts_str = ts_str.split('+')[0] + "+" + ts_str.split('+')[1][:5]
            if (now - datetime.fromisoformat(ts_str)).days < 30:
                recent.add(s["sku_id"])
        except Exception:
            pass
    dead = []
    for s in stock:
        if s["qty_on_hand"] > 0 and s["sku_id"] not in recent:
            sku = next((x for x in skus if x["sku_id"] == s["sku_id"]), None)
            if sku: dead.append({"sku_id": s["sku_id"], "product_name": sku["product_name"], "qty_on_hand": s["qty_on_hand"], "capital_tied_up": s["qty_on_hand"] * sku.get("unit_cost", 0)})
    return jsonify(dead)

@app.route("/api/analytics/forecast")
@login_required
def api_forecast():
    store_id = get_current_store_id()
    skus = get_records("skus", "store_id", store_id)
    forecasts = []
    for sku in skus:
        pred = predict_demand(sku["sku_id"], store_id, 14)
        forecasts.append({"sku_id": sku["sku_id"], "product_name": sku["product_name"], "predicted_14d": pred, "message": f"Machine Learning predicts {pred} units needed."})
    return jsonify(forecasts)

# --- APP INITIALIZATION ---
init_data_dir()
with app.app_context():
    try:
        if not get_records("users"): seed_test_data()
    except Exception as e: print(f"Startup failed: {e}")

if __name__ == "__main__":
    with app.app_context():
        try:
            for store in get_records("stores"):
                refresh_all_metrics(store["store_id"])
                run_all_alerts(store["store_id"])
        except Exception as e: print(f"Startup tasks failed: {e}")
    app.run(host="0.0.0.0", debug=os.environ.get('FLASK_DEBUG', '0') == '1', port=5000)