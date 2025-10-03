# engine/schemas.py
import uuid
from pydantic import BaseModel, condecimal, conint
from typing import Optional

Price = condecimal(gt=0, decimal_places=2)
Qty = conint(gt=0)


class PlaceOrderEvent(BaseModel):
    action: str  # "place", "cancel", "modify"
    order_id: Optional[uuid.UUID] = None
    side: Optional[int] = None
    price: Optional[Price] = None
    quantity: Optional[Qty] = None


class CancelEvent(BaseModel):
    action: str
    order_id: uuid.UUID


class ModifyEvent(BaseModel):
    action: str
    order_id: uuid.UUID
    price: Price
