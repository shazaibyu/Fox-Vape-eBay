import json
import datetime
import requests
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Order, Settings
from .. import ebay_client
from ..shipping import resolve_shipping_cost
from ..profit import calculate_ebay_fee, calculate_profit

router = APIRouter(prefix="/api/orders", tags=["orders"])

# Only look up tracking for orders newer than this - tracking lookups cost
# one extra eBay API call per order, which is what made big imports time out.
TRACKING_LOOKUP_DAYS = 45


def _parse_dt(iso_str):
    """Parse eBay's ISO timestamps like 2026-07-01T10:00:00.000Z."""
    if not iso_str:
        return None
    try:
        return datetime.datetime.strptime(iso_str[:19], "%Y-%m-%dT%H:%M:%S")
    except Exception:
        return None


def compute_fulfillment_status(o: Order, now=None):
    """Derive a seller-friendly status from eBay's raw data.

    Note: 'past_est_delivery' means the estimated delivery window has passed,
    NOT confirmed delivery - eBay's API doesn't expose carrier delivery
    confirmation, so we stay honest and label it as an estimate.
    """
    now = now or datetime.datetime.utcnow()
    is_shipped = (o.status == "FULFILLED") or bool(o.shipped_date)

    if o.refunded:
        return "refunded"

    if not is_shipped:
        if o.ship_by_date:
            if now > o.ship_by_date:
                return "overdue"
            if (o.ship_by_date - now) <= datetime.timedelta(hours=24):
                return "due_24h"
        return "awaiting_dispatch"

    # shipped
    if o.shipped_date and o.ship_by_date and o.shipped_date > o.ship_by_date:
        return "shipped_late"
    if o.max_delivery_date and now > o.max_delivery_date:
        return "past_est_delivery"
    return "shipped"


def _recalc(order: Order, settings: Settings):
    if order.ebay_fee_is_estimated:
        order.ebay_fee = calculate_ebay_fee(
            order.sale_price, order.shipping_charged,
            settings.ebay_fee_percent, settings.ebay_fee_fixed,
        )
    order.age_verification_fee = settings.age_verification_fee
    order.profit = calculate_profit(
        order.sale_price, order.shipping_charged, order.item_cost,
        order.shipping_cost, order.ebay_fee, order.age_verification_fee,
    )


def _get_tracking_for_order(order_id, base_url, headers):
    try:
        r = requests.get(
            f"{base_url}/sell/fulfillment/v1/order/{order_id}/shipping_fulfillment",
            headers=headers,
            timeout=10,
        )
        r.raise_for_status()
        fulfillments = r.json().get("fulfillments", [])
        if fulfillments:
            f = fulfillments[0]
            return (
                f.get("shipmentTrackingNumber"),
                f.get("shippingCarrierCode"),
                _parse_dt(f.get("shippedDate")),
            )
    except Exception:
        pass
    return None, None, None


@router.get("")
def list_orders(db: Session = Depends(get_db)):
    orders = db.query(Order).order_by(Order.order_date.desc()).all()
    now = datetime.datetime.utcnow()
    return [
        {
            "ebay_order_id": o.ebay_order_id,
            "buyer_username": o.buyer_username,
            "item_title": o.item_title,
            "sku": o.sku,
            "quantity": o.quantity,
            "sale_price": o.sale_price,
            "shipping_charged": o.shipping_charged,
            "order_date": o.order_date.isoformat() if o.order_date else None,
            "status": o.status,
            "fulfillment_status": compute_fulfillment_status(o, now),
            "ship_by_date": o.ship_by_date.isoformat() if o.ship_by_date else None,
            "shipped_date": o.shipped_date.isoformat() if o.shipped_date else None,
            "max_delivery_date": o.max_delivery_date.isoformat() if o.max_delivery_date else None,
            "tracking_number": o.tracking_number,
            "carrier": o.carrier,
            "shipping_cost": o.shipping_cost,
            "shipping_cost_is_estimated": o.shipping_cost_is_estimated,
            "item_cost": o.item_cost,
            "ebay_fee": o.ebay_fee,
            "ebay_fee_is_estimated": o.ebay_fee_is_estimated,
            "age_verification_fee": o.age_verification_fee,
            "refunded": bool(o.refunded),
            "profit": o.profit,
        }
        for o in orders
    ]


@router.post("/sync")
def sync_orders(db: Session = Depends(get_db)):
    """Imports orders page-by-page (200 at a time), committing after EVERY
    page so a timeout or crash never loses already-fetched orders. Tracking
    lookups only happen for recent orders missing a tracking number."""
    settings = db.query(Settings).first()
    base_url = "https://api.sandbox.ebay.com" if settings.ebay_environment == "sandbox" else "https://api.ebay.com"

    try:
        token = ebay_client.get_access_token()
    except Exception as e:
        return {"error": str(e)}
    headers = {"Authorization": f"Bearer {token}"}

    imported = 0
    tracking_lookups = 0
    revenue_seen = 0.0
    offset = 0
    limit = 200
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=TRACKING_LOOKUP_DAYS)

    while True:
        try:
            r = requests.get(
                f"{base_url}/sell/fulfillment/v1/order",
                headers=headers,
                params={"limit": limit, "offset": offset},
                timeout=25,
            )
            if not r.ok:
                db.commit()
                return {
                    "imported": imported,
                    "error": f"eBay order fetch failed at offset {offset} ({r.status_code}): {r.text[:300]}",
                }
            data = r.json()
        except Exception as e:
            db.commit()
            return {"imported": imported, "error": f"Stopped at offset {offset}: {e}"}

        batch = data.get("orders", [])
        if not batch:
            break

        for ro in batch:
            oid = ro.get("orderId")
            if not oid:
                continue
            row = db.query(Order).filter(Order.ebay_order_id == oid).first()
            if not row:
                row = Order(ebay_order_id=oid, item_cost=0.0)
                db.add(row)

            line_items = ro.get("lineItems", [])
            first_item = line_items[0] if line_items else {}

            sale_price = sum(float(li.get("total", {}).get("value", 0)) for li in line_items)
            shipping_charged = sum(
                float(li.get("deliveryCost", {}).get("shippingCost", {}).get("value", 0))
                for li in line_items
            )
            revenue_seen += sale_price + shipping_charged

            row.buyer_username = ro.get("buyer", {}).get("username")
            row.item_title = first_item.get("title")
            row.sku = first_item.get("sku")
            row.quantity = sum(int(li.get("quantity", 1)) for li in line_items) or 1
            row.sale_price = sale_price
            row.shipping_charged = shipping_charged
            created = ro.get("creationDate")
            if created:
                row.order_date = datetime.datetime.strptime(created[:19], "%Y-%m-%dT%H:%M:%S")
            row.status = ro.get("orderFulfillmentStatus")
            if ro.get("orderPaymentStatus", "") == "FULLY_REFUNDED":
                row.refunded = True
            row.raw_json = json.dumps(ro)

            # Dispatch deadline + estimated delivery window from line items
            instr = first_item.get("lineItemFulfillmentInstructions", {})
            row.ship_by_date = _parse_dt(instr.get("shipByDate")) or row.ship_by_date
            row.max_delivery_date = _parse_dt(instr.get("maxEstimatedDeliveryDate")) or row.max_delivery_date

            # Tracking lookup: for recent orders missing tracking OR shipped date
            needs_lookup = (
                row.order_date and row.order_date >= cutoff
                and (not row.tracking_number or (row.status == "FULFILLED" and not row.shipped_date))
            )
            if needs_lookup:
                tracking, carrier_code, shipped_dt = _get_tracking_for_order(oid, base_url, headers)
                tracking_lookups += 1
                if shipped_dt:
                    row.shipped_date = shipped_dt
                if tracking and not row.tracking_number:
                    row.tracking_number = tracking
                    carrier, cost, estimated = resolve_shipping_cost(tracking)
                    row.carrier = carrier or carrier_code
                    row.shipping_cost = cost
                    row.shipping_cost_is_estimated = estimated

            if row.item_cost is None:
                row.item_cost = 0.0
            _recalc(row, settings)
            imported += 1

        db.commit()  # save every page - progress is never lost

        total = data.get("total", 0)
        offset += limit
        if offset >= total:
            break

    return {
        "imported": imported,
        "revenue_imported": round(revenue_seen, 2),
        "tracking_lookups": tracking_lookups,
    }


@router.post("/{order_id}/edit")
def edit_order(order_id: str, item_cost: float = None, shipping_cost: float = None,
                refunded: bool = None, db: Session = Depends(get_db)):
    settings = db.query(Settings).first()
    order = db.query(Order).filter(Order.ebay_order_id == order_id).first()
    if not order:
        return {"error": "not found"}
    if item_cost is not None:
        order.item_cost = item_cost
    if shipping_cost is not None:
        order.shipping_cost = shipping_cost
        order.shipping_cost_is_estimated = False
    if refunded is not None:
        order.refunded = refunded
    _recalc(order, settings)
    db.commit()
    return {"ok": True, "profit": order.profit}
