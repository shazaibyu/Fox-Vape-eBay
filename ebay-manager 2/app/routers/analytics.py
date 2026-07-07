import csv
import io
import datetime
from collections import defaultdict
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Order

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def _active(db):
    """All non-refunded orders."""
    return db.query(Order).filter(Order.refunded == False)  # noqa: E712


@router.get("/summary")
def summary(db: Session = Depends(get_db)):
    orders = _active(db).all()
    now = datetime.datetime.utcnow()
    month_ago = now - datetime.timedelta(days=30)

    def stats(subset):
        revenue = sum((o.sale_price or 0) + (o.shipping_charged or 0) for o in subset)
        profit = sum(o.profit or 0 for o in subset)
        count = len(subset)
        return {
            "revenue": round(revenue, 2),
            "profit": round(profit, 2),
            "orders": count,
            "avg_profit": round(profit / count, 2) if count else 0,
        }

    recent = [o for o in orders if o.order_date and o.order_date >= month_ago]
    refunded_count = db.query(Order).filter(Order.refunded == True).count()  # noqa: E712
    return {
        "all_time": stats(orders),
        "last_30_days": stats(recent),
        "refunded_orders": refunded_count,
    }


@router.get("/monthly")
def monthly(db: Session = Depends(get_db)):
    """Profit and revenue by month for the last 12 months."""
    orders = _active(db).filter(Order.order_date != None).all()  # noqa: E711
    buckets = defaultdict(lambda: {"revenue": 0.0, "profit": 0.0, "orders": 0})
    for o in orders:
        key = o.order_date.strftime("%Y-%m")
        buckets[key]["revenue"] += (o.sale_price or 0) + (o.shipping_charged or 0)
        buckets[key]["profit"] += o.profit or 0
        buckets[key]["orders"] += 1

    # last 12 months in order
    months = []
    now = datetime.datetime.utcnow().replace(day=1)
    for i in range(11, -1, -1):
        m = now - datetime.timedelta(days=30 * i)
        months.append(m.strftime("%Y-%m"))
    months = sorted(set(months))

    return [
        {
            "month": m,
            "revenue": round(buckets[m]["revenue"], 2),
            "profit": round(buckets[m]["profit"], 2),
            "orders": buckets[m]["orders"],
        }
        for m in months
    ]


@router.get("/top-items")
def top_items(db: Session = Depends(get_db)):
    """Top 10 items by total profit."""
    orders = _active(db).all()
    buckets = defaultdict(lambda: {"profit": 0.0, "revenue": 0.0, "orders": 0})
    for o in orders:
        key = o.item_title or "(unknown item)"
        buckets[key]["profit"] += o.profit or 0
        buckets[key]["revenue"] += (o.sale_price or 0) + (o.shipping_charged or 0)
        buckets[key]["orders"] += 1
    ranked = sorted(buckets.items(), key=lambda kv: kv[1]["profit"], reverse=True)[:10]
    return [
        {"item": k, "profit": round(v["profit"], 2), "revenue": round(v["revenue"], 2),
         "orders": v["orders"]}
        for k, v in ranked
    ]


@router.get("/export.csv")
def export_csv(db: Session = Depends(get_db)):
    """Download all orders as a CSV spreadsheet."""
    orders = db.query(Order).order_by(Order.order_date.desc()).all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([
        "Order ID", "Date", "Buyer", "Item", "Qty", "Sale Price", "Postage Charged",
        "Tracking", "Carrier", "Item Cost", "Shipping Cost", "Shipping Est?",
        "eBay Fee", "Age Verification", "Profit", "Refunded", "Status",
    ])
    for o in orders:
        w.writerow([
            o.ebay_order_id,
            o.order_date.strftime("%Y-%m-%d") if o.order_date else "",
            o.buyer_username or "", o.item_title or "", o.quantity,
            o.sale_price, o.shipping_charged, o.tracking_number or "",
            o.carrier or "", o.item_cost, o.shipping_cost,
            "yes" if o.shipping_cost_is_estimated else "no",
            o.ebay_fee, o.age_verification_fee, o.profit,
            "yes" if o.refunded else "no", o.status or "",
        ])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=orders.csv"},
    )
