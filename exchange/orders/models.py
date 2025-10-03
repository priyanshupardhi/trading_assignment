import uuid
from django.db import models
from decimal import Decimal

class Order(models.Model):
    SIDE_CHOICES = [
        (1, 'Buy'),
        (-1, 'Sell'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    side = models.IntegerField(choices=SIDE_CHOICES)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.IntegerField()
    remaining_qty = models.IntegerField(null=True, blank=True)  # Allow null temporarily
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    alive = models.BooleanField(default=True)
    
    def save(self, *args, **kwargs):
        # Auto-initialize remaining_qty if not set
        if self.remaining_qty is None:
            self.remaining_qty = self.quantity
        super().save(*args, **kwargs)
    
    def traded_quantity(self) -> int:
        return self.quantity - self.remaining_qty
    
    def average_traded_price(self) -> Decimal:
        """Calculate average price from all trades"""
        buy_trades = self.buy_trades.all()
        sell_trades = self.sell_trades.all()
        all_trades = list(buy_trades) + list(sell_trades)
        
        if not all_trades:
            return Decimal('0.0')
        
        total_value = sum(trade.price * trade.quantity for trade in all_trades)
        total_qty = sum(trade.quantity for trade in all_trades)
        
        return total_value / total_qty if total_qty > 0 else Decimal('0.0')
    
    def update_remaining_qty(self, traded_qty: int):
        """Update remaining quantity after a trade"""
        self.remaining_qty -= traded_qty
        if self.remaining_qty <= 0:
            self.remaining_qty = 0
            self.alive = False
        self.save()


class Trade(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.IntegerField()
    execution_time = models.DateTimeField(auto_now_add=True)
    bid_order = models.ForeignKey(
        Order, 
        on_delete=models.CASCADE, 
        related_name="buy_trades"
    )
    ask_order = models.ForeignKey(
        Order, 
        on_delete=models.CASCADE, 
        related_name="sell_trades"
    )
    
    def save(self, *args, **kwargs):
        """Automatically update order quantities when trade is created"""
        is_new = self._state.adding
        super().save(*args, **kwargs)
        
        if is_new:
            # Update both orders' remaining quantities
            self.bid_order.update_remaining_qty(self.quantity)
            self.ask_order.update_remaining_qty(self.quantity)