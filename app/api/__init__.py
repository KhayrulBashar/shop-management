from fastapi import APIRouter

from app.api.auth import router as auth_router
from app.api.customers import router as customers_router
from app.api.dashboard import router as dashboard_router
from app.api.inventory import router as inventory_router
from app.api.orders import router as orders_router
from app.api.products import router as products_router
from app.api.ai import router as ai_router

api_router = APIRouter(prefix="/api")

api_router.include_router(auth_router)
api_router.include_router(products_router)
api_router.include_router(customers_router)
api_router.include_router(orders_router)
api_router.include_router(inventory_router)
api_router.include_router(dashboard_router)
api_router.include_router(ai_router)

__all__ = ["api_router"]
