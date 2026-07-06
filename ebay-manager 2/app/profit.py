"""
Per-order profit calculation.

profit = sale_price + shipping_charged
         - item_cost
         - shipping_cost (actual/estimated)
         - ebay_fee (actual if eBay returns it, else estimated)
         - age_verification_fee (flat, default 0.54)
"""


def calculate_ebay_fee(sale_price, shipping_charged, fee_percent, fee_fixed):
    """Estimate eBay's final value fee when the real figure isn't on the
    order payload. eBay charges a % of (item price + shipping + tax) plus
    a small fixed per-order amount - adjust fee_percent/fee_fixed in
    Settings to match your actual category rate."""
    gross = (sale_price or 0) + (shipping_charged or 0)
    return round(gross * (fee_percent / 100.0) + fee_fixed, 2)


def calculate_profit(sale_price, shipping_charged, item_cost, shipping_cost,
                      ebay_fee, age_verification_fee):
    revenue = (sale_price or 0) + (shipping_charged or 0)
    costs = (item_cost or 0) + (shipping_cost or 0) + (ebay_fee or 0) + (age_verification_fee or 0)
    return round(revenue - costs, 2)
