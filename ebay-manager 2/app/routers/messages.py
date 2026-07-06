from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import MessageLog
from .. import messaging

router = APIRouter(prefix="/api/messages", tags=["messages"])


@router.get("/log")
def get_log(db: Session = Depends(get_db)):
    logs = db.query(MessageLog).order_by(MessageLog.created_at.desc()).limit(200).all()
    return [
        {
            "buyer_username": m.buyer_username,
            "message_text": m.message_text,
            "direction": m.direction,
            "auto_generated": m.auto_generated,
            "created_at": m.created_at.isoformat(),
        }
        for m in logs
    ]


@router.post("/check-now")
def check_now():
    """Manually trigger a check-and-autoreply pass instead of waiting for
    the scheduled background poll."""
    return messaging.check_and_autoreply()
