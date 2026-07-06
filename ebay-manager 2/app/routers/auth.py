from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Settings
from .. import ebay_client

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/status")
def status(db: Session = Depends(get_db)):
    s = db.query(Settings).first()
    return {
        "connected": bool(s.ebay_refresh_token),
        "environment": s.ebay_environment,
        "has_client_id": bool(s.ebay_client_id),
    }


@router.post("/save-keys")
def save_keys(client_id: str, client_secret: str, redirect_uri: str, environment: str = "production",
              db: Session = Depends(get_db)):
    s = db.query(Settings).first()
    s.ebay_client_id = client_id
    s.ebay_client_secret = client_secret
    s.ebay_redirect_uri = redirect_uri
    s.ebay_environment = environment
    db.commit()
    return {"ok": True}


@router.get("/connect")
def connect():
    """Send the user to eBay's consent screen."""
    url = ebay_client.build_authorize_url()
    return RedirectResponse(url)


@router.get("/callback")
def callback(code: str):
    """eBay redirects here with ?code=... after the seller approves access."""
    ebay_client.exchange_code_for_token(code)
    return RedirectResponse("/?connected=1")
