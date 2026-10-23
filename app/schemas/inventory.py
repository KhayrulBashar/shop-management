from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class StockMovementCreate(BaseModel):
    product_id: int
    movement_type: str = Field(..., pattern="^(IN|OUT|ADJUSTMENT)$")
    quantity: int = Field(..., ge=1, description="Quantity must be greater than or equal to 1")
    reason: str | None = Field(None, max_length=500)


class StockMovementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    product_name: str
    product_sku: str
    movement_type: str
    quantity: int
    previous_stock: int
    new_stock: int
    reason: str | None = None
    user_name: str | None = None
    created_at: datetime
