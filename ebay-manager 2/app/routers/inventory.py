import datetime
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import InventoryItem
from .. import ebay_client

router = APIRouter(prefix="/api/inventory", tags=["inventory"])


@router.get("")
def list_inventory(db: Session = Depends(get_db)):
    items = db.query(InventoryItem).all()
    return [
        {
            "sku": i.sku,
            "ebay_item_id": i.ebay_item_id,
            "title": i.title,
            "quantity": i.quantity,
            "price": i.price,
            "image_url": i.image_url,
            "last_synced": i.last_synced.isoformat() if i.last_synced else None,
        }
        for i in items
    ]


@router.post("/add")
def add_item(title: str, quantity: int = 0, sku: str = None, db: Session = Depends(get_db)):
    """Manually add a product/flavour to inventory. Stock deducts
    automatically when new orders for it import."""
    key = sku or f"manual-{abs(hash(title)) % 100000}"
    existing = db.query(InventoryItem).filter(InventoryItem.sku == key).first()
    if existing:
        return {"error": "An item with that SKU already exists"}
    db.add(InventoryItem(sku=key, title=title, quantity=quantity,
                         last_synced=datetime.datetime.utcnow()))
    db.commit()
    return {"ok": True, "sku": key}


@router.post("/set-qty")
def set_qty(sku: str, quantity: int, db: Session = Depends(get_db)):
    row = db.query(InventoryItem).filter(InventoryItem.sku == sku).first()
    if not row:
        return {"error": "not found"}
    row.quantity = max(0, quantity)
    db.commit()
    return {"ok": True}


@router.delete("/item")
def delete_item(sku: str, db: Session = Depends(get_db)):
    db.query(InventoryItem).filter(InventoryItem.sku == sku).delete()
    db.commit()
    return {"ok": True}


@router.post("/sync")
def sync_inventory(db: Session = Depends(get_db)):
    """Pulls all ACTIVE LISTINGS from eBay (read-only - nothing is ever
    written back). Uses the Trading API, which covers normally-listed items."""
    try:
        listings = ebay_client.fetch_active_listings()
    except Exception as e:
        return {"error": str(e)}

    updated = 0
    for it in listings:
        # key by SKU when present, otherwise by eBay item ID
        key = it["sku"] or f"item-{it['item_id']}"
        row = db.query(InventoryItem).filter(InventoryItem.sku == key).first()
        if not row:
            row = InventoryItem(sku=key)
            db.add(row)
        row.ebay_item_id = it["item_id"]
        row.title = it["title"] or row.title
        row.quantity = it["quantity"]
        row.price = it["price"]
        if it["image_url"]:
            row.image_url = it["image_url"]
        row.last_synced = datetime.datetime.utcnow()
        updated += 1
    db.commit()
    return {"synced": updated}
