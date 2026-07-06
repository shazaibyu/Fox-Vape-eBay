"""
eBay requires every production app to have a working endpoint that can
receive "Marketplace Account Deletion / Closure" notifications - this is
just eBay confirming they can reach you if a buyer asks eBay to delete
their data, so you can delete it from your own database too.

Two things eBay does to this endpoint:
1. A GET request with a "challenge_code" - used once, during setup, to
   prove you control this URL. You must answer with a specific hashed value.
2. Real POST notifications later, whenever an actual account deletion
   happens - you just need to acknowledge with a 200 OK. This app deletes
   the matching buyer's stored messages/order buyer-name references.
"""
import hashlib
import os
from fastapi import APIRouter, Request
from sqlalchemy.orm import Session
from fastapi import Depends
from ..database import get_db
from ..models import MessageLog

router = APIRouter(prefix="/ebay", tags=["compliance"])

# Set this in Render's Environment Variables to whatever you type into
# eBay's "Verification token" box (any string, 32-80 chars, your choice).
VERIFICATION_TOKEN = os.environ.get("EBAY_VERIFICATION_TOKEN", "")

# The exact same URL you paste into eBay's "Marketplace account deletion
# notification endpoint" field - must match exactly, including https://.
ENDPOINT_URL = os.environ.get("EBAY_DELETION_ENDPOINT_URL", "")


@router.get("/marketplace-account-deletion")
def verify_challenge(challenge_code: str):
    """eBay calls this once, with ?challenge_code=..., to verify the endpoint."""
    to_hash = challenge_code + VERIFICATION_TOKEN + ENDPOINT_URL
    challenge_response = hashlib.sha256(to_hash.encode("utf-8")).hexdigest()
    return {"challengeResponse": challenge_response}


@router.post("/marketplace-account-deletion")
async def receive_deletion_notice(request: Request, db: Session = Depends(get_db)):
    """eBay calls this for real when a buyer's account/data must be deleted."""
    payload = await request.json()
    username = (
        payload.get("notification", {})
        .get("data", {})
        .get("username")
    )
    if username:
        db.query(MessageLog).filter(MessageLog.buyer_username == username).delete()
        db.commit()
    return {"ok": True}
