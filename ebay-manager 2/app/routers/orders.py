import csv
import io
import json
import threading
import datetime
import requests
from fastapi import APIRouter, Depends, UploadFile, File
from sqlalchemy.orm import Session
from ..database import get_db, SessionLocal
from ..models import Order, Settings, ProductCost
from .. import ebay_client
from ..shipping import resolve_shipping_cost
from ..profit import calculate_ebay_fee, calculate_profit

router = APIRouter(prefix="/api/orders", tags=["orders"])

TRACKING_LOOKUP_DAYS = 45

# Background import state - lets the import run without freezing the page,
# while the frontend polls /sync/status for live progress.
SYNC_STATE = {
    "running": False, "imported": 0, "total": 0,
    "revenue": 0.0, "error": None, "finished_at": None,
}


def _parse_dt(iso_str):
    if not iso_str:
        return None
    try:
        return datetime.datetime.strptime(iso_str[:19], "%Y-%m-%dT%H:%M:%S")
    except Exception:
        return None


def compute_fulfillment_status(o: Order, now=None):
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


def _product_key(sku, title):
    return f"sku:{sku}" if sku else f"title:{title or '(unknown)'}"


def _get_tracking_for_order(order_id, base_url, headers):
    try:
        r = requests.get(
            f"{base_url}/sell/fulfillment/v1/order/{order_id}/shipping_fulfillment",
            headers=headers, timeout=10,
        )
        r.raise_for_status()
        fulfillments = r.json().get("fulfillments", [])
        if fulfillments:
            f = fulfillments[0]
            return (f.get("shipmentTrackingNumber"), f.get("shippingCarrierCode"),
                    _parse_dt(f.get("shippedDate")))
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


def _run_sync():
    """The actual import, run in a background thread with its own DB session."""
    db = SessionLocal()
    try:
        settings = db.query(Settings).first()
        base_url = ("https://api.sandbox.ebay.com" if settings.ebay_environment == "sandbox"
                    else "https://api.ebay.com")
        token = ebay_client.get_access_token()
        headers = {"Authorization": f"Bearer {token}"}
        product_costs = {c.product_key: c.unit_cost for c in db.query(ProductCost).all()}

        offset, limit = 0, 200
        cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=TRACKING_LOOKUP_DAYS)

        while True:
            r = requests.get(
                f"{base_url}/sell/fulfillment/v1/order",
                headers=headers, params={"limit": limit, "offset": offset}, timeout=25,
            )
            if not r.ok:
                SYNC_STATE["error"] = f"eBay fetch failed at {offset} ({r.status_code}): {r.text[:200]}"
                break
            data = r.json()
            batch = data.get("orders", [])
            if not batch:
                break
            SYNC_STATE["total"] = data.get("total", 0)

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
                SYNC_STATE["revenue"] += sale_price + shipping_charged

                row.buyer_username = ro.get("buyer", {}).get("username")
                row.item_title = first_item.get("title")
                row.sku = first_item.get("sku")
                row.quantity = sum(int(li.get("quantity", 1)) for li in line_items) or 1
                row.sale_price = sale_price
                row.shipping_charged = shipping_charged
                row.order_date = _parse_dt(ro.get("creationDate"))
                row.status = ro.get("orderFulfillmentStatus")
                if ro.get("orderPaymentStatus", "") == "FULLY_REFUNDED":
                    row.refunded = True
                row.raw_json = json.dumps(ro)

                instr = first_item.get("lineItemFulfillmentInstructions", {})
                row.ship_by_date = _parse_dt(instr.get("shipByDate")) or row.ship_by_date
                row.max_delivery_date = _parse_dt(instr.get("maxEstimatedDeliveryDate")) or row.max_delivery_date

                needs_lookup = (
                    row.order_date and row.order_date >= cutoff
                    and (not row.tracking_number or (row.status == "FULFILLED" and not row.shipped_date))
                )
                if needs_lookup:
                    tracking, carrier_code, shipped_dt = _get_tracking_for_order(oid, base_url, headers)
                    if shipped_dt:
                        row.shipped_date = shipped_dt
                    if tracking and not row.tracking_number:
                        row.tracking_number = tracking
                        carrier, cost, estimated = resolve_shipping_cost(tracking)
                        row.carrier = carrier or carrier_code
                        row.shipping_cost = cost
                        row.shipping_cost_is_estimated = estimated

                # apply saved product unit cost if no cost set yet
                if not row.item_cost:
                    key = _product_key(row.sku, row.item_title)
                    if key in product_costs:
                        row.item_cost = round(product_costs[key] * (row.quantity or 1), 2)

                _recalc(row, settings)
                SYNC_STATE["imported"] += 1

            db.commit()  # progress saved every page
            offset += limit
            if offset >= data.get("total", 0):
                break
    except Exception as e:
        SYNC_STATE["error"] = str(e)
        db.rollback()
    finally:
        db.commit()
        db.close()
        SYNC_STATE["running"] = False
        SYNC_STATE["finished_at"] = datetime.datetime.utcnow().isoformat()


@router.post("/sync")
def sync_orders():
    """Kick off the import in the background and return immediately.
    The page stays responsive and polls /sync/status for progress."""
    if SYNC_STATE["running"]:
        return {"started": False, "message": "Import already running"}
    SYNC_STATE.update({"running": True, "imported": 0, "total": 0,
                       "revenue": 0.0, "error": None, "finished_at": None})
    threading.Thread(target=_run_sync, daemon=True).start()
    return {"started": True}


@router.get("/sync/status")
def sync_status():
    return {
        "running": SYNC_STATE["running"],
        "imported": SYNC_STATE["imported"],
        "total": SYNC_STATE["total"],
        "revenue": round(SYNC_STATE["revenue"], 2),
        "error": SYNC_STATE["error"],
    }


@router.post("/sync-fees")
def sync_fees(db: Session = Depends(get_db)):
    """Pull REAL per-order fees from eBay's Finances API and replace the
    estimates. Requires reconnecting to eBay once after this update
    (Settings -> Connect to eBay) to grant the new permission."""
    try:
        fees = ebay_client.fetch_order_fees()
    except Exception as e:
        return {"error": str(e)}

    settings = db.query(Settings).first()
    updated = 0
    for o in db.query(Order).all():
        if o.ebay_order_id in fees:
            o.ebay_fee = round(fees[o.ebay_order_id], 2)
            o.ebay_fee_is_estimated = False
            o.profit = calculate_profit(
                o.sale_price, o.shipping_charged, o.item_cost,
                o.shipping_cost, o.ebay_fee, o.age_verification_fee,
            )
            updated += 1
    db.commit()
    return {"ok": True, "orders_updated": updated, "fees_found": len(fees)}


@router.post("/import-csv")
async def import_csv(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Import older orders (beyond eBay's 90-day API window) from a Seller
    Hub order report CSV. Column names are matched loosely, so most report
    formats work."""
    settings = db.query(Settings).first()
    raw = (await file.read()).decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(raw))
    if not reader.fieldnames:
        return {"error": "Couldn't read any columns from that file."}

    def find_col(*candidates):
        for c in reader.fieldnames:
            cl = c.lower().strip()
            for cand in candidates:
                if cand in cl:
                    return c
        return None

    col_order = find_col("order number", "order id", "sales record")
    col_buyer = find_col("buyer username", "buyer user id", "user id")
    col_title = find_col("item title", "title")
    col_qty = find_col("quantity")
    col_price = find_col("sold for", "total price", "sale price", "item subtotal")
    col_post = find_col("postage and packaging", "shipping and handling", "p&p")
    col_date = find_col("sale date", "order creation date", "paid on date", "date sold")

    if not col_order:
        return {"error": f"No order-number column found. Columns seen: {reader.fieldnames}"}

    def parse_money(v):
        if not v:
            return 0.0
        return float(str(v).replace("£", "").replace("$", "").replace(",", "").strip() or 0)

    def parse_date(v):
        if not v:
            return None
        for fmt in ("%d-%b-%y", "%d/%m/%Y", "%Y-%m-%d", "%d %b %Y", "%m/%d/%Y", "%d-%m-%Y"):
            try:
                return datetime.datetime.strptime(v.strip(), fmt)
            except Exception:
                continue
        return None

    product_costs = {c.product_key: c.unit_cost for c in db.query(ProductCost).all()}
    imported, skipped = 0, 0
    for rec in reader:
        oid = (rec.get(col_order) or "").strip()
        if not oid:
            skipped += 1
            continue
        row = db.query(Order).filter(Order.ebay_order_id == oid).first()
        if not row:
            row = Order(ebay_order_id=oid, item_cost=0.0)
            db.add(row)
        row.buyer_username = (rec.get(col_buyer) or "").strip() if col_buyer else row.buyer_username
        row.item_title = (rec.get(col_title) or "").strip() if col_title else row.item_title
        row.quantity = int(parse_money(rec.get(col_qty)) or 1) if col_qty else (row.quantity or 1)
        row.sale_price = parse_money(rec.get(col_price)) if col_price else row.sale_price
        row.shipping_charged = parse_money(rec.get(col_post)) if col_post else row.shipping_charged
        if col_date and not row.order_date:
            row.order_date = parse_date(rec.get(col_date))
        if not row.status:
            row.status = "FULFILLED"  # historical orders are long shipped

        if not row.item_cost:
            key = _product_key(row.sku, row.item_title)
            if key in product_costs:
                row.item_cost = round(product_costs[key] * (row.quantity or 1), 2)
        _recalc(row, settings)
        imported += 1

    db.commit()
    return {"ok": True, "imported": imported, "skipped": skipped}


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
