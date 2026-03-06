import requests
import json
import time
import statistics
import os
from dotenv import load_dotenv

# Load API key from .env file
load_dotenv()
_API_KEY = os.getenv("API_KEY", "")

# --- Cache for API data so we don't spam the endpoint ---
_cache = {
    'data': None,
    'timestamp': 0,
    'ttl': 30  # seconds before cache expires
}

def get_bazaar_data():
    """Fetches full bazaar JSON. Uses an in-memory cache (30s TTL)."""
    now = time.time()
    if _cache['data'] and (now - _cache['timestamp']) < _cache['ttl']:
        return _cache['data']

    url = "https://api.hypixel.net/v2/skyblock/bazaar"
    # Send API key as header to avoid rate-limit / IP ban
    headers = {}
    if _API_KEY:
        headers['API-Key'] = _API_KEY

    if not _API_KEY:
        print("No API key found")
        return {'success': False, 'cause': 'No API key found'}

    # Retry up to 3 times if the API returns empty/invalid JSON
    for attempt in range(3):
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()  # Raise on HTTP errors (4xx/5xx)
            data = response.json()
            # Update cache
            _cache['data'] = data
            _cache['timestamp'] = now
            return data
        except (requests.RequestException, json.JSONDecodeError) as e:
            if attempt < 2:
                time.sleep(1)  # Wait 1s before retry
            else:
                # All retries failed — return error dict
                return {'success': False, 'cause': str(e)}

def invalidate_cache():
    """Force next fetch to hit the API."""
    _cache['data'] = None
    _cache['timestamp'] = 0

def save_bazaar_json():
    with open("bazaar.json", "w") as f:
        json.dump(get_bazaar_data(), f)

# ---- Single-product helpers (use cached data) ----

def get_product(product_id):
    data = get_bazaar_data()
    if not data.get('success'):
        print(f"Error fetching bazaar data: {data.get('cause', 'Unknown error')}")
        return None
    return data['products'].get(product_id)

def get_buy_summary(product_id):
    product = get_product(product_id)
    if product:
        return product.get('buy_summary', [])
    return []

def get_sell_summary(product_id):
    product = get_product(product_id)
    if product:
        return product.get('sell_summary', [])
    return []

def get_quick_status(product_id):
    product = get_product(product_id)
    if product:
        return product.get('quick_status', {})
    return {}

def getPrice(product_id, type='buy'):
    """
    Returns the best price. 
    type='buy' returns the lowest price people are selling for (instant buy price).
    type='sell' returns the highest price people are buying for (instant sell price).
    """
    quick_status = get_quick_status(product_id)
    if not quick_status:
        return 0

    if type == 'buy':
        return quick_status.get('buyPrice', 0)
    elif type == 'sell':
        return quick_status.get('sellPrice', 0)
    return 0

# ---- Bulk data extraction ----

def get_all_products():
    """Returns the full products dict from the API (cached)."""
    data = get_bazaar_data()
    if not data.get('success'):
        return {}
    return data.get('products', {})

def compute_price_stability(product):
    """
    Score 0–100. Measures how tightly clustered the top sell orders are.
    100 = all orders at the same price (very stable).
    0 = huge variance in the order book (volatile).
    Uses coefficient of variation of the top sell order prices.
    """
    sell_summary = product.get('sell_summary', [])
    if len(sell_summary) < 2:
        return 50  # not enough data, neutral score

    prices = [order['pricePerUnit'] for order in sell_summary[:10]]
    mean = statistics.mean(prices)
    if mean == 0:
        return 50

    stdev = statistics.stdev(prices)
    # Coefficient of variation (lower = more stable)
    cv = stdev / mean

    # Map CV to a 0-100 score: CV of 0 -> 100, CV of 0.5+ -> 0
    score = max(0, min(100, int((1 - cv / 0.5) * 100)))
    return score

def compute_volume_stability(quick_status):
    """
    Score 0–100. Compares current volume to weekly moving average.
    100 = volume today matches the weekly average perfectly.
    0 = massive deviation from weekly average.
    """
    sell_vol = quick_status.get('sellVolume', 0)
    buy_vol = quick_status.get('buyVolume', 0)
    sell_week = quick_status.get('sellMovingWeek', 0)
    buy_week = quick_status.get('buyMovingWeek', 0)

    # Weekly average per-day (divide by 7)
    sell_daily_avg = sell_week / 7 if sell_week > 0 else 0
    buy_daily_avg = buy_week / 7 if buy_week > 0 else 0

    if sell_daily_avg == 0 and buy_daily_avg == 0:
        return 50  # no data, neutral

    # Ratio of current volume to daily average (closer to 1.0 = stable)
    ratios = []
    if sell_daily_avg > 0:
        ratios.append(sell_vol / sell_daily_avg)
    if buy_daily_avg > 0:
        ratios.append(buy_vol / buy_daily_avg)

    avg_ratio = statistics.mean(ratios) if ratios else 1.0

    # Deviation from 1.0 (perfect match)
    deviation = abs(avg_ratio - 1.0)

    # Map deviation to score: 0 deviation -> 100, 2.0+ deviation -> 0
    score = max(0, min(100, int((1 - deviation / 2.0) * 100)))
    return score

def detect_spike(product):
    """
    Detects if the current margin is caused by a price spike.
    Returns (is_spike: bool, confidence: float 0-1).
    A spike is when few orders at extreme prices are inflating the margin.
    """
    buy_summary = product.get('buy_summary', [])
    sell_summary = product.get('sell_summary', [])
    quick_status = product.get('quick_status', {})

    buy_price = quick_status.get('buyPrice', 0)
    sell_price = quick_status.get('sellPrice', 0)

    if buy_price == 0 or sell_price == 0:
        return False, 0.0

    margin = buy_price - sell_price

    # If margin is tiny or negative, no spike
    if margin <= 0 or sell_price == 0:
        return False, 0.0

    margin_pct = (margin / sell_price) * 100

    # Check if the top buy order is an outlier (very few orders, high price)
    if len(buy_summary) >= 2:
        top_buy = buy_summary[0]
        second_buy = buy_summary[1]

        # If the top buy order has very few items AND its price is much
        # higher than the second order, it's likely a spike
        price_jump = (top_buy['pricePerUnit'] - second_buy['pricePerUnit'])
        price_jump_pct = (price_jump / second_buy['pricePerUnit'] * 100) if second_buy['pricePerUnit'] > 0 else 0

        if top_buy['orders'] <= 2 and price_jump_pct > 20 and top_buy['amount'] < 1000:
            confidence = min(1.0, price_jump_pct / 100)
            return True, confidence

    # Also check sell side for manipulation
    if len(sell_summary) >= 2:
        top_sell = sell_summary[0]
        second_sell = sell_summary[1]

        price_drop = (second_sell['pricePerUnit'] - top_sell['pricePerUnit'])
        price_drop_pct = (price_drop / top_sell['pricePerUnit'] * 100) if top_sell['pricePerUnit'] > 0 else 0

        if top_sell['orders'] <= 2 and price_drop_pct > 20 and top_sell['amount'] < 1000:
            confidence = min(1.0, price_drop_pct / 100)
            return True, confidence

    return False, 0.0

def get_all_items_summary():
    """
    Returns a list of dicts with computed data for every product.
    Each dict has: product_id, buy_price, sell_price, margin, margin_percent,
    buy_volume, sell_volume, buy_orders, sell_orders, buy_moving_week,
    sell_moving_week, price_stability, volume_stability, is_spike, spike_confidence.
    """
    products = get_all_products()
    items = []

    for pid, product in products.items():
        qs = product.get('quick_status', {})

        buy_price = qs.get('buyPrice', 0)
        sell_price = qs.get('sellPrice', 0)
        margin = buy_price - sell_price
        margin_pct = (margin / sell_price * 100) if sell_price > 0 else 0

        price_stab = compute_price_stability(product)
        vol_stab = compute_volume_stability(qs)
        is_spike, spike_conf = detect_spike(product)

        items.append({
            'product_id': pid,
            'buy_price': round(buy_price, 2),
            'sell_price': round(sell_price, 2),
            'margin': round(margin, 2),
            'margin_percent': round(margin_pct, 2),
            'buy_volume': qs.get('buyVolume', 0),
            'sell_volume': qs.get('sellVolume', 0),
            'buy_orders': qs.get('buyOrders', 0),
            'sell_orders': qs.get('sellOrders', 0),
            'buy_moving_week': qs.get('buyMovingWeek', 0),
            'sell_moving_week': qs.get('sellMovingWeek', 0),
            'price_stability': price_stab,
            'volume_stability': vol_stab,
            'is_spike': is_spike,
            'spike_confidence': round(spike_conf, 2),
        })

    return items
