"""
Thin wrapper around the eBay REST APIs used by this app.

APIs used:
- OAuth2 (identity)         -> get/refresh access tokens
- Sell Inventory API        -> READ inventory only (we never write back)
- Sell Fulfillment API      -> READ orders
- Trading API (legacy XML)  -> read/send buyer messages (no REST equivalent
                                with the same functionality yet)

All calls use the *refresh token* obtained once via the OAuth consent flow
(see /auth routes) to mint short-lived access tokens.

Every network call has an explicit timeout - without this, a stalled
connection to eBay would hang forever instead of failing with a clear error.
"""
import requests
import datetime
from .database import SessionLocal
from .models import Settings

TIMEOUT = 20  # seconds - every call to eBay must finish or fail within this

PROD_BASE = "https://api.ebay.com"
SANDBOX_BASE = "https://api.sandbox.ebay.com"

PROD_AUTH = "https://auth.ebay.com/oauth2/authorize"
SANDBOX_AUTH = "https://auth.sandbox.ebay.com/oauth2/authorize"

PROD_TOKEN = "https://api.ebay.com/identity/v1/oauth2/token"
SANDBOX_TOKEN = "https://api.sandbox.ebay.com/identity/v1/oauth2/token"

SCOPES = [
    "https://api.ebay.com/oauth/api_scope/sell.inventory",
    "https://api.ebay.com/oauth/api_scope/sell.fulfillment",
    "https://api.ebay.com/oauth/api_scope/sell.marketing",
]

_token_cache = {"access_token": None, "expires_at": None}


def _settings():
    db = SessionLocal()
    try:
        return db.query(Settings).first()
    finally:
        db.close()


def _base_urls(s):
    if s.ebay_environment == "sandbox":
        return SANDBOX_BASE, SANDBOX_AUTH, SANDBOX_TOKEN
    return PROD_BASE, PROD_AUTH, PROD_TOKEN


def build_authorize_url():
    s = _settings()
    _, auth_url, _ = _base_urls(s)
    scope_str = "%20".join(SCOPES)
    return (
        f"{auth_url}?client_id={s.ebay_client_id}"
        f"&redirect_uri={s.ebay_redirect_uri}"
        f"&response_type=code&scope={scope_str}"
    )


def exchange_code_for_token(code: str):
    s = _settings()
    _, _, token_url = _base_urls(s)
    resp = requests.post(
        token_url,
        auth=(s.ebay_client_id, s.ebay_client_secret),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": s.ebay_redirect_uri,
        },
        timeout=TIMEOUT,
    )
    if not resp.ok:
        raise RuntimeError(f"eBay token exchange failed ({resp.status_code}): {resp.text}")
    data = resp.json()

    db = SessionLocal()
    try:
        settings_row = db.query(Settings).first()
        settings_row.ebay_refresh_token = data["refresh_token"]
        settings_row.ebay_refresh_token_expiry = datetime.datetime.utcnow() + datetime.timedelta(
            seconds=data.get("refresh_token_expires_in", 0)
        )
        db.commit()
    finally:
        db.close()
    return data


def get_access_token():
    now = datetime.datetime.utcnow()
    if _token_cache["access_token"] and _token_cache["expires_at"] > now:
        return _token_cache["access_token"]

    s = _settings()
    if not s.ebay_refresh_token:
        raise RuntimeError("Not connected to eBay yet - complete the OAuth setup first.")

    _, _, token_url = _base_urls(s)
    resp = requests.post(
        token_url,
        auth=(s.ebay_client_id, s.ebay_client_secret),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "refresh_token",
            "refresh_token": s.ebay_refresh_token,
            "scope": " ".join(SCOPES),
        },
        timeout=TIMEOUT,
    )
    if not resp.ok:
        raise RuntimeError(f"eBay token refresh failed ({resp.status_code}): {resp.text}")
    data = resp.json()
    _token_cache["access_token"] = data["access_token"]
    _token_cache["expires_at"] = now + datetime.timedelta(seconds=data["expires_in"] - 60)
    return _token_cache["access_token"]


def _headers():
    return {
        "Authorization": f"Bearer {get_access_token()}",
        "Content-Type": "application/json",
    }


def fetch_inventory(limit=100):
    s = _settings()
    base, _, _ = _base_urls(s)
    items = []
    offset = 0
    headers = _headers()
    while True:
        r = requests.get(
            f"{base}/sell/inventory/v1/inventory_item",
            headers=headers,
            params={"limit": limit, "offset": offset},
            timeout=TIMEOUT,
        )
        if not r.ok:
            raise RuntimeError(f"eBay inventory fetch failed ({r.status_code}): {r.text}")
        data = r.json()
        batch = data.get("inventoryItems", [])
        items.extend(batch)
        offset += limit
        if offset >= data.get("total", 0) or not batch:
            break
    return items


def fetch_orders(order_ids=None, creation_date_from=None):
    s = _settings()
    base, _, _ = _base_urls(s)
    params = {"limit": 50}
    filters = []
    if creation_date_from:
        filters.append(f"creationdate:[{creation_date_from}..]")
    if filters:
        params["filter"] = ",".join(filters)

    orders = []
    offset = 0
    headers = _headers()
    while True:
        params["offset"] = offset
        r = requests.get(
            f"{base}/sell/fulfillment/v1/order",
            headers=headers,
            params=params,
            timeout=TIMEOUT,
        )
        if not r.ok:
            raise RuntimeError(f"eBay order fetch failed ({r.status_code}): {r.text}")
        data = r.json()
        batch = data.get("orders", [])
        orders.extend(batch)
        offset += params["limit"]
        if offset >= data.get("total", 0) or not batch:
            break
    return orders


TRADING_ENDPOINT = "https://api.ebay.com/ws/api.dll"
TRADING_ENDPOINT_SANDBOX = "https://api.sandbox.ebay.com/ws/api.dll"


def _trading_headers(call_name):
    return {
        "X-EBAY-API-SITEID": "3",
        "X-EBAY-API-COMPATIBILITY-LEVEL": "1193",
        "X-EBAY-API-CALL-NAME": call_name,
        "Content-Type": "text/xml",
    }


def fetch_member_messages():
    s = _settings()
    endpoint = TRADING_ENDPOINT_SANDBOX if s.ebay_environment == "sandbox" else TRADING_ENDPOINT
    token = get_access_token()
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<GetMemberMessagesRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials>
    <eBayAuthToken>{token}</eBayAuthToken>
  </RequesterCredentials>
  <MailMessageType>All</MailMessageType>
  <MessageStatus>Unanswered</MessageStatus>
  <DetailLevel>ReturnHeaders</DetailLevel>
</GetMemberMessagesRequest>"""
    r = requests.post(endpoint, headers=_trading_headers("GetMemberMessages"), data=xml, timeout=TIMEOUT)
    if not r.ok:
        raise RuntimeError(f"eBay GetMemberMessages failed ({r.status_code}): {r.text}")
    return r.text


def send_reply(item_id: str, buyer_username: str, message_text: str):
    s = _settings()
    endpoint = TRADING_ENDPOINT_SANDBOX if s.ebay_environment == "sandbox" else TRADING_ENDPOINT
    token = get_access_token()
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<AddMemberMessageAAQToPartnerRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials>
    <eBayAuthToken>{token}</eBayAuthToken>
  </RequesterCredentials>
  <ItemID>{item_id}</ItemID>
  <MemberMessage>
    <Body>{message_text}</Body>
    <QuestionType>General</QuestionType>
    <RecipientID>{buyer_username}</RecipientID>
  </MemberMessage>
</AddMemberMessageAAQToPartnerRequest>"""
    r = requests.post(
        endpoint, headers=_trading_headers("AddMemberMessageAAQToPartner"), data=xml, timeout=TIMEOUT
    )
    if not r.ok:
        raise RuntimeError(f"eBay send message failed ({r.status_code}): {r.text}")
    return r.text
