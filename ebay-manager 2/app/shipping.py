"""
IMPORTANT HONESTY NOTE (read this before trusting the numbers):
A tracking number's *format* tells you the carrier and often the service,
but it does NOT encode what you paid for postage. There is no carrier in
the world that hides "price paid" inside the tracking number string.

So this module does two things:
1. Detects the carrier + likely service from the tracking number pattern.
2. Resolves an actual COST for that shipment using, in priority order:
   a) A real cost pulled from your shipping-label provider's API/account,
      if you've connected one (e.g. Royal Mail Click & Drop export, a
      courier account, or eBay label purchase data if present on the order).
   b) A fallback default rate you set per carrier/service in Settings.
   c) £0.00 flagged as "unresolved" if neither is available, so it's
      obvious in the UI rather than silently wrong.
"""
import re
from .database import SessionLocal
from .models import ShippingRate

CARRIER_PATTERNS = [
    # (carrier, service guess, regex)
    ("Royal Mail", "Tracked 24/48", re.compile(r"^[A-Z]{2}\d{9}GB$")),
    ("Royal Mail", "Special Delivery", re.compile(r"^[A-Z]{2}\d{9}GB$")),
    ("Evri (Hermes)", "Standard", re.compile(r"^\d{16}$")),
    ("DPD", "Standard/Next Day", re.compile(r"^\d{14}$")),
    ("DPD", "Standard", re.compile(r"^\d{10}$")),
    ("UPS", "Standard", re.compile(r"^1Z[0-9A-Z]{16}$")),
    ("FedEx", "Standard", re.compile(r"^\d{12}$")),
    ("FedEx", "Express", re.compile(r"^\d{15}$")),
    ("Yodel", "Standard", re.compile(r"^\d{16,18}$")),
    ("DHL", "Standard", re.compile(r"^\d{10,11}$")),
]


def detect_carrier(tracking_number: str):
    if not tracking_number:
        return None, None
    cleaned = tracking_number.strip().upper().replace(" ", "")
    for carrier, service, pattern in CARRIER_PATTERNS:
        if pattern.match(cleaned):
            return carrier, service
    return "Unknown", None


def resolve_shipping_cost(tracking_number: str, real_label_cost: float = None):
    """
    real_label_cost: pass this in if you already have the actual cost from
    a connected label/courier account for this shipment. If given, it's
    always trusted over the fallback table.

    Returns: (carrier, cost, is_estimated)
    """
    carrier, service = detect_carrier(tracking_number)

    if real_label_cost is not None:
        return carrier, round(real_label_cost, 2), False

    db = SessionLocal()
    try:
        rate = (
            db.query(ShippingRate)
            .filter(ShippingRate.carrier == carrier)
            .filter(ShippingRate.service_name == service)
            .first()
        )
        if not rate:
            # try carrier-only match if exact service isn't configured
            rate = db.query(ShippingRate).filter(ShippingRate.carrier == carrier).first()
        if rate:
            return carrier, round(rate.default_cost, 2), True
        return carrier, 0.0, True
    finally:
        db.close()
