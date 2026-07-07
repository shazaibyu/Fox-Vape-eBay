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
    "https://api.ebay.com/oauth/api_scope/sell.finances",
]

FINANCE_BASE = "https://apiz.ebay.com"          # Finances API uses apiz, not api
FINANCE_BASE_SANDBOX = "https://apiz.sandbox.ebay.com"

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
            # no scope param: eBay grants whatever was originally consented,
            # so tokens created before the finances scope was added keep working
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


def fetch_active_listings():
    """Fetch ALL active listings via the Trading API (GetMyeBaySelling).
    This works for normally-listed items - unlike the Inventory API, which
    only returns items created through the Inventory API itself (which is
    why inventory sync previously came back empty)."""
    import xml.etree.ElementTree as ET
    s = _settings()
    endpoint = TRADING_ENDPOINT_SANDBOX if s.ebay_environment == "sandbox" else TRADING_ENDPOINT
    token = get_access_token()
    ns = {"e": "urn:ebay:apis:eBLBaseComponents"}

    listings = []
    page = 1
    while True:
        xml = f"""<?xml version="1.0" encoding="utf-8"?>
<GetMyeBaySellingRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials><eBayAuthToken>{token}</eBayAuthToken></RequesterCredentials>
  <ActiveList>
    <Include>true</Include>
    <Pagination>
      <EntriesPerPage>200</EntriesPerPage>
      <PageNumber>{page}</PageNumber>
    </Pagination>
  </ActiveList>
  <DetailLevel>ReturnAll</DetailLevel>
</GetMyeBaySellingRequest>"""
        r = requests.post(endpoint, headers=_trading_headers("GetMyeBaySelling"), data=xml, timeout=30)
        if not r.ok:
            raise RuntimeError(f"eBay GetMyeBaySelling failed ({r.status_code}): {r.text[:300]}")
        root = ET.fromstring(r.text)

        ack = root.find("e:Ack", ns)
        if ack is not None and ack.text not in ("Success", "Warning"):
            err = root.find(".//e:Errors/e:LongMessage", ns)
            raise RuntimeError(f"eBay listing fetch error: {err.text if err is not None else r.text[:300]}")

        items = root.findall(".//e:ActiveList/e:ItemArray/e:Item", ns)
        for it in items:
            def g(path):
                el = it.find(path, ns)
                return el.text if el is not None else None
            qty = g("e:QuantityAvailable") or g("e:Quantity") or "0"
            listings.append({
                "item_id": g("e:ItemID"),
                "title": g("e:Title"),
                "sku": g("e:SKU"),
                "quantity": int(qty),
                "price": float(g("e:SellingStatus/e:CurrentPrice") or 0),
                "image_url": g("e:PictureDetails/e:GalleryURL"),
            })

        total_pages_el = root.find(".//e:ActiveList/e:PaginationResult/e:TotalNumberOfPages", ns)
        total_pages = int(total_pages_el.text) if total_pages_el is not None else 1
        if page >= total_pages or not items:
            break
        page += 1
    return listings


def fetch_order_fees():
    """Fetch real per-order fees via the Finances API. Returns a dict of
    orderId -> total fee amount. Requires the sell.finances permission -
    if the current eBay connection was made before that scope was added,
    this raises a clear error telling the user to reconnect."""
    s = _settings()
    base = FINANCE_BASE_SANDBOX if s.ebay_environment == "sandbox" else FINANCE_BASE
    token = get_access_token()
    headers = {"Authorization": f"Bearer {token}"}

    fees = {}
    offset = 0
    limit = 200
    while True:
        r = requests.get(
            f"{base}/sell/finances/v1/transaction",
            headers=headers,
            params={"filter": "transactionType:{SALE}", "limit": limit, "offset": offset},
            timeout=25,
        )
        if r.status_code in (401, 403):
            raise RuntimeError(
                "eBay hasn't granted fee access to this connection yet. "
                "Go to Settings and click 'Connect to eBay' once more to approve "
                "the new permission, then try again."
            )
        if not r.ok:
            raise RuntimeError(f"eBay fee fetch failed ({r.status_code}): {r.text[:300]}")
        data = r.json()
        txns = data.get("transactions", [])
        for t in txns:
            oid = t.get("orderId")
            fee = float(t.get("totalFeeAmount", {}).get("value", 0) or 0)
            if oid:
                fees[oid] = fees.get(oid, 0.0) + fee
        total = data.get("total", 0)
        offset += limit
        if offset >= total or not txns:
            break
    return fees


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
