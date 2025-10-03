import json
import redis
from decimal import Decimal
from django.conf import settings
from django.core.management.base import BaseCommand
from orders.models import Order, Trade


class Command(BaseCommand):
    help = 'Consume trades from Redis and save to database'

    def handle(self, *args, **options):
        redis_client = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB
        )
        pubsub = redis_client.pubsub()
        pubsub.subscribe('trades')
        
        self.stdout.write(self.style.SUCCESS('Trade consumer started...'))
        
        for message in pubsub.listen():
            if message['type'] == 'message':
                try:
                    data = json.loads(message['data'])
                    
                    # Handle trades
                    if 'trades' in data:
                        for trade_data in data['trades']:
                            bid_order = Order.objects.get(id=trade_data['bid_order_id'])
                            ask_order = Order.objects.get(id=trade_data['ask_order_id'])
                            
                            Trade.objects.create(
                                id=trade_data['unique_id'],
                                price=Decimal(str(trade_data['price'])),
                                quantity=trade_data['quantity'],
                                bid_order=bid_order,
                                ask_order=ask_order,
                            )
                            self.stdout.write(
                                self.style.SUCCESS(f"Trade created: {trade_data['unique_id']}")
                            )
                    
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(f"Error processing trade: {e}")
                    )