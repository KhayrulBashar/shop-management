from app.schemas.auth import (
    AuthStatusResponse,
    UserLogin,
    UserRegister,
    UserResponse,
)
from app.schemas.customer import (
    CustomerCreate,
    CustomerResponse,
    CustomerUpdate,
)
from app.schemas.dashboard import DashboardStats
from app.schemas.inventory import (
    StockMovementCreate,
    StockMovementResponse,
)
from app.schemas.order import (
    OrderCreate,
    OrderItemCreate,
    OrderItemResponse,
    OrderResponse,
    OrderStatusUpdate,
)
from app.schemas.product import (
    ProductCreate,
    ProductResponse,
    ProductUpdate,
)

__all__ = [
    "UserRegister",
    "UserLogin",
    "UserResponse",
    "AuthStatusResponse",
    "ProductCreate",
    "ProductUpdate",
    "ProductResponse",
    "CustomerCreate",
    "CustomerUpdate",
    "CustomerResponse",
    "OrderItemCreate",
    "OrderItemResponse",
    "OrderCreate",
    "OrderStatusUpdate",
    "OrderResponse",
    "StockMovementCreate",
    "StockMovementResponse",
    "DashboardStats",
]