from rest_framework.routers import DefaultRouter
from .views import OrderViewSet, TradeViewSet

router = DefaultRouter()
router.register(r'order/v1', OrderViewSet, basename='orders')
router.register(r'trade/v1', TradeViewSet, basename='trades')

urlpatterns = router.urls
