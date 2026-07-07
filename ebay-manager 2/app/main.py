import os
from fastapi import FastAPI, Request, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from apscheduler.schedulers.background import BackgroundScheduler

from .database import init_db
from .routers import (
    auth, inventory, orders, settings as settings_router,
    messages, compliance, analytics,
)
from . import messaging, security

init_db()

app = FastAPI(title="eBay Seller Manager")


@app.middleware("http")
async def password_gate(request: Request, call_next):
    path = request.url.path
    if security.is_exempt(path) or security.is_authed(request):
        return await call_next(request)
    return RedirectResponse("/login")


@app.get("/login")
def login_form():
    return security.login_page()


@app.post("/login")
def login_submit(password: str = Form("")):
    return security.handle_login(password)


app.include_router(auth.router)
app.include_router(inventory.router)
app.include_router(orders.router)
app.include_router(settings_router.router)
app.include_router(messages.router)
app.include_router(compliance.router)
app.include_router(analytics.router)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def root():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


scheduler = BackgroundScheduler()
scheduler.add_job(messaging.check_and_autoreply, "interval", minutes=5)
scheduler.start()
