from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field


class OrderItemCreate(BaseModel):
    product_id: int
    quantity: int = Field(..., ge=1, description="Quantity must be at least 1")


class OrderItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    product_name: str
    product_sku: str
    quantity: int
    unit_price: Decimal
    line_total: Decimal


class OrderCreate(BaseModel):
    customer_id: int
    order_status: str = Field(default="Pending", pattern="^(Pending|Processing|Shipped|Delivered|Cancelled)$")
    payment_status: str = Field(default="Unpaid", pattern="^(Unpaid|Partial|Paid)$")
    notes: str | None = None
    items: list[OrderItemCreate] = Field(..., min_length=1, description="Order must contain at least one item")


class OrderStatusUpdate(BaseModel):
    order_status: str | None = Field(None, pattern="^(Pending|Processing|Shipped|Delivered|Cancelled)$")
    payment_status: str | None = Field(None, pattern="^(Unpaid|Partial|Paid)$")
    notes: str | None = None


class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_number: str
    customer_id: int
    customer_name: str
    customer_phone: str
    customer_email: str | None = None
    customer_address: str | None = None
    total_amount: Decimal
    order_status: str
    payment_status: str
    notes: str | None = None
    created_at: datetime
    items: list[OrderItemResponse] = []