from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, Text
)
from sqlalchemy.orm import declarative_base
import datetime

Base = declarative_base()


class Settings(Base):
    """Single-row table holding all app + eBay config."""
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, default=1)

    ebay_client_id = Column(String, default="")
    ebay_client_secret = Column(String, default="")
    ebay_redirect_uri = Column(String, default="")
    ebay_environment = Column(String, default="production")  # or sandbox
    ebay_refresh_token = Column(Text, default="")
    ebay_refresh_token_expiry = Column(DateTime, nullable=True)

    # Fee assumptions used by the profit calculator when eBay doesn't
    # return an exact fee on the order itself.
    ebay_fee_percent = Column(Float, default=12.8)   # % of total sale price
    ebay_fee_fixed = Column(Float, default=0.30)     # fixed per-order fee

    age_verification_fee = Column(Float, default=0.54)

    away_mode = Column(Boolean, default=False)
    low_stock_threshold = Column(Integer, default=3)
    away_message = Column(Text, default=(
        "Thanks for your message! I'm away right now and will reply as soon "
        "as I'm back. Your order is still being processed as normal."
    ))
    last_message_check = Column(DateTime, nullable=True)


class InventoryItem(Base):
    __tablename__ = "inventory_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sku = Column(String, unique=True, index=True)
    ebay_item_id = Column(String, nullable=True)
    title = Column(String)
    quantity = Column(Integer, default=0)
    price = Column(Float, default=0.0)
    image_url = Column(String, nullable=True)
    last_synced = Column(DateTime, default=datetime.datetime.utcnow)


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ebay_order_id = Column(String, unique=True, index=True)
    buyer_username = Column(String, nullable=True)
    item_title = Column(String, nullable=True)
    sku = Column(String, nullable=True)
    quantity = Column(Integer, default=1)

    sale_price = Column(Float, default=0.0)        # total buyer paid for item(s)
    shipping_charged = Column(Float, default=0.0)  # postage buyer paid you

    order_date = Column(DateTime, nullable=True)
    status = Column(String, nullable=True)

    tracking_number = Column(String, nullable=True)
    carrier = Column(String, nullable=True)

    shipping_cost = Column(Float, default=0.0)
    shipping_cost_is_estimated = Column(Boolean, default=True)

    item_cost = Column(Float, default=0.0)          # what YOU paid for the item - editable
    ebay_fee = Column(Float, default=0.0)
    ebay_fee_is_estimated = Column(Boolean, default=True)
    age_verification_fee = Column(Float, default=0.54)

    refunded = Column(Boolean, default=False)

    profit = Column(Float, default=0.0)

    raw_json = Column(Text, nullable=True)          # full eBay payload for reference


class ShippingRate(Base):
    """User-maintained fallback rates, used when the real label cost
    can't be pulled automatically for a given tracking number."""
    __tablename__ = "shipping_rates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    carrier = Column(String)
    service_name = Column(String)
    default_cost = Column(Float, default=0.0)


class MessageLog(Base):
    __tablename__ = "message_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ebay_order_id = Column(String, nullable=True)
    buyer_username = Column(String, nullable=True)
    message_text = Column(Text)
    direction = Column(String)       # "in" or "out"
    auto_generated = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
