from functions import add_record, gen_id
from datetime import datetime, timedelta, timezone
from werkzeug.security import generate_password_hash
import random

def seed_test_data():
    """Generate sample data."""

    # USER — with hashed password
    user_id = gen_id("USR", "users")
    add_record("users", {
        "user_id": user_id,
        "name": "Demo User",
        "email": "demo@test.com",
        "password_hash": generate_password_hash("demo1234")
    })

    # STORE
    store_id = gen_id("STR", "stores")
    add_record("stores", {
        "store_id": store_id,
        "user_id": user_id,
        "store_name": "Demo Store",
        "location": "Manila"
    })

    # SKUs (3 products)
    product_names = ["Wireless Mouse", "Mechanical Keyboard", "LED Monitor"]
    skus = []
    for i in range(3):
        sku_id = gen_id("SKU", "skus")
        add_record("skus", {
            "sku_id": sku_id,
            "store_id": store_id,
            "product_name": product_names[i],
            "unit_cost": 100 + (i * 50),
            "order_cost": 50,
            "hold_cost_annual": 25,
            "lead_time_days": 7,
            "category": "electronics"
        })
        skus.append(sku_id)

    # STOCK
    for sku_id in skus:
        add_record("stock", {
            "stock_id": gen_id("STK", "stock"),
            "sku_id": sku_id,
            "store_id": store_id,
            "qty_on_hand": random.randint(50, 200)
        })

    # SALES_LOG (30 days)
    for day_offset in range(30):
        sale_date = (datetime.now(timezone.utc) - timedelta(days=day_offset)).isoformat() + "Z"
        for sku_id in skus:
            if random.random() > 0.3:  # 70% chance sale
                add_record("sales_log", {
                    "sale_id": gen_id("SL", "sales_log"),
                    "sku_id": sku_id,
                    "store_id": store_id,
                    "qty_sold": random.randint(1, 10),
                    "sale_date": sale_date
                })