# orders/serializers.py
from rest_framework import serializers
from .models import Order, Trade

class OrderSerializer(serializers.ModelSerializer):
    traded_quantity = serializers.IntegerField(read_only=True)
    average_traded_price = serializers.FloatField(read_only=True)

    class Meta:
        model = Order
        fields = [
            "id", "side", "price", "quantity", "remaining_qty", "alive",
            "created_at", "updated_at",
            "traded_quantity", "average_traded_price"
        ]
        read_only_fields = [
            "id", "remaining_qty", "alive",
            "created_at", "updated_at",
            "traded_quantity", "average_traded_price"
        ]



class TradeSerializer(serializers.ModelSerializer):
    bid_order_id = serializers.UUIDField(source="bid_order.id", read_only=True)
    ask_order_id = serializers.UUIDField(source="ask_order.id", read_only=True)

    class Meta:
        model = Trade
        fields = "__all__"
