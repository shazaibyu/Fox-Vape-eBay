"""
Optional password protection.

If the DASHBOARD_PASSWORD environment variable is set (in Render:
Environment -> Add Environment Variable -> DASHBOARD_PASSWORD), the whole
dashboard requires that password to view. If it's not set, no login is
required (same behaviour as before) - so you can't lock yourself out.

Paths that must stay open even with a password on:
- /ebay/*          eBay's compliance notifications must always get through
- /auth/callback   eBay's OAuth redirect
- /login           the login page itself
"""
import os
import hashlib
from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse

PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "")

EXEMPT_PREFIXES = ("/ebay/", "/auth/callback", "/login", "/favicon")


def _token():
    return hashlib.sha256(("ebay-manager::" + PASSWORD).encode()).hexdigest()


def is_authed(request: Request) -> bool:
    if not PASSWORD:
        return True
    return request.cookies.get("dash_session") == _token()


def is_exempt(path: str) -> bool:
    return any(path.startswith(p) for p in EXEMPT_PREFIXES)


LOGIN_PAGE = """<!DOCTYPE html>
<html><head><title>Login - eBay Seller Manager</title>
<script src="https://cdn.tailwindcss.com"></script></head>
<body class="bg-gray-100 min-h-screen flex items-center justify-center">
<form method="post" action="/login" class="bg-white p-8 rounded shadow max-w-sm w-full">
  <h1 class="text-xl font-bold mb-4">eBay Seller Manager</h1>
  <input type="password" name="password" placeholder="Password" autofocus
    class="w-full border rounded p-2 mb-3">
  <button class="w-full bg-blue-600 text-white rounded p-2">Log in</button>
  {error}
</form></body></html>"""


def login_page(error: bool = False):
    err_html = '<p class="text-red-600 text-sm mt-2">Wrong password, try again.</p>' if error else ""
    return HTMLResponse(LOGIN_PAGE.replace("{error}", err_html))


def handle_login(password: str):
    if PASSWORD and password == PASSWORD:
        resp = RedirectResponse("/", status_code=302)
        resp.set_cookie("dash_session", _token(), max_age=60 * 60 * 24 * 30, httponly=True)
        return resp
    return login_page(error=True)
