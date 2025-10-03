# engine/orderbook.py
import heapq
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, ROUND_DOWN, getcontext
from typing import Deque, Dict, List, Optional

# set decimal precision
getcontext().prec = 12


@dataclass
class Order:
    id: uuid.UUID
    side: int           # 1 buy, -1 sell
    price: Decimal
    orig_qty: int
    remaining: int
    ts: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Trade:
    id: uuid.UUID
    price: Decimal
    qty: int
    bid_order_id: uuid.UUID
    ask_order_id: uuid.UUID
    ts: datetime = field(default_factory=datetime.utcnow)


class OrderBook:
    """
    Single-instrument limit order book.
    buy_levels: price -> deque[Order]
    sell_levels: price -> deque[Order]
    buy_heap: max via negative prices
    sell_heap: min heap
    orders_by_id: uuid -> Order (for cancel/modify)
    buy_volume/sell_volume: aggregated remaining per price
    """

    def __init__(self):
        self.buy_levels: Dict[Decimal, Deque[Order]] = {}
        self.sell_levels: Dict[Decimal, Deque[Order]] = {}
        self.buy_heap: List[Decimal] = []   # store -price to get max behavior
        self.sell_heap: List[Decimal] = []  # store price to get min
        self.buy_price_set = set()
        self.sell_price_set = set()
        self.orders_by_id: Dict[uuid.UUID, Order] = {}
        self.buy_volume: Dict[Decimal, int] = {}
        self.sell_volume: Dict[Decimal, int] = {}

    @staticmethod
    def _norm_price(p: Decimal) -> Decimal:
        return p.quantize(Decimal("0.01"), rounding=ROUND_DOWN)

    # -------- helpers for price heaps --------
    def _ensure_buy_price(self, price: Decimal):
        if price not in self.buy_price_set:
            heapq.heappush(self.buy_heap, -price)
            self.buy_price_set.add(price)

    def _ensure_sell_price(self, price: Decimal):
        if price not in self.sell_price_set:
            heapq.heappush(self.sell_heap, price)
            self.sell_price_set.add(price)

    def _clean_buy_heap(self):
        while self.buy_heap:
            price = -self.buy_heap[0]
            dq = self.buy_levels.get(price)
            if dq and len(dq) > 0:
                return
            # stale or empty level -> pop and cleanup
            heapq.heappop(self.buy_heap)
            self.buy_price_set.discard(price)
            self.buy_levels.pop(price, None)
            self.buy_volume.pop(price, None)

    def _clean_sell_heap(self):
        while self.sell_heap:
            price = self.sell_heap[0]
            dq = self.sell_levels.get(price)
            if dq and len(dq) > 0:
                return
            heapq.heappop(self.sell_heap)
            self.sell_price_set.discard(price)
            self.sell_levels.pop(price, None)
            self.sell_volume.pop(price, None)

    def _best_buy_price(self) -> Optional[Decimal]:
        self._clean_buy_heap()
        if not self.buy_heap:
            return None
        return -self.buy_heap[0]

    def _best_sell_price(self) -> Optional[Decimal]:
        self._clean_sell_heap()
        if not self.sell_heap:
            return None
        return self.sell_heap[0]

    # -------- core: add to book (no matching) --------
    def _add_to_book(self, order: Order):
        mapping = self.buy_levels if order.side == 1 else self.sell_levels
        volume_map = self.buy_volume if order.side == 1 else self.sell_volume
        price_set_fn = self._ensure_buy_price if order.side == 1 else self._ensure_sell_price

        if order.price not in mapping:
            mapping[order.price] = deque()
            price_set_fn(order.price)
            volume_map[order.price] = 0
        mapping[order.price].append(order)
        volume_map[order.price] += order.remaining
        self.orders_by_id[order.id] = order

    # -------- cancel order --------
    def cancel(self, order_id: uuid.UUID) -> bool:
        o = self.orders_by_id.get(order_id)
        if not o:
            return False
        mapping = self.buy_levels if o.side == 1 else self.sell_levels
        volume_map = self.buy_volume if o.side == 1 else self.sell_volume
        dq = mapping.get(o.price)
        if dq:
            try:
                dq.remove(o)   # O(n) in level; OK for assignment/demo
                volume_map[o.price] = max(0, volume_map.get(o.price, 0) - o.remaining)
            except ValueError:
                pass
            if not dq:
                mapping.pop(o.price, None)
        self.orders_by_id.pop(order_id, None)
        return True

    # -------- modify order: change price (simplest approach) --------
    def modify(self, order_id: uuid.UUID, new_price: Decimal) -> bool:
        o = self.orders_by_id.get(order_id)
        if not o:
            return False
        mapping = self.buy_levels if o.side == 1 else self.sell_levels
        volume_map = self.buy_volume if o.side == 1 else self.sell_volume
        dq = mapping.get(o.price)
        if dq:
            try:
                dq.remove(o)
                volume_map[o.price] = max(0, volume_map.get(o.price, 0) - o.remaining)
            except ValueError:
                pass
            if not dq:
                mapping.pop(o.price, None)
        # reinsert with new price
        o.price = self._norm_price(new_price)
        self._add_to_book(o)
        return True

    # -------- match incoming order (main algorithm) --------
    def match(self, incoming: Order) -> List[Trade]:
        trades: List[Trade] = []
        if incoming.side == 1:  # buy incoming -> match with sells (lowest ask)
            while incoming.remaining > 0:
                best_ask = self._best_sell_price()
                if best_ask is None or best_ask > incoming.price:
                    break
                sell_dq = self.sell_levels[best_ask]
                resting = sell_dq[0]
                traded_qty = min(incoming.remaining, resting.remaining)
                tr = Trade(
                    id=uuid.uuid4(),
                    price=resting.price,
                    qty=traded_qty,
                    bid_order_id=incoming.id,
                    ask_order_id=resting.id,
                )
                trades.append(tr)
                incoming.remaining -= traded_qty
                resting.remaining -= traded_qty
                self.sell_volume[best_ask] -= traded_qty
                if resting.remaining == 0:
                    sell_dq.popleft()
                    self.orders_by_id.pop(resting.id, None)
                if not sell_dq:
                    self.sell_levels.pop(best_ask, None)
        else:  # sell incoming -> match with best buys
            while incoming.remaining > 0:
                best_bid = self._best_buy_price()
                if best_bid is None or best_bid < incoming.price:
                    break
                buy_dq = self.buy_levels[best_bid]
                resting = buy_dq[0]
                traded_qty = min(incoming.remaining, resting.remaining)
                tr = Trade(
                    id=uuid.uuid4(),
                    price=resting.price,
                    qty=traded_qty,
                    bid_order_id=resting.id,
                    ask_order_id=incoming.id,
                )
                trades.append(tr)
                incoming.remaining -= traded_qty
                resting.remaining -= traded_qty
                self.buy_volume[best_bid] -= traded_qty
                if resting.remaining == 0:
                    buy_dq.popleft()
                    self.orders_by_id.pop(resting.id, None)
                if not buy_dq:
                    self.buy_levels.pop(best_bid, None)

        # leftover goes to book
        if incoming.remaining > 0:
            self._add_to_book(incoming)
        return trades

    # -------- snapshot top-N levels --------
    def snapshot(self, depth: int = 5):
        self._clean_buy_heap()
        self._clean_sell_heap()
        bids = []
        asks = []
        buy_prices_sorted = sorted(self.buy_price_set, reverse=True)[:depth]
        sell_prices_sorted = sorted(self.sell_price_set)[:depth]
        for p in buy_prices_sorted:
            total = self.buy_volume.get(p, 0)
            bids.append({"price": float(p), "quantity": total})
        for p in sell_prices_sorted:
            total = self.sell_volume.get(p, 0)
            asks.append({"price": float(p), "quantity": total})
        return {"bids": bids, "asks": asks}
