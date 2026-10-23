from datetime import datetime
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class CustomerBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=150)
    phone: str = Field(..., min_length=5, max_length=50)
    email: EmailStr | None = None
    address: str | None = None
    notes: str | None = None

    @field_validator("name", "phone")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Field cannot be empty")
        return v


class CustomerCreate(CustomerBase):
    pass


class CustomerUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=150)
    phone: str | None = Field(None, min_length=5, max_length=50)
    email: EmailStr | None = None
    address: str | None = None
    notes: str | None = None


class CustomerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    phone: str
    email: str | None
    address: str | None
    notes: str | None
    is_deleted: bool
    created_at: datetime
    updated_at: datetime
    orders_count: int = 0
