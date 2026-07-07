"""
Products & Costs: set ONE unit cost per product and it's applied to every
order of that product (unit cost x quantity), past and future, then profit
is recalculated. Products are grouped by SKU when the listing has one,
otherwise by exact item title.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Order, ProductCost, Settings
from .orders import _recalc

router = APIRouter(prefix="/api/products", tags=["products"])


def product_key(sku, title):
    if sku:
        return f"sku:{sku}"
    return f"title:{title or '(unknown)'}"


@router.get("")
def list_products(db: Session = Depends(get_db)):
    """Distinct products across all orders, with order counts and current cost."""
    orders = db.query(Order).all()
    costs = {c.product_key: c.unit_cost for c in db.query(ProductCost).all()}

    groups = {}
    for o in orders:
        key = product_key(o.sku, o.item_title)
        if key not in groups:
            groups[key] = {
                "product_key": key,
                "title": o.item_title or "(unknown)",
                "sku": o.sku,
                "orders": 0,
                "units": 0,
                "unit_cost": costs.get(key, 0.0),
            }
        groups[key]["orders"] += 1
        groups[key]["units"] += o.quantity or 1
    return sorted(groups.values(), key=lambda g: -g["orders"])


@router.post("/cost")
def set_cost(key: str, unit_cost: float, db: Session = Depends(get_db)):
    """Save a unit cost for a product and apply it to ALL its orders."""
    settings = db.query(Settings).first()

    row = db.query(ProductCost).filter(ProductCost.product_key == key).first()
    if not row:
        row = ProductCost(product_key=key)
        db.add(row)
    row.unit_cost = unit_cost

    # apply to all matching orders
    updated = 0
    for o in db.query(Order).all():
        if product_key(o.sku, o.item_title) == key:
            o.item_cost = round(unit_cost * (o.quantity or 1), 2)
            _recalc(o, settings)
            updated += 1
    db.commit()
    return {"ok": True, "orders_updated": updated}
