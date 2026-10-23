from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.product import Product
from app.models.stock_movement import StockMovement
from app.models.user import User
from app.schemas.inventory import StockMovementCreate, StockMovementResponse

router = APIRouter(prefix="/inventory", tags=["Inventory"])


@router.get("/movements", response_model=dict)
async def list_stock_movements(
    movement_type: str | None = Query(None, description="Filter by type: IN, OUT, ADJUSTMENT"),
    product_id: int | None = Query(None, description="Filter by product ID"),
    search: str | None = Query(None, description="Search by product name, SKU, or reason"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List stock movement history with filters and search."""
    query = (
        select(StockMovement)
        .options(
            selectinload(StockMovement.product),
            selectinload(StockMovement.user),
        )
    )

    if movement_type and movement_type.upper() != "ALL":
        query = query.where(StockMovement.movement_type == movement_type.upper())

    if product_id:
        query = query.where(StockMovement.product_id == product_id)

    if search:
        search_term = f"%{search.strip()}%"
        query = query.join(StockMovement.product).where(
            or_(
                Product.name.ilike(search_term),
                Product.sku.ilike(search_term),
                StockMovement.reason.ilike(search_term),
            )
        )

    # Count
    count_query = select(func.count(StockMovement.id))
    if movement_type and movement_type.upper() != "ALL":
        count_query = count_query.where(StockMovement.movement_type == movement_type.upper())
    if product_id:
        count_query = count_query.where(StockMovement.product_id == product_id)
    if search:
        search_term = f"%{search.strip()}%"
        count_query = count_query.join(StockMovement.product).where(
            or_(
                Product.name.ilike(search_term),
                Product.sku.ilike(search_term),
                StockMovement.reason.ilike(search_term),
            )
        )

    total_res = await db.execute(count_query)
    total_count = total_res.scalar_one() or 0

    paginated_query = (
        query.order_by(StockMovement.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(paginated_query)
    movements = result.scalars().all()

    items = []
    for m in movements:
        items.append(
            StockMovementResponse(
                id=m.id,
                product_id=m.product_id,
                product_name=m.product.name if m.product else "Deleted Product",
                product_sku=m.product.sku if m.product else "N/A",
                movement_type=m.movement_type,
                quantity=m.quantity,
                previous_stock=m.previous_stock,
                new_stock=m.new_stock,
                reason=m.reason,
                user_name=m.user.full_name if m.user else "System",
                created_at=m.created_at,
            )
        )

    return {
        "items": items,
        "total": total_count,
        "page": page,
        "page_size": page_size,
        "total_pages": (total_count + page_size - 1) // page_size if total_count > 0 else 1,
    }


@router.post("/movement", response_model=StockMovementResponse, status_code=status.HTTP_201_CREATED)
async def create_stock_movement(
    payload: StockMovementCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Perform a stock action (IN, OUT, ADJUSTMENT):
    - IN: adds quantity to current stock
    - OUT: deducts quantity (validates stock >= quantity)
    - ADJUSTMENT: sets current stock directly to quantity
    Atomic database transaction with movement audit log.
    """
    res = await db.execute(
        select(Product).where(Product.id == payload.product_id, Product.is_deleted == False)
    )
    product = res.scalar_one_or_none()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found or inactive.",
        )

    prev_stock = product.stock_quantity
    movement_type = payload.movement_type.upper()
    qty = payload.quantity

    if movement_type == "IN":
        new_stock = prev_stock + qty
    elif movement_type == "OUT":
        if prev_stock < qty:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot remove {qty} units. Current stock is only {prev_stock} units.",
            )
        new_stock = prev_stock - qty
    elif movement_type == "ADJUSTMENT":
        new_stock = qty
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid movement type. Must be IN, OUT, or ADJUSTMENT.",
        )

    product.stock_quantity = new_stock

    movement = StockMovement(
        product_id=product.id,
        user_id=current_user.id,
        movement_type=movement_type,
        quantity=qty,
        previous_stock=prev_stock,
        new_stock=new_stock,
        reason=payload.reason.strip() if payload.reason else f"Manual {movement_type} adjustment",
    )
    db.add(movement)
    await db.commit()
    await db.refresh(movement)
    await db.refresh(product)

    return StockMovementResponse(
        id=movement.id,
        product_id=product.id,
        product_name=product.name,
        product_sku=product.sku,
        movement_type=movement.movement_type,
        quantity=movement.quantity,
        previous_stock=movement.previous_stock,
        new_stock=movement.new_stock,
        reason=movement.reason,
        user_name=current_user.full_name,
        created_at=movement.created_at,
    )
