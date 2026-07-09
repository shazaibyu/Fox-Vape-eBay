"""
Products & Costs with flavour-aware grouping.

Grouping rules:
- A "keyword group" (e.g. "bar juice 5000") matches EVERY order whose title
  contains that keyword, so all flavours collapse into one product row with
  one shared unit cost. Keyword groups are created by the seller.
- Anything not covered by a keyword group is grouped by exact title.
- SKUs are ignored for grouping, because eBay gives each flavour/variation
  its own SKU, which is exactly what caused the duplicated rows before.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Order, ProductCost, Settings
from .orders import _recalc

router = APIRouter(prefix="/api/products", tags=["products"])


def resolve_key(title, kw_list):
    """kw_list: lowercase keywords from saved keyword groups."""
    t = (title or "").lower()
    for kw in kw_list:
        if kw in t:
            return f"kw:{kw}"
    return f"title:{title or '(unknown)'}"


def _kw_list(db):
    return [c.product_key[3:] for c in db.query(ProductCost).all()
            if c.product_key.startswith("kw:")]


@router.get("")
def list_products(db: Session = Depends(get_db)):
    orders = db.query(Order).all()
    costs = {c.product_key: c.unit_cost for c in db.query(ProductCost).all()}
    kws = [k[3:] for k in costs if k.startswith("kw:")]

    groups = {}
    for o in orders:
        key = resolve_key(o.item_title, kws)
        if key not in groups:
            display = key[3:].title() if key.startswith("kw:") else (o.item_title or "(unknown)")
            groups[key] = {
                "product_key": key,
                "title": display,
                "is_group": key.startswith("kw:"),
                "orders": 0, "units": 0,
                "unit_cost": costs.get(key, 0.0),
            }
        groups[key]["orders"] += 1
        groups[key]["units"] += o.quantity or 1
    return sorted(groups.values(), key=lambda g: -g["orders"])


@router.post("/group")
def create_group(keyword: str, unit_cost: float, db: Session = Depends(get_db)):
    """Create a keyword group (e.g. 'bar juice 5000') so all flavours share
    one row and one cost, then apply the cost to every matching order."""
    keyword = keyword.strip().lower()
    if not keyword:
        return {"error": "Keyword can't be empty"}
    key = f"kw:{keyword}"
    row = db.query(ProductCost).filter(ProductCost.product_key == key).first()
    if not row:
        row = ProductCost(product_key=key)
        db.add(row)
    row.unit_cost = unit_cost
    db.flush()

    settings = db.query(Settings).first()
    updated = 0
    for o in db.query(Order).all():
        if keyword in (o.item_title or "").lower():
            o.item_cost = round(unit_cost * (o.quantity or 1), 2)
            _recalc(o, settings)
            updated += 1
    db.commit()
    return {"ok": True, "orders_updated": updated}


@router.post("/cost")
def set_cost(key: str, unit_cost: float, db: Session = Depends(get_db)):
    """Update the unit cost on an existing group/title and re-apply."""
    settings = db.query(Settings).first()
    row = db.query(ProductCost).filter(ProductCost.product_key == key).first()
    if not row:
        row = ProductCost(product_key=key)
        db.add(row)
    row.unit_cost = unit_cost
    db.flush()

    kws = _kw_list(db)
    updated = 0
    for o in db.query(Order).all():
        if resolve_key(o.item_title, kws) == key:
            o.item_cost = round(unit_cost * (o.quantity or 1), 2)
            _recalc(o, settings)
            updated += 1
    db.commit()
    return {"ok": True, "orders_updated": updated}


@router.delete("/group")
def delete_group(key: str, db: Session = Depends(get_db)):
    db.query(ProductCost).filter(ProductCost.product_key == key).delete()
    db.commit()
    return {"ok": True}
