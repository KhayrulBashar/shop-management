from datetime import datetime, timedelta, timezone
from decimal import Decimal
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.customer import Customer
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.product import Product
from app.models.user import User
from app.schemas.dashboard import DashboardStats
from app.schemas.product import ProductResponse

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/stats", response_model=DashboardStats)
async def get_dashboard_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve overview metrics: counts, revenue, low stock count, recent orders, and chart data."""
    # 1. Total active products
    prod_res = await db.execute(
        select(func.count(Product.id)).where(Product.is_deleted == False)
    )
    total_products = prod_res.scalar_one() or 0

    # 2. Total active customers
    cust_res = await db.execute(
        select(func.count(Customer.id)).where(Customer.is_deleted == False)
    )
    total_customers = cust_res.scalar_one() or 0

    # 3. Total orders & total revenue (Delivered and Paid only)
    ord_count_res = await db.execute(select(func.count(Order.id)))
    total_orders = ord_count_res.scalar_one() or 0

    sales_res = await db.execute(
        select(func.sum(Order.total_amount)).where(
            Order.order_status == "Delivered",
            Order.payment_status == "Paid",
        )
    )
    total_sales = sales_res.scalar_one() or Decimal("0.00")

    # 4. Low stock products count
    low_stock_res = await db.execute(
        select(func.count(Product.id)).where(
            Product.is_deleted == False,
            Product.stock_quantity <= Product.reorder_level,
        )
    )
    low_stock_count = low_stock_res.scalar_one() or 0

    # 5. Recent orders (top 6)
    recent_stmt = (
        select(Order)
        .options(selectinload(Order.customer))
        .order_by(Order.created_at.desc())
        .limit(6)
    )
    recent_res = await db.execute(recent_stmt)
    recent_orders_list = recent_res.scalars().all()

    formatted_recent = []
    for o in recent_orders_list:
        formatted_recent.append({
            "id": o.id,
            "order_number": o.order_number,
            "customer_name": o.customer.name if o.customer else "Walk-in",
            "total_amount": float(o.total_amount),
            "order_status": o.order_status,
            "payment_status": o.payment_status,
            "created_at": o.created_at.strftime("%b %d, %Y - %I:%M %p"),
        })

    # 6. Chart data: last 7 days sales and orders
    now = datetime.now(timezone.utc)
    chart_labels = []
    chart_sales = []
    chart_orders = []

    for i in range(6, -1, -1):
        day_date = (now - timedelta(days=i)).date()
        day_start = datetime(day_date.year, day_date.month, day_date.day, 0, 0, 0, tzinfo=timezone.utc)
        day_end = datetime(day_date.year, day_date.month, day_date.day, 23, 59, 59, tzinfo=timezone.utc)
        label_str = day_date.strftime("%a (%d %b)")

        day_sales_stmt = select(func.sum(Order.total_amount)).where(
            Order.created_at >= day_start,
            Order.created_at <= day_end,
            Order.order_status == "Delivered",
            Order.payment_status == "Paid",
        )
        day_sales_res = await db.execute(day_sales_stmt)
        day_sales_val = float(day_sales_res.scalar_one() or 0)

        day_orders_stmt = select(func.count(Order.id)).where(
            Order.created_at >= day_start,
            Order.created_at <= day_end,
        )
        day_orders_res = await db.execute(day_orders_stmt)
        day_orders_val = int(day_orders_res.scalar_one() or 0)

        chart_labels.append(label_str)
        chart_sales.append(day_sales_val)
        chart_orders.append(day_orders_val)

    sales_chart = {
        "labels": chart_labels,
        "sales": chart_sales,
        "orders": chart_orders,
    }

    return DashboardStats(
        total_products=total_products,
        total_customers=total_customers,
        total_orders=total_orders,
        total_sales=total_sales,
        low_stock_count=low_stock_count,
        recent_orders=formatted_recent,
        sales_chart=sales_chart,
    )


@router.get("/low-stock", response_model=list[ProductResponse])
async def get_low_stock_products(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve all products currently at or below their reorder level."""
    stmt = (
        select(Product)
        .where(
            Product.is_deleted == False,
            Product.stock_quantity <= Product.reorder_level,
        )
        .order_by(Product.stock_quantity.asc())
    )
    res = await db.execute(stmt)
    products = res.scalars().all()
    return [ProductResponse.model_validate(p) for p in products]
