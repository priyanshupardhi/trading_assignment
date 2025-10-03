import asyncio
import json
import os
import uuid
from decimal import Decimal
from typing import List

import redis.asyncio as aioredis
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .orderbook import Order, OrderBook
from .schemas import PlaceOrderEvent

import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("matching_engine")

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
ORDERS_CHANNEL = "orders"
TRADES_CHANNEL = "trades"

app = FastAPI(title="Matching Engine")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

BOOK = OrderBook()
PROCESS_LOCK = asyncio.Lock()

# Redis client
redis_client: aioredis.Redis | None = None
pubsub: aioredis.client.PubSub | None = None

# WebSocket clients
trade_clients: List[WebSocket] = []
book_clients: List[WebSocket] = []

# Background task handles
_sub_task = None
_snapshot_task = None


# WebSocket helper functions
async def broadcast_to_clients(clients: List[WebSocket], payload: dict):
    """Broadcast message to all connected clients"""
    dead = []
    for ws in list(clients):
        try:
            await ws.send_json(payload)
        except Exception as e:
            logger.error(f"Error broadcasting to client: {e}")
            dead.append(ws)
    
    # Remove dead connections
    for ws in dead:
        try:
            clients.remove(ws)
        except ValueError:
            pass


async def broadcast_trades(trades_payload):
    """Broadcast trades to all trade WebSocket clients"""
    payload = {"type": "trade", "data": trades_payload}
    await broadcast_to_clients(trade_clients, payload)
    logger.info(f"📢 Broadcasted {len(trades_payload)} trades to {len(trade_clients)} clients")


async def broadcast_snapshot(snapshot_payload):
    """Broadcast order book snapshot to all book WebSocket clients"""
    payload = {"type": "snapshot", "data": snapshot_payload}
    await broadcast_to_clients(book_clients, payload)


async def _process_redis_message(raw: bytes | str):
    """Process Redis messages for order actions"""
    try:
        if isinstance(raw, bytes):
            raw = raw.decode()
        msg = json.loads(raw)
        logger.info(f"📥 Received message from Redis: {msg}")
    except Exception as e:
        logger.error(f"❌ Failed to parse message: {e}")
        return

    action = msg.get("action")
    
    if action == "place":
        oid = uuid.UUID(msg["order_id"]) if "order_id" in msg and msg["order_id"] else uuid.uuid4()
        side = int(msg["side"])
        price = Decimal(str(msg["price"]))
        qty = int(msg["quantity"])
        price = OrderBook._norm_price(price)
        
        incoming = Order(id=oid, side=side, price=price, orig_qty=qty, remaining=qty)
        
        async with PROCESS_LOCK:
            trades = BOOK.match(incoming)
            
            if trades:
                payloads = []
                for t in trades:
                    payload = {
                        "unique_id": str(t.id),
                        "execution_timestamp": t.ts.isoformat(),
                        "price": float(t.price),
                        "quantity": t.qty,
                        "bid_order_id": str(t.bid_order_id),
                        "ask_order_id": str(t.ask_order_id),
                    }
                    payloads.append(payload)
                
                # Publish to Redis
                if redis_client:
                    await redis_client.publish(TRADES_CHANNEL, json.dumps({"trades": payloads}))
                
                # Broadcast to WebSocket clients
                await broadcast_trades(payloads)
    
    elif action == "cancel":
        oid = uuid.UUID(msg["order_id"])
        async with PROCESS_LOCK:
            ok = BOOK.cancel(oid)
            if redis_client:
                await redis_client.publish(
                    TRADES_CHANNEL, 
                    json.dumps({"cancel_ack": {"order_id": str(oid), "success": ok}})
                )
    
    elif action == "modify":
        oid = uuid.UUID(msg["order_id"])
        new_price = OrderBook._norm_price(Decimal(str(msg["price"])))
        async with PROCESS_LOCK:
            ok = BOOK.modify(oid, new_price)
            if redis_client:
                await redis_client.publish(
                    TRADES_CHANNEL,
                    json.dumps({"modify_ack": {"order_id": str(oid), "success": ok}})
                )
    
    # Broadcast updated snapshot
    try:
        snap = BOOK.snapshot(depth=5)
        await broadcast_snapshot(snap)
    except Exception as e:
        logger.error(f"Error broadcasting snapshot: {e}")


async def _redis_subscriber_loop():
    """Subscribe to Redis orders channel and process messages"""
    global pubsub
    try:
        pubsub = redis_client.pubsub(ignore_subscribe_messages=True)
        await pubsub.subscribe(ORDERS_CHANNEL)
        logger.info(f"✅ Subscribed to Redis channel: {ORDERS_CHANNEL}")
        
        async for message in pubsub.listen():
            data = message.get("data")
            if data:
                asyncio.create_task(_process_redis_message(data))
    except Exception as e:
        logger.error(f"❌ Redis subscriber error: {e}")


async def _snapshot_loop():
    """Periodically broadcast order book snapshots"""
    while True:
        try:
            await asyncio.sleep(1.0)
            snap = BOOK.snapshot(depth=5)
            await broadcast_snapshot(snap)
        except Exception as e:
            logger.error(f"Error in snapshot loop: {e}")


@app.on_event("startup")
async def startup():
    global redis_client, _sub_task, _snapshot_task
    
    redis_client = aioredis.from_url(REDIS_URL)
    logger.info(f"✅ Connected to Redis: {REDIS_URL}")
    
    # Start background tasks
    _sub_task = asyncio.create_task(_redis_subscriber_loop())
    _snapshot_task = asyncio.create_task(_snapshot_loop())
    
    logger.info("✅ Matching engine started")


@app.on_event("shutdown")
async def shutdown():
    global pubsub, redis_client, _sub_task, _snapshot_task
    
    if pubsub:
        try:
            await pubsub.unsubscribe(ORDERS_CHANNEL)
            await pubsub.close()
        except Exception as e:
            logger.error(f"Error closing pubsub: {e}")
    
    if redis_client:
        await redis_client.close()
    
    if _sub_task:
        _sub_task.cancel()
    
    if _snapshot_task:
        _snapshot_task.cancel()
    
    logger.info("✅ Matching engine shutdown complete")


# Health check endpoint
@app.get("/")
async def root():
    return {
        "service": "Matching Engine",
        "status": "running",
        "websockets": {
            "trades": "/ws/trades",
            "orderbook": "/ws/book"
        },
        "connected_clients": {
            "trades": len(trade_clients),
            "orderbook": len(book_clients)
        }
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}


# WebSocket endpoint for trades
@app.websocket("/ws/trades")
async def ws_trades(websocket: WebSocket):
    await websocket.accept()
    trade_clients.append(websocket)
    logger.info(f"📡 Client connected to /ws/trades (total: {len(trade_clients)})")
    
    try:
        # Send initial connection message
        await websocket.send_json({
            "type": "connection",
            "message": "Connected to trades stream"
        })
        
        # Keep connection alive
        while True:
            data = await websocket.receive_text()
            # Echo back for ping/pong
            await websocket.send_json({"type": "pong", "data": data})
            
    except WebSocketDisconnect:
        logger.info("Client disconnected from /ws/trades")
    except Exception as e:
        logger.error(f"⚠️ WebSocket error in /ws/trades: {e}")
    finally:
        if websocket in trade_clients:
            trade_clients.remove(websocket)
        logger.info(f"❌ Client removed from /ws/trades (remaining: {len(trade_clients)})")


# WebSocket endpoint for order book
@app.websocket("/ws/book")
async def ws_book(websocket: WebSocket):
    await websocket.accept()
    book_clients.append(websocket)
    logger.info(f"📡 Client connected to /ws/book (total: {len(book_clients)})")
    
    try:
        # Send initial connection message
        await websocket.send_json({
            "type": "connection",
            "message": "Connected to order book stream"
        })
        
        # Send current snapshot immediately
        snap = BOOK.snapshot(depth=5)
        await websocket.send_json({"type": "snapshot", "data": snap})
        
        # Keep connection alive
        while True:
            data = await websocket.receive_text()
            # Echo back for ping/pong
            await websocket.send_json({"type": "pong", "data": data})
            
    except WebSocketDisconnect:
        logger.info("Client disconnected from /ws/book")
    except Exception as e:
        logger.error(f"⚠️ WebSocket error in /ws/book: {e}")
    finally:
        if websocket in book_clients:
            book_clients.remove(websocket)
        logger.info(f"❌ Client removed from /ws/book (remaining: {len(book_clients)})")