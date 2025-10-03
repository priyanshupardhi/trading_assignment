from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from typing import Any
import uuid
from decimal import Decimal
import asyncio

from .schemas import PlaceOrderEvent, CancelEvent, ModifyEvent
from .orderbook import Order, OrderBook
from .main import BOOK, PROCESS_LOCK, redis_client, ORDERS_CHANNEL

router = APIRouter()

@router.get("/health", tags=["internal"])
async def health() -> Any:
    return {"status": "ok"}

# Convenience HTTP endpoints for testing (Django should publish to Redis in prod)
@router.post("/place", response_model=dict, tags=["orders"])
async def http_place(evt: PlaceOrderEvent):
    """
    For quick testing only: publish the event to Redis 'orders' channel.
    In production your Django app should publish to Redis directly.
    """
    payload = evt.dict()
    # set order_id if not present
    if not payload.get("order_id"):
        payload["order_id"] = str(uuid.uuid4())
    if redis_client:
        await redis_client.publish(ORDERS_CHANNEL, JSONResponse(payload).body.decode())
    return {"published": True, "payload": payload}


@router.post("/cancel", tags=["orders"])
async def http_cancel(evt: CancelEvent):
    payload = evt.dict()
    if redis_client:
        await redis_client.publish(ORDERS_CHANNEL, JSONResponse(payload).body.decode())
    return {"published": True, "payload": payload}


@router.post("/modify", tags=["orders"])
async def http_modify(evt: ModifyEvent):
    payload = evt.dict()
    if redis_client:
        await redis_client.publish(ORDERS_CHANNEL, JSONResponse(payload).body.decode())
    return {"published": True, "payload": payload}
