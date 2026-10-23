from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.customer import Customer
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.user import User
from app.schemas.customer import CustomerCreate, CustomerResponse, CustomerUpdate
from app.schemas.order import OrderResponse

router = APIRouter(prefix="/customers", tags=["Customers"])


@router.get("", response_model=dict)
async def list_customers(
    search: str | None = Query(None, description="Search by name, phone, or email"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List customers with search and total order counts."""
    query = select(
        Customer,
        func.count(Order.id).label("orders_count"),
    ).outerjoin(
        Order, (Order.customer_id == Customer.id)
    ).where(
        Customer.is_deleted == False
    ).group_by(Customer.id)

    if search:
        search_term = f"%{search.strip()}%"
        query = query.where(
            or_(
                Customer.name.ilike(search_term),
                Customer.phone.ilike(search_term),
                Customer.email.ilike(search_term),
                Customer.address.ilike(search_term),
            )
        )

    # Count total
    count_subquery = select(Customer.id).where(Customer.is_deleted == False)
    if search:
        search_term = f"%{search.strip()}%"
        count_subquery = count_subquery.where(
            or_(
                Customer.name.ilike(search_term),
                Customer.phone.ilike(search_term),
                Customer.email.ilike(search_term),
                Customer.address.ilike(search_term),
            )
        )
    total_res = await db.execute(select(func.count()).select_from(count_subquery.subquery()))
    total_count = total_res.scalar_one() or 0

    # Paginate
    paginated_query = query.order_by(Customer.name.asc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(paginated_query)
    rows = result.all()

    items = []
    for customer, orders_count in rows:
        resp = CustomerResponse.model_validate(customer)
        resp.orders_count = orders_count or 0
        items.append(resp)

    return {
        "items": items,
        "total": total_count,
        "page": page,
        "page_size": page_size,
        "total_pages": (total_count + page_size - 1) // page_size if total_count > 0 else 1,
    }


@router.post("", response_model=CustomerResponse, status_code=status.HTTP_201_CREATED)
async def create_customer(
    payload: CustomerCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new customer."""
    customer = Customer(
        name=payload.name.strip(),
        phone=payload.phone.strip(),
        email=payload.email.strip().lower() if payload.email else None,
        address=payload.address.strip() if payload.address else None,
        notes=payload.notes.strip() if payload.notes else None,
    )
    db.add(customer)
    await db.commit()
    await db.refresh(customer)
    resp = CustomerResponse.model_validate(customer)
    resp.orders_count = 0
    return resp


@router.get("/{customer_id}", response_model=CustomerResponse)
async def get_customer(
    customer_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get customer by ID with their order count."""
    res = await db.execute(select(Customer).where(Customer.id == customer_id, Customer.is_deleted == False))
    customer = res.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found.")

    order_count_res = await db.execute(select(func.count(Order.id)).where(Order.customer_id == customer_id))
    resp = CustomerResponse.model_validate(customer)
    resp.orders_count = order_count_res.scalar_one() or 0
    return resp


@router.put("/{customer_id}", response_model=CustomerResponse)
async def update_customer(
    customer_id: int,
    payload: CustomerUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update customer details."""
    res = await db.execute(select(Customer).where(Customer.id == customer_id, Customer.is_deleted == False))
    customer = res.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found.")

    if payload.name is not None:
        customer.name = payload.name.strip()
    if payload.phone is not None:
        customer.phone = payload.phone.strip()
    if payload.email is not None:
        customer.email = payload.email.strip().lower() if payload.email else None
    if payload.address is not None:
        customer.address = payload.address.strip() if payload.address else None
    if payload.notes is not None:
        customer.notes = payload.notes.strip() if payload.notes else None

    await db.commit()
    await db.refresh(customer)

    order_count_res = await db.execute(select(func.count(Order.id)).where(Order.customer_id == customer_id))
    resp = CustomerResponse.model_validate(customer)
    resp.orders_count = order_count_res.scalar_one() or 0
    return resp


@router.delete("/{customer_id}")
async def delete_customer(
    customer_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Soft delete customer; prevent deletion if active orders exist."""
    res = await db.execute(select(Customer).where(Customer.id == customer_id, Customer.is_deleted == False))
    customer = res.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found.")

    # Check orders
    order_count_res = await db.execute(select(func.count(Order.id)).where(Order.customer_id == customer_id))
    order_count = order_count_res.scalar_one() or 0
    if order_count > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete customer '{customer.name}' because they have {order_count} associated orders. The customer is preserved for financial records.",
        )

    customer.is_deleted = True
    await db.commit()
    return {"success": True, "message": f"Customer '{customer.name}' was successfully deleted."}


@router.get("/{customer_id}/orders", response_model=list[dict])
async def get_customer_orders(
    customer_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get full order history for a specific customer."""
    res = await db.execute(select(Customer).where(Customer.id == customer_id, Customer.is_deleted == False))
    customer = res.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found.")

    orders_stmt = (
        select(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.product))
        .where(Order.customer_id == customer_id)
        .order_by(Order.created_at.desc())
    )
    orders_res = await db.execute(orders_stmt)
    orders = orders_res.scalars().all()

    output = []
    for ord in orders:
        output.append({
            "id": ord.id,
            "order_number": ord.order_number,
            "total_amount": float(ord.total_amount),
            "order_status": ord.order_status,
            "payment_status": ord.payment_status,
            "created_at": ord.created_at.isoformat(),
            "items_count": len(ord.items),
            "items": [
                {
                    "product_name": item.product.name if item.product else "Unknown",
                    "quantity": item.quantity,
                    "unit_price": float(item.unit_price),
                    "line_total": float(item.line_total),
                }
                for item in ord.items
            ],
        })
    return output
