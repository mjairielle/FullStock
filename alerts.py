from functions import get_records, get_one, load_json, save_json
from calculations import get_metrics
from datetime import datetime, timezone

severity = ["critical", "warning", "info", "ok"]
LOW_DEMAND_TREND_THRESHOLD = -10  # % slope

def check_stock_alert(sku_id, store_id, metrics=None, qty_on_hand=None):
    if qty_on_hand is None:
        stock = get_records("stock", "sku_id", sku_id)
        store_stock = next((s for s in stock if s["store_id"] == store_id), None)
        qty_on_hand = store_stock["qty_on_hand"] if store_stock else 0
    if metrics is None:
        metrics = get_metrics(sku_id, store_id)
    rop = metrics["rop"]
    
    if qty_on_hand == 0:
        return "critical"
    elif qty_on_hand < rop:
        return "warning"
    elif qty_on_hand < rop * 2:
        return "info"
    else:
        return "ok"

def get_buy_recommendation(sku_id, store_id, metrics=None):
    if metrics is None:
        metrics = get_metrics(sku_id, store_id)
    sev = check_stock_alert(sku_id, store_id, metrics=metrics)
    trend = metrics["trend_14d"]
    eoq = metrics["eoq"]
    low_demand = trend < LOW_DEMAND_TREND_THRESHOLD
    
    should_buy = False
    qty_to_buy = 0
    reason = ""
    
    if sev == "ok":
        if low_demand:
            reason = "Declining demand, no buy"
        else:
            reason = "Sufficient stock, no buy"
    elif sev in ["warning", "critical", "info"]:
        should_buy = True
        qty_to_buy = eoq
        if sev == "warning":
            reason = "Stock below ROP"
        elif sev == "critical":
            reason = "Stock out! Critical situation"
        elif sev == "info":
            reason = "Low stock, reordering soon"
            
    return {
        "should_buy": should_buy,
        "qty_to_buy": qty_to_buy,
        "low_demand_flag": low_demand,
        "reason": reason
    }

def build_alert(sku_id, store_id):
    sku = get_one("skus", "sku_id", sku_id)
    stock = get_records("stock", "sku_id", sku_id)
    store_stock = next((s for s in stock if s["store_id"] == store_id), None)
    qty_on_hand = store_stock["qty_on_hand"] if store_stock else 0
    
    metrics = get_metrics(sku_id, store_id)
    sev = check_stock_alert(sku_id, store_id, metrics=metrics, qty_on_hand=qty_on_hand)
    rec = get_buy_recommendation(sku_id, store_id, metrics=metrics)
    
    return {
        "sku_id": sku_id,
        "store_id": store_id,
        "product_name": sku["product_name"],
        "qty_on_hand": qty_on_hand,
        "rop": metrics["rop"],
        "eoq": metrics["eoq"],
        "days_of_cover": metrics["days_of_cover"],
        "trend_14d": metrics["trend_14d"],
        "severity": sev,
        "should_buy": rec["should_buy"],
        "qty_to_buy": rec["qty_to_buy"],
        "low_demand_flag": rec["low_demand_flag"],
        "reason": rec["reason"],
        "timestamp": datetime.now(timezone.utc).isoformat() + "Z"
    }

def run_all_alerts(store_id):
    skus = get_records("skus", "store_id", store_id)
    new_alerts = []
    
    for sku in skus:
        new_alerts.append(build_alert(sku["sku_id"], store_id))
    
    new_alerts.sort(key=lambda x: severity.index(x["severity"]))
    
    all_alerts = load_json("alerts")
    all_alerts = [a for a in all_alerts if a.get("store_id") != store_id]
    all_alerts.extend(new_alerts)
    
    save_json("alerts", all_alerts)
    return new_alerts

