"""
Away-mode auto-reply.

How it actually works:
- eBay's own "Automatic Away Messages" (Seller Hub > Messages > Settings)
  is a native feature you can toggle directly on eBay - it needs no API
  and is the most reliable option for simple "I'm away" auto-replies.
- This module adds a SECOND layer on top: it polls your buyer messages via
  the Trading API and sends a custom auto-reply through THIS app when
  away_mode is on here, logging every message sent so you have a record.
  Useful if you want smarter/custom replies than eBay's native box allows.

Note: eBay's legacy Trading API messaging calls can have stricter access
requirements on some accounts. If GetMemberMessages/AddMemberMessageAAQToPartner
throw permission errors for your account, turn on eBay's native Away
Message feature in Seller Hub as the reliable fallback - the README covers
exactly where that setting lives.
"""
import xml.etree.ElementTree as ET
from .database import SessionLocal
from .models import Settings, MessageLog
from . import ebay_client

NS = {"e": "urn:ebay:apis:eBLBaseComponents"}


def check_and_autoreply():
    db = SessionLocal()
    try:
        settings = db.query(Settings).first()
        if not settings.away_mode or not settings.ebay_refresh_token:
            return {"skipped": True}

        raw_xml = ebay_client.fetch_member_messages()
        root = ET.fromstring(raw_xml)

        replied = 0
        for msg in root.findall(".//e:MemberMessage", NS):
            item_id_el = msg.find(".//e:ItemID", NS)
            sender_el = msg.find(".//e:SenderID", NS)
            text_el = msg.find(".//e:Body", NS)

            item_id = item_id_el.text if item_id_el is not None else None
            sender = sender_el.text if sender_el is not None else None
            body = text_el.text if text_el is not None else ""

            if not sender or not item_id:
                continue

            already_replied = (
                db.query(MessageLog)
                .filter(MessageLog.buyer_username == sender)
                .filter(MessageLog.auto_generated == True)  # noqa: E712
                .first()
            )
            if already_replied:
                continue

            db.add(MessageLog(buyer_username=sender, message_text=body, direction="in"))
            ebay_client.send_reply(item_id, sender, settings.away_message)
            db.add(MessageLog(
                buyer_username=sender, message_text=settings.away_message,
                direction="out", auto_generated=True,
            ))
            replied += 1

        db.commit()
        return {"replied": replied}
    finally:
        db.close()
