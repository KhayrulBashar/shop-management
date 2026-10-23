from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProductBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=200)
    sku: str = Field(..., min_length=2, max_length=100)
    category: str = Field(default="General", min_length=1, max_length=100)
    price: Decimal = Field(..., ge=Decimal("0.00"), decimal_places=2)
    stock_quantity: int = Field(default=0, ge=0)
    reorder_level: int = Field(default=5, ge=0)

    @field_validator("sku")
    @classmethod
    def sanitize_sku(cls, v: str) -> str:
        v = v.strip().upper()
        if not v:
            raise ValueError("SKU cannot be empty")
        return v

    @field_validator("name")
    @classmethod
    def sanitize_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name cannot be empty")
        return v


class ProductCreate(ProductBase):
    pass


class ProductUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=200)
    sku: str | None = Field(None, min_length=2, max_length=100)
    category: str | None = Field(None, min_length=1, max_length=100)
    price: Decimal | None = Field(None, ge=Decimal("0.00"), decimal_places=2)
    stock_quantity: int | None = Field(None, ge=0)
    reorder_level: int | None = Field(None, ge=0)

    @field_validator("sku")
    @classmethod
    def sanitize_sku(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip().upper()
            if not v:
                raise ValueError("SKU cannot be empty")
        return v


class ProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    sku: str
    category: str
    price: Decimal
    stock_quantity: int
    reorder_level: int
    is_deleted: bool
    created_at: datetime
    updated_at: datetime

    @property
    def is_low_stock(self) -> bool:
        return self.stock_quantity <= self.reorder_level