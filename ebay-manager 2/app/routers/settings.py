from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Settings, ShippingRate

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("")
def get_settings(db: Session = Depends(get_db)):
    s = db.query(Settings).first()
    return {
        "ebay_environment": s.ebay_environment,
        "ebay_fee_percent": s.ebay_fee_percent,
        "ebay_fee_fixed": s.ebay_fee_fixed,
        "age_verification_fee": s.age_verification_fee,
        "away_mode": s.away_mode,
        "away_message": s.away_message,
        "connected": bool(s.ebay_refresh_token),
    }


@router.post("")
def update_settings(ebay_fee_percent: float = None, ebay_fee_fixed: float = None,
                     age_verification_fee: float = None, away_mode: bool = None,
                     away_message: str = None, db: Session = Depends(get_db)):
    s = db.query(Settings).first()
    if ebay_fee_percent is not None:
        s.ebay_fee_percent = ebay_fee_percent
    if ebay_fee_fixed is not None:
        s.ebay_fee_fixed = ebay_fee_fixed
    if age_verification_fee is not None:
        s.age_verification_fee = age_verification_fee
    if away_mode is not None:
        s.away_mode = away_mode
    if away_message is not None:
        s.away_message = away_message
    db.commit()
    return {"ok": True}


@router.get("/shipping-rates")
def list_rates(db: Session = Depends(get_db)):
    rates = db.query(ShippingRate).all()
    return [{"id": r.id, "carrier": r.carrier, "service_name": r.service_name,
             "default_cost": r.default_cost} for r in rates]


@router.post("/shipping-rates")
def add_rate(carrier: str, service_name: str, default_cost: float, db: Session = Depends(get_db)):
    rate = ShippingRate(carrier=carrier, service_name=service_name, default_cost=default_cost)
    db.add(rate)
    db.commit()
    return {"ok": True, "id": rate.id}


@router.delete("/shipping-rates/{rate_id}")
def delete_rate(rate_id: int, db: Session = Depends(get_db)):
    db.query(ShippingRate).filter(ShippingRate.id == rate_id).delete()
    db.commit()
    return {"ok": True}
