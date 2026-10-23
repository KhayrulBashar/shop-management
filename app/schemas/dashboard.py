from decimal import Decimal
from typing import Any
from pydantic import BaseModel


class DashboardStats(BaseModel):
    total_products: int
    total_customers: int
    total_orders: int
    total_sales: Decimal
    low_stock_count: int
    recent_orders: list[dict[str, Any]] = []
    sales_chart: dict[str, Any] = {}
