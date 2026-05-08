
from functions import get_records, get_one, load_json, save_json
import math
from datetime import datetime, timedelta, timezone

def _get_recent_sales(sku_id, store_id, days):
    """Fetch and filter sales for a SKU/store within the last N days (single query)."""
    sales = get_records("sales_log", "sku_id", sku_id)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat() + "Z"
    return [s for s in sales if s["store_id"] == store_id and s["sale_date"] >= cutoff]

def daily_demand_simple(sku_id, store_id, days=30, _sales=None):
    """Calculate avg daily demand over last N days."""
    recent_sales = _sales if _sales is not None else _get_recent_sales(sku_id, store_id, days)
    total_qty = sum(s["qty_sold"] for s in recent_sales)
    return total_qty / days if days > 0 else 0

def daily_demand_weighted(sku_id, store_id, days=30, _sales=None):
    """Calculate weighted avg daily demand (recent sales more weight)."""
    recent_sales = _sales if _sales is not None else _get_recent_sales(sku_id, store_id, days)
    
    split_point = datetime.now(timezone.utc) - timedelta(days=days//2)
    split_iso = split_point.isoformat() + "Z"
    recent = [s for s in recent_sales if s["sale_date"] >= split_iso]
    prior = [s for s in recent_sales if s["sale_date"] < split_iso]
    
    recent_sum = sum(s["qty_sold"] for s in recent) * 1.5
    prior_sum = sum(s["qty_sold"] for s in prior) * 1.0
    total_weighted = recent_sum + prior_sum
    
    return total_weighted / days if days > 0 else 0

def calc_safety_stock(sku_id, store_id, service_level=0.95, _sales=None):
    """Calculate safety stock based on demand variability."""
    recent_sales = _sales if _sales is not None else _get_recent_sales(sku_id, store_id, 30)
    
    daily_sums = {}
    for i in range(30):
        d_str = (datetime.now(timezone.utc) - timedelta(days=i)).strftime('%Y-%m-%d')
        daily_sums[d_str] = 0
        
    for s in recent_sales:
        d_str = s["sale_date"][:10]
        if d_str in daily_sums:
            daily_sums[d_str] += s["qty_sold"]
            
    daily_qtys = list(daily_sums.values())
    
    if not daily_qtys:
        return 1  # Minimum safety stock
    
    mean_val = sum(daily_qtys) / len(daily_qtys)
    std_dev = (sum((x - mean_val)**2 for x in daily_qtys) / len(daily_qtys))**0.5
    sku = get_one("skus", "sku_id", sku_id)
    lead_time = sku.get("lead_time_days", 7)
    
    z_score = 1.65  # For 95% service level
    safety_stock = z_score * std_dev * (lead_time ** 0.5)
    
    return max(1, round(safety_stock))

def calc_eoq(sku_id, store_id):
    """Calculate Economic Order Quantity."""
    d = daily_demand_simple(sku_id, store_id, 30)
    D = d * 365  # Annual demand
    sku = get_one("skus", "sku_id", sku_id)
    S = sku.get("order_cost", 0)
    H = sku.get("hold_cost_annual", 0)
    
    if D == 0 or H == 0:
        return 0
    
    eoq = ((2 * D * S) / H) ** 0.5
    return round(eoq)

def calc_rop(sku_id, store_id):
    """Calculate Reorder Point."""
    avg_daily = daily_demand_simple(sku_id, store_id, 30)
    sku = get_one("skus", "sku_id", sku_id)
    lead_time = sku.get("lead_time_days", 7)
    
    # Safety Stock (Buffer for uncertainty)
    # If no sales, assume a minimum safety buffer of 5% of a typical batch
    safety_stock = max(2.0, (avg_daily * 0.5) * lead_time)
    
    # Reorder Point (ROP) = (Daily Demand * Lead Time) + Safety Stock
    # For new items, ensure ROP is at least enough to cover lead time + buffer
    rop = math.ceil((avg_daily * lead_time) + safety_stock)
    if avg_daily == 0:
        rop = max(1, math.ceil(lead_time * 0.2)) # Minimum buffer for new items
        
    return rop

def calc_days_of_cover(sku_id, store_id):
    """Calculate Days of Cover based on current stock."""
    stock = get_records("stock", "sku_id", sku_id)
    store_stock = next((s for s in stock if s["store_id"] == store_id), None)
    qty_on_hand = store_stock["qty_on_hand"] if store_stock else 0
    
    d = daily_demand_simple(sku_id, store_id, 30)
    
    if d == 0:
        return 999  # Infinite cover if no demand
    
    days_cover = qty_on_hand / d
    return round(days_cover, 2)

def calc_trend(sku_id, store_id, window1=14, window2=14, _sales=None):
    """Calculate demand trend (% change between two periods)."""
    recent_sales = _sales if _sales is not None else _get_recent_sales(sku_id, store_id, window1 + window2)
    
    cutoff_iso = (datetime.now(timezone.utc) - timedelta(days=window1)).isoformat() + "Z"
    recent_period = [s for s in recent_sales if s["sale_date"] >= cutoff_iso]
    prior_period = [s for s in recent_sales if s["sale_date"] < cutoff_iso]
    
    avg_recent = sum(s["qty_sold"] for s in recent_period) / window1
    avg_prior = sum(s["qty_sold"] for s in prior_period) / window2
    
    if avg_prior == 0:
        return 0  # No prior demand means no trend
    
    slope = ((avg_recent - avg_prior) / avg_prior) * 100
    return round(slope, 2)

def calc_all_metrics(sku_id, store_id):
    """Calculate all metrics and save to cache."""
    # Single DB fetch for all calculations that need sales data
    sales_30d = _get_recent_sales(sku_id, store_id, 30)
    sales_28d = _get_recent_sales(sku_id, store_id, 28)
    metrics = {
        "sku_id": sku_id,
        "store_id": store_id,
        "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
        "daily_demand_simple": daily_demand_simple(sku_id, store_id, _sales=sales_30d),
        "daily_demand_weighted": daily_demand_weighted(sku_id, store_id, _sales=sales_30d),
        "safety_stock": calc_safety_stock(sku_id, store_id, _sales=sales_30d),
        "eoq": calc_eoq(sku_id, store_id),
        "rop": calc_rop(sku_id, store_id),
        "days_of_cover": calc_days_of_cover(sku_id, store_id),
        "trend_14d": calc_trend(sku_id, store_id, _sales=sales_28d)
    }
    
    # Load existing metrics
    metrics_data = load_json("metrics")
    # Remove old entry for same SKU+store
    metrics_data = [m for m in metrics_data if not (m["sku_id"] == sku_id and m["store_id"] == store_id)]
    # Append new metrics
    metrics_data.append(metrics)
    # Save back to JSON
    save_json("metrics", metrics_data)
    
    return metrics

def get_metrics_cached(sku_id, store_id):
    """Fetch metrics from cache if recent."""
    cached_data = load_json("metrics")
    for m in cached_data:
        try:
            if m.get("sku_id") != sku_id or m.get("store_id") != store_id:
                continue
            ts_str = m.get("timestamp", "")
            if not ts_str:
                continue
            # Safely handle both 'Z' and '+00:00' or other offsets
            ts_str = ts_str.replace('Z', "+00:00")
            # If the string somehow got a double offset, trim it
            if ts_str.count(':') > 3 and '+' in ts_str:
                # Basic fix for the +00:00:00:00 glitch seen in logs
                parts = ts_str.split('+')
                if len(parts) > 1:
                    ts_str = parts[0] + "+" + parts[1][:5]

            timestamp = datetime.fromisoformat(ts_str)
            now = datetime.now(timezone.utc)
            
            # Check freshness (1 hour)
            if (now - timestamp).total_seconds() < 3600:
                return m
        except (ValueError, TypeError, KeyError) as e:
            print(f"[DEBUG] Skipping malformed cache entry: {e}")
            continue
    return None

def get_metrics(sku_id, store_id, use_cache=True):
    """Get metrics, using cache if valid."""
    if use_cache:
        cached = get_metrics_cached(sku_id, store_id)
        if cached:
            return cached
    return calc_all_metrics(sku_id, store_id)

def refresh_all_metrics(store_id):
    from functions import get_records
    skus = get_records("skus", "store_id", store_id)
    for sku in skus:
        calc_all_metrics(sku["sku_id"], store_id)

