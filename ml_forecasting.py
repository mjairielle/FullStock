import pandas as pd
from sklearn.linear_model import LinearRegression
from datetime import timedelta
from functions import get_records
from calculations import get_metrics

def predict_demand(sku_id, store_id, days_ahead=14):
    """
    Uses Machine Learning (Linear Regression) to forecast demand based on historical sales data.
    Features: day of week, day of month, and overall time trend.
    """
    sales = get_records("sales_log", "sku_id", sku_id)
    store_sales = [s for s in sales if s["store_id"] == store_id]
    
    if not store_sales:
        return fallback_prediction(sku_id, store_id, days_ahead)
    
    # Process data into a DataFrame
    df = pd.DataFrame(store_sales)
    # Safely handle the timestamp glitch before passing to pandas
    def _fix_date(d):
        d = d.replace("Z", "+00:00")
        if d.count(':') > 3 and '+' in d:
            d = d.split('+')[0] + "+" + d.split('+')[1][:5]
        return d
    df['sale_date'] = df['sale_date'].apply(_fix_date)
    df['sale_date'] = pd.to_datetime(df['sale_date'], format='ISO8601', errors='coerce')
    df = df.dropna(subset=['sale_date'])
    df['date'] = df['sale_date'].dt.date
    
    # Group by day and sum qty_sold
    daily_sales = df.groupby('date')['qty_sold'].sum().reset_index()
    daily_sales['date'] = pd.to_datetime(daily_sales['date'])
    
    # Need at least 10 days of data to train a meaningful ML model
    if len(daily_sales) < 30:
        return fallback_prediction(sku_id, store_id, days_ahead)
        
    # Feature Engineering
    daily_sales['day_of_week'] = daily_sales['date'].dt.dayofweek
    daily_sales['day_of_month'] = daily_sales['date'].dt.day
    # Numeric representation of time for overall linear trend
    daily_sales['time_index'] = (daily_sales['date'] - daily_sales['date'].min()).dt.days
    
    # Features (X) and Target (y)
    X = daily_sales[['day_of_week', 'day_of_month', 'time_index']]
    y = daily_sales['qty_sold']
    
    # Train the Machine Learning model
    model = LinearRegression()
    model.fit(X, y)
    
    # Make predictions for the next `days_ahead` days
    last_date = daily_sales['date'].max()
    future_dates = [last_date + timedelta(days=i) for i in range(1, days_ahead + 1)]
    
    future_df = pd.DataFrame({'date': future_dates})
    future_df['day_of_week'] = future_df['date'].dt.dayofweek
    future_df['day_of_month'] = future_df['date'].dt.day
    future_df['time_index'] = (future_df['date'] - daily_sales['date'].min()).dt.days
    
    X_future = future_df[['day_of_week', 'day_of_month', 'time_index']]
    predictions = model.predict(X_future)
    
    # Sum up the predictions (replace any negative predictions with 0)
    total_predicted_demand = sum(max(0, p) for p in predictions)
    
    return int(total_predicted_demand)

def fallback_prediction(sku_id, store_id, days_ahead=14):
    """
    Fallback to the traditional heuristic method if there is not enough data for ML.
    """
    metrics = get_metrics(sku_id, store_id, use_cache=True)
    daily_demand   = metrics.get("daily_demand_simple", 0)
    trend          = metrics.get("trend_14d", 0)
    trend_mult     = max(0, 1 + (trend / 100.0))
    return int(daily_demand * days_ahead * trend_mult)
