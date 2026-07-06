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


@router.post("/sync")
def sync_inventory(db: Session = Depends(get_db)):
    """Pulls current stock levels FROM eBay only. Nothing is ever written
    back to eBay from this endpoint."""
    remote_items = ebay_client.fetch_inventory()
    updated = 0
    for it in remote_items:
        sku = it.get("sku")
        if not sku:
            continue
        product = it.get("product", {})
        qty = (it.get("availability", {})
                 .get("shipToLocationAvailability", {})
                 .get("quantity", 0))
        price = None
        # price often lives on the offer, not the inventory item - left as
        # 0 here; can be enriched by also calling the Offers API per SKU.
        row = db.query(InventoryItem).filter(InventoryItem.sku == sku).first()
        if not row:
            row = InventoryItem(sku=sku)
            db.add(row)
        row.title = (product.get("title") or row.title or "")
        row.quantity = qty
        if product.get("imageUrls"):
            row.image_url = product["imageUrls"][0]
        row.last_synced = datetime.datetime.utcnow()
        updated += 1
    db.commit()
    return {"synced": updated}
