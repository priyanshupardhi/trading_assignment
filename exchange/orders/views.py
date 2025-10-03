import json
import redis
from rest_framework import viewsets, status
from rest_framework.response import Response
from .models import Order, Trade
from .serializers import OrderSerializer, TradeSerializer

# Initialize Redis client
redis_client = redis.Redis(host='redis', port=6379, db=0, decode_responses=True)

class OrderViewSet(viewsets.ModelViewSet):
    queryset = Order.objects.all().order_by("-created_at")
    serializer_class = OrderSerializer
    
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = serializer.save()
        
        # Publish to Redis "orders" channel
        event = {
            "action": "place",
            "order_id": str(order.id),
            "side": order.side,
            "price": float(order.price),
            "quantity": order.quantity,
        }
        redis_client.publish("orders", json.dumps(event))
        
        return Response({"order_id": str(order.id)}, status=status.HTTP_201_CREATED)
    
    def update(self, request, *args, **kwargs):
        order = self.get_object()
        if not order.alive:
            return Response({"success": False, "error": "Order not alive"}, status=status.HTTP_400_BAD_REQUEST)
        
        new_price = request.data.get("price")
        if not new_price:
            return Response({"success": False, "error": "Price required"}, status=status.HTTP_400_BAD_REQUEST)
        
        # Publish modify to Redis
        event = {
            "action": "modify",
            "order_id": str(order.id),
            "price": float(new_price),
        }
        redis_client.publish("orders", json.dumps(event))
        
        # Update local database
        order.price = new_price
        order.save()
        
        return Response({"success": True})
    
    def destroy(self, request, *args, **kwargs):
        order = self.get_object()
        if not order.alive:
            return Response({"success": False, "error": "Order already cancelled"}, status=status.HTTP_400_BAD_REQUEST)
        
        # Publish cancel to Redis
        event = {
            "action": "cancel",
            "order_id": str(order.id),
        }
        redis_client.publish("orders", json.dumps(event))
        
        # Update local database
        order.alive = False
        order.remaining_qty = 0
        order.save()
        
        return Response({"success": True})
    
    def retrieve(self, request, *args, **kwargs):
        order = self.get_object()
        return Response({
            "order_id": str(order.id),
            "order_price": float(order.price),
            "order_quantity": order.quantity,
            "average_traded_price": float(order.average_traded_price()),
            "traded_quantity": order.traded_quantity(),
            "order_alive": order.alive,
        })
    
    def list(self, request, *args, **kwargs):
        orders = self.get_queryset()
        result = []
        for order in orders:
            result.append({
                "order_id": str(order.id),
                "order_price": float(order.price),
                "order_quantity": order.quantity,
                "average_traded_price": float(order.average_traded_price()),
                "traded_quantity": order.traded_quantity(),
                "order_alive": order.alive,
            })
        return Response(result)


class TradeViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Trade.objects.all().order_by("-execution_time")
    serializer_class = TradeSerializer
    
    def list(self, request, *args, **kwargs):
        trades = self.get_queryset()
        data = []
        for t in trades:
            data.append({
                "unique_id": str(t.id),
                "execution_timestamp": t.execution_time.isoformat(),
                "price": float(t.price),
                "quantity": t.quantity,
                "bid_order_id": str(t.bid_order.id),
                "ask_order_id": str(t.ask_order.id),
            })
        return Response(data)