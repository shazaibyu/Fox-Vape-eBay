import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from apscheduler.schedulers.background import BackgroundScheduler

from .database import init_db
from .routers import auth, inventory, orders, settings as settings_router, messages, compliance
from . import messaging

init_db()

app = FastAPI(title="eBay Seller Manager")

app.include_router(auth.router)
app.include_router(inventory.router)
app.include_router(orders.router)
app.include_router(settings_router.router)
app.include_router(messages.router)
app.include_router(compliance.router)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def root():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


# Background poll for away-mode auto-replies every 5 minutes.
scheduler = BackgroundScheduler()
scheduler.add_job(messaging.check_and_autoreply, "interval", minutes=5)
scheduler.start()
