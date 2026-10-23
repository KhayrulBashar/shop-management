from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.order_item import OrderItem
from app.models.product import Product
from app.models.stock_movement import StockMovement
from app.models.user import User
from app.schemas.product import ProductCreate, ProductResponse, ProductUpdate

router = APIRouter(prefix="/products", tags=["Products"])


@router.get("", response_model=dict)
async def list_products(
    search: str | None = Query(None, description="Search by name or SKU"),
    category: str | None = Query(None, description="Filter by category"),
    low_stock_only: bool = Query(False, description="Filter products with stock <= reorder_level"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List products with search, category filtering, low stock filter, and pagination."""
    query = select(Product).where(Product.is_deleted == False)

    if search:
        search_term = f"%{search.strip()}%"
        query = query.where(
            or_(
                Product.name.ilike(search_term),
                Product.sku.ilike(search_term),
                Product.category.ilike(search_term),
            )
        )

    if category and category.lower() != "all":
        query = query.where(Product.category.ilike(category.strip()))

    if low_stock_only:
        query = query.where(Product.stock_quantity <= Product.reorder_level)

    # Total count query
    count_query = select(func.count()).select_from(query.subquery())
    total_res = await db.execute(count_query)
    total_count = total_res.scalar_one() or 0

    # Paginated results ordered by name
    paginated_query = query.order_by(Product.name.asc()).offset((page - 1) * page_size).limit(page_size)
    items_res = await db.execute(paginated_query)
    products = items_res.scalars().all()

    # Get distinct categories for filtering
    cat_query = select(Product.category).where(Product.is_deleted == False).distinct().order_by(Product.category.asc())
    cat_res = await db.execute(cat_query)
    categories = [c for c in cat_res.scalars().all() if c]

    return {
        "items": [ProductResponse.model_validate(p) for p in products],
        "total": total_count,
        "page": page,
        "page_size": page_size,
        "total_pages": (total_count + page_size - 1) // page_size if total_count > 0 else 1,
        "categories": categories,
    }


@router.post("", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    payload: ProductCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new product with duplicate SKU check and initial stock movement log."""
    sku_upper = payload.sku.strip().upper()
    existing_sku = await db.execute(
        select(Product).where(Product.sku == sku_upper, Product.is_deleted == False)
    )
    if existing_sku.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Product with SKU '{sku_upper}' already exists.",
        )

    product = Product(
        name=payload.name.strip(),
        sku=sku_upper,
        category=payload.category.strip() or "General",
        price=payload.price,
        stock_quantity=payload.stock_quantity,
        reorder_level=payload.reorder_level,
    )
    db.add(product)
    await db.flush()

    # If initial stock > 0, log an initial stock movement
    if product.stock_quantity > 0:
        movement = StockMovement(
            product_id=product.id,
            user_id=current_user.id,
            movement_type="IN",
            quantity=product.stock_quantity,
            previous_stock=0,
            new_stock=product.stock_quantity,
            reason="Initial product creation stock",
        )
        db.add(movement)

    await db.commit()
    await db.refresh(product)
    return product


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve single product details."""
    res = await db.execute(select(Product).where(Product.id == product_id, Product.is_deleted == False))
    product = res.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")
    return product


@router.put("/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: int,
    payload: ProductUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update an existing product."""
    res = await db.execute(select(Product).where(Product.id == product_id, Product.is_deleted == False))
    product = res.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")

    if payload.sku:
        new_sku = payload.sku.strip().upper()
        if new_sku != product.sku:
            check_sku = await db.execute(
                select(Product).where(
                    Product.sku == new_sku,
                    Product.id != product_id,
                    Product.is_deleted == False,
                )
            )
            if check_sku.scalar_one_or_none():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Product SKU '{new_sku}' is already in use by another product.",
                )
            product.sku = new_sku

    if payload.name is not None:
        product.name = payload.name.strip()
    if payload.category is not None:
        product.category = payload.category.strip() or "General"
    if payload.price is not None:
        product.price = payload.price
    if payload.reorder_level is not None:
        product.reorder_level = payload.reorder_level

    # Note: Stock changes should ideally go through Inventory/Stock Movement, but if updated here:
    if payload.stock_quantity is not None and payload.stock_quantity != product.stock_quantity:
        prev = product.stock_quantity
        diff = payload.stock_quantity - prev
        movement_type = "IN" if diff > 0 else "OUT"
        movement = StockMovement(
            product_id=product.id,
            user_id=current_user.id,
            movement_type=movement_type if diff != 0 else "ADJUSTMENT",
            quantity=abs(diff),
            previous_stock=prev,
            new_stock=payload.stock_quantity,
            reason="Manual update via Product Edit modal",
        )
        db.add(movement)
        product.stock_quantity = payload.stock_quantity

    await db.commit()
    await db.refresh(product)
    return product


@router.delete("/{product_id}")
async def delete_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Delete product with reference integrity check.
    If product has associated order items, prevents deletion.
    """
    res = await db.execute(select(Product).where(Product.id == product_id, Product.is_deleted == False))
    product = res.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")

    # Check order items reference
    order_check = await db.execute(
        select(func.count(OrderItem.id)).where(OrderItem.product_id == product_id)
    )
    orders_count = order_check.scalar_one() or 0
    if orders_count > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete product '{product.name}' because it is linked to {orders_count} customer orders. You may mark its stock as 0 instead to preserve historical records.",
        )

    # Soft delete to preserve historical integrity while hiding from active lists
    product.is_deleted = True
    await db.commit()
    return {"success": True, "message": f"Product '{product.name}' was successfully deleted."}
