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


def _recalc(order: Order, settings: Settings):
    if not order.ebay_fee_is_estimated:
        pass  # keep real fee if we already have one
    else:
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
    """Fulfillment API keeps tracking info under a sub-resource."""
    try:
        r = requests.get(
            f"{base_url}/sell/fulfillment/v1/order/{order_id}/shipping_fulfillment",
            headers=headers,
            timeout=15,
        )
        r.raise_for_status()
        fulfillments = r.json().get("fulfillments", [])
        if fulfillments:
            f = fulfillments[0]
            return f.get("shipmentTrackingNumber"), f.get("shippingCarrierCode")
    except Exception:
        pass
    return None, None


@router.get("")
def list_orders(db: Session = Depends(get_db)):
    orders = db.query(Order).order_by(Order.order_date.desc()).all()
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
    settings = db.query(Settings).first()
    base_url = "https://api.sandbox.ebay.com" if settings.ebay_environment == "sandbox" else "https://api.ebay.com"

    try:
        headers = {"Authorization": f"Bearer {ebay_client.get_access_token()}"}
        remote_orders = ebay_client.fetch_orders()
    except Exception as e:
        return {"error": str(e)}

    imported = 0
    for ro in remote_orders:
        oid = ro.get("orderId")
        if not oid:
            continue
        row = db.query(Order).filter(Order.ebay_order_id == oid).first()
        if not row:
            row = Order(ebay_order_id=oid)
            db.add(row)

        buyer = ro.get("buyer", {}).get("username")
        line_items = ro.get("lineItems", [])
        first_item = line_items[0] if line_items else {}

        sale_price = sum(
            float(li.get("total", {}).get("value", 0)) for li in line_items
        )
        shipping_charged = sum(
            float(li.get("deliveryCost", {}).get("shippingCost", {}).get("value", 0))
            for li in line_items
        )

        row.buyer_username = buyer
        row.item_title = first_item.get("title")
        row.sku = first_item.get("sku")
        row.quantity = sum(int(li.get("quantity", 1)) for li in line_items) or 1
        row.sale_price = sale_price
        row.shipping_charged = shipping_charged
        created = ro.get("creationDate")
        if created:
            row.order_date = datetime.datetime.strptime(created[:19], "%Y-%m-%dT%H:%M:%S")
        row.status = ro.get("orderFulfillmentStatus")
        payment_status = ro.get("orderPaymentStatus", "")
        if payment_status == "FULLY_REFUNDED":
            row.refunded = True
        row.raw_json = json.dumps(ro)

        tracking, carrier_code = _get_tracking_for_order(oid, base_url, headers)
        row.tracking_number = tracking

        carrier, cost, estimated = resolve_shipping_cost(tracking) if tracking else (None, 0.0, True)
        row.carrier = carrier or carrier_code
        row.shipping_cost = cost
        row.shipping_cost_is_estimated = estimated

        # keep any manually-edited item_cost the seller already entered
        if row.item_cost is None:
            row.item_cost = 0.0

        _recalc(row, settings)
        imported += 1

    db.commit()
    return {"imported": imported}


@router.post("/{order_id}/edit")
def edit_order(order_id: str, item_cost: float = None, shipping_cost: float = None,
                refunded: bool = None, db: Session = Depends(get_db)):
    """Lets you manually correct the item cost (eBay has no idea what YOU
    paid for stock), override an estimated shipping cost with the real one,
    or mark an order refunded so it's excluded from profit totals."""
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
