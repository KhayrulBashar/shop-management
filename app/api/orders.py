from datetime import datetime, timezone
from decimal import Decimal
import secrets
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.customer import Customer
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.product import Product
from app.models.stock_movement import StockMovement
from app.models.user import User
from app.schemas.order import (
    OrderCreate,
    OrderItemResponse,
    OrderResponse,
    OrderStatusUpdate,
)

router = APIRouter(prefix="/orders", tags=["Orders"])


def generate_order_number() -> str:
    now_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    random_suffix = secrets.token_hex(2).upper()
    return f"ORD-{now_str}-{random_suffix}"


def format_order_response(order: Order) -> OrderResponse:
    items_resp = []
    if order.items:
        for it in order.items:
            items_resp.append(
                OrderItemResponse(
                    id=it.id,
                    product_id=it.product_id,
                    product_name=it.product.name if it.product else "Unknown Product",
                    product_sku=it.product.sku if it.product else "N/A",
                    quantity=it.quantity,
                    unit_price=it.unit_price,
                    line_total=it.line_total,
                )
            )

    return OrderResponse(
        id=order.id,
        order_number=order.order_number,
        customer_id=order.customer_id,
        customer_name=order.customer.name if order.customer else "Unknown Customer",
        customer_phone=order.customer.phone if order.customer else "",
        customer_email=order.customer.email if order.customer else None,
        customer_address=order.customer.address if order.customer else None,
        total_amount=order.total_amount,
        order_status=order.order_status,
        payment_status=order.payment_status,
        notes=order.notes,
        created_at=order.created_at,
        items=items_resp,
    )


@router.get("", response_model=dict)
async def list_orders(
    search: str | None = Query(None, description="Search by order number or customer name/phone"),
    order_status: str | None = Query(None, description="Filter by order status"),
    payment_status: str | None = Query(None, description="Filter by payment status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List orders with filters, search, and pagination."""
    query = (
        select(Order)
        .options(
            selectinload(Order.customer),
            selectinload(Order.items).selectinload(OrderItem.product),
        )
    )

    if search:
        search_term = f"%{search.strip()}%"
        query = query.join(Order.customer).where(
            or_(
                Order.order_number.ilike(search_term),
                Customer.name.ilike(search_term),
                Customer.phone.ilike(search_term),
            )
        )

    if order_status and order_status.lower() != "all":
        query = query.where(Order.order_status == order_status)

    if payment_status and payment_status.lower() != "all":
        query = query.where(Order.payment_status == payment_status)

    # Count
    count_query = select(func.count(Order.id))
    if search:
        search_term = f"%{search.strip()}%"
        count_query = count_query.join(Order.customer).where(
            or_(
                Order.order_number.ilike(search_term),
                Customer.name.ilike(search_term),
                Customer.phone.ilike(search_term),
            )
        )
    if order_status and order_status.lower() != "all":
        count_query = count_query.where(Order.order_status == order_status)
    if payment_status and payment_status.lower() != "all":
        count_query = count_query.where(Order.payment_status == payment_status)

    total_res = await db.execute(count_query)
    total_count = total_res.scalar_one() or 0

    # Execute
    paginated_query = query.order_by(Order.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    orders_res = await db.execute(paginated_query)
    orders = orders_res.scalars().all()

    return {
        "items": [format_order_response(o) for o in orders],
        "total": total_count,
        "page": page,
        "page_size": page_size,
        "total_pages": (total_count + page_size - 1) // page_size if total_count > 0 else 1,
    }


@router.post("", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    payload: OrderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create a new order:
    1. Validates customer.
    2. Validates stock availability for each item.
    3. Deducts stock atomically and logs StockMovement(OUT).
    4. Computes line totals and total amount.
    """
    # 1. Customer validation
    cust_res = await db.execute(
        select(Customer).where(Customer.id == payload.customer_id, Customer.is_deleted == False)
    )
    customer = cust_res.scalar_one_or_none()
    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Selected customer not found or inactive.",
        )

    # 2. Consolidate requested quantities per product
    product_quantities: dict[int, int] = {}
    for item in payload.items:
        if item.quantity <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Item quantity must be greater than zero.",
            )
        product_quantities[item.product_id] = product_quantities.get(item.product_id, 0) + item.quantity

    # 3. Check products and stock availability
    products_res = await db.execute(
        select(Product).where(Product.id.in_(product_quantities.keys()), Product.is_deleted == False)
    )
    products_by_id = {p.id: p for p in products_res.scalars().all()}

    for pid, req_qty in product_quantities.items():
        product = products_by_id.get(pid)
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Product with ID {pid} was not found.",
            )
        if product.stock_quantity < req_qty:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Insufficient stock for '{product.name}' (SKU: {product.sku}). Available stock: {product.stock_quantity}, requested: {req_qty}.",
            )

    order_number = generate_order_number()
    grand_total = Decimal("0.00")
    order_items_to_add: list[OrderItem] = []

    # 4. Process each item and adjust stock
    for item_data in payload.items:
        product = products_by_id[item_data.product_id]
        unit_price = product.price
        line_total = unit_price * Decimal(item_data.quantity)
        grand_total += line_total

        order_items_to_add.append(
            OrderItem(
                product_id=product.id,
                quantity=item_data.quantity,
                unit_price=unit_price,
                line_total=line_total,
            )
        )

        # Deduct stock and log movement
        prev_stock = product.stock_quantity
        new_stock = prev_stock - item_data.quantity
        product.stock_quantity = new_stock

        movement = StockMovement(
            product_id=product.id,
            user_id=current_user.id,
            movement_type="OUT",
            quantity=item_data.quantity,
            previous_stock=prev_stock,
            new_stock=new_stock,
            reason=f"Order #{order_number} created for customer {customer.name}",
        )
        db.add(movement)

    # 5. Create Order
    new_order = Order(
        order_number=order_number,
        customer_id=customer.id,
        total_amount=grand_total,
        order_status=payload.order_status,
        payment_status=payload.payment_status,
        notes=payload.notes,
        items=order_items_to_add,
    )
    db.add(new_order)

    await db.commit()

    # Re-fetch with relationships
    stmt = (
        select(Order)
        .options(
            selectinload(Order.customer),
            selectinload(Order.items).selectinload(OrderItem.product),
        )
        .where(Order.id == new_order.id)
    )
    res = await db.execute(stmt)
    saved_order = res.scalar_one()

    return format_order_response(saved_order)


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get single order with items and customer info."""
    stmt = (
        select(Order)
        .options(
            selectinload(Order.customer),
            selectinload(Order.items).selectinload(OrderItem.product),
        )
        .where(Order.id == order_id)
    )
    res = await db.execute(stmt)
    order = res.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")
    return format_order_response(order)


@router.patch("/{order_id}/status", response_model=OrderResponse)
async def update_order_status(
    order_id: int,
    payload: OrderStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Update order status or payment status.
    - If transitioning to CANCELLED from an active status, automatically restores stock.
    - If transitioning from CANCELLED to an active status, verifies and deducts stock again.
    """
    stmt = (
        select(Order)
        .options(
            selectinload(Order.customer),
            selectinload(Order.items).selectinload(OrderItem.product),
        )
        .where(Order.id == order_id)
    )
    res = await db.execute(stmt)
    order = res.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")

    old_status = order.order_status
    new_status = payload.order_status

    if new_status and new_status != old_status:
        # 1. Order is being CANCELLED -> restore stock
        if new_status == "Cancelled" and old_status != "Cancelled":
            for item in order.items:
                product = item.product
                if product:
                    prev_stock = product.stock_quantity
                    new_stock = prev_stock + item.quantity
                    product.stock_quantity = new_stock

                    movement = StockMovement(
                        product_id=product.id,
                        user_id=current_user.id,
                        movement_type="IN",
                        quantity=item.quantity,
                        previous_stock=prev_stock,
                        new_stock=new_stock,
                        reason=f"Order #{order.order_number} cancelled - stock restored",
                    )
                    db.add(movement)

        # 2. Order was CANCELLED and is now being REACTIVATED -> check and deduct stock
        elif old_status == "Cancelled" and new_status != "Cancelled":
            # Check stock for all items first
            for item in order.items:
                product = item.product
                if not product or product.stock_quantity < item.quantity:
                    p_name = product.name if product else "Product"
                    avail = product.stock_quantity if product else 0
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Cannot un-cancel order: insufficient stock for '{p_name}'. Available: {avail}, needed: {item.quantity}.",
                    )

            # Deduct stock
            for item in order.items:
                product = item.product
                prev_stock = product.stock_quantity
                new_stock = prev_stock - item.quantity
                product.stock_quantity = new_stock

                movement = StockMovement(
                    product_id=product.id,
                    user_id=current_user.id,
                    movement_type="OUT",
                    quantity=item.quantity,
                    previous_stock=prev_stock,
                    new_stock=new_stock,
                    reason=f"Order #{order.order_number} reactivated from cancelled - stock deducted",
                )
                db.add(movement)

        order.order_status = new_status

    if payload.payment_status is not None:
        order.payment_status = payload.payment_status

    if payload.notes is not None:
        order.notes = payload.notes

    await db.commit()
    await db.refresh(order)
    return format_order_response(order)


@router.get("/{order_id}/invoice", response_model=dict)
async def get_order_invoice(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve full formatted invoice data for printing."""
    stmt = (
        select(Order)
        .options(
            selectinload(Order.customer),
            selectinload(Order.items).selectinload(OrderItem.product),
        )
        .where(Order.id == order_id)
    )
    res = await db.execute(stmt)
    order = res.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")

    items_list = []
    for it in order.items:
        items_list.append({
            "name": it.product.name if it.product else "Unknown Product",
            "sku": it.product.sku if it.product else "N/A",
            "quantity": it.quantity,
            "unit_price": float(it.unit_price),
            "line_total": float(it.line_total),
        })

    invoice_data = {
        "invoice_number": f"INV-{order.order_number}",
        "order_number": order.order_number,
        "date": order.created_at.strftime("%B %d, %Y - %I:%M %p"),
        "customer": {
            "name": order.customer.name if order.customer else "Walk-in Customer",
            "phone": order.customer.phone if order.customer else "N/A",
            "email": order.customer.email if order.customer else "N/A",
            "address": order.customer.address if order.customer else "N/A",
        },
        "order_status": order.order_status,
        "payment_status": order.payment_status,
        "items": items_list,
        "total_amount": float(order.total_amount),
        "notes": order.notes or "Thank you for your business!",
    }
    return invoice_data