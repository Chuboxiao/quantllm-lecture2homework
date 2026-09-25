"""Pure data helpers; no API imports or order placement."""
import math
from datetime import date


def valid_price(value):
    try:
        p = float(value)
        return p if math.isfinite(p) and 0 < p < 1e100 else None
    except (TypeError, ValueError):
        return None


def candidates(contracts, products, per_product=6, today=None):
    today = today or date.today().strftime('%Y%m%d')
    result = []
    for product in products:
        rows = [c for c in contracts.values()
                if c.get('ProductID') == product and c.get('ProductClass') == '1'
                and c.get('IsTrading') and c.get('ExpireDate', '') >= today]
        rows.sort(key=lambda c: (c.get('ExpireDate', ''), c['InstrumentID']))
        result.extend(c['InstrumentID'] for c in rows[:per_product])
    return result


def rank_active(contracts, stats, products):
    """One valid, actually updating candidate per product, ranked by cumulative volume."""
    selected = []
    for product in products:
        rows = [(s['volume'], s['ticks'], symbol) for symbol, s in stats.items()
                if contracts.get(symbol, {}).get('ProductID') == product
                and s['ticks'] >= 2 and s['changes'] >= 1 and s['last_price'] is not None]
        if rows:
            selected.append(max(rows)[2])
    return selected
