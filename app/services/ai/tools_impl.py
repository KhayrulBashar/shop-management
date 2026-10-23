from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import re
from typing import Any
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.customer import Customer
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.product import Product
from app.models.stock_movement import StockMovement
from app.models.user import User
from app.services.ai.registry import ToolDefinition, ToolParameter, tool_registry


# ---------------------------------------------------------------------------
# 1. Dashboard & Analytics Tools
# ---------------------------------------------------------------------------

async def handle_get_dashboard_stats(db: AsyncSession, current_user: User, args: dict[str, Any]) -> dict[str, Any]:
    prod_res = await db.execute(select(func.count(Product.id)).where(Product.is_deleted == False))
    total_products = prod_res.scalar_one() or 0

    cust_res = await db.execute(select(func.count(Customer.id)).where(Customer.is_deleted == False))
    total_customers = cust_res.scalar_one() or 0

    ord_res = await db.execute(select(func.count(Order.id)))
    total_orders = ord_res.scalar_one() or 0

    # Strict revenue rule: Delivered + Paid only
    sales_res = await db.execute(
        select(func.sum(Order.total_amount)).where(
            Order.order_status == "Delivered",
            Order.payment_status == "Paid",
        )
    )
    total_sales = float(sales_res.scalar_one() or 0.0)

    low_res = await db.execute(
        select(func.count(Product.id)).where(
            Product.is_deleted == False,
            Product.stock_quantity <= Product.reorder_level,
        )
    )
    low_stock_count = low_res.scalar_one() or 0

    return {
        "total_products": total_products,
        "total_customers": total_customers,
        "total_orders": total_orders,
        "total_sales_tk": total_sales,
        "revenue_calculation_rule": "Strictly Delivered and Paid orders only",
        "low_stock_items_count": low_stock_count,
    }


tool_registry.register(
    ToolDefinition(
        name="get_dashboard_stats",
        description="Retrieve high-level business analytics: total active products, customer count, order count, total verified revenue (Delivered + Paid only), and low-stock count.",
        parameters=[],
        is_mutation=False,
        handler=handle_get_dashboard_stats,
    )
)


async def handle_get_low_stock_products(db: AsyncSession, current_user: User, args: dict[str, Any]) -> dict[str, Any]:
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
    items = []
    for p in products:
        items.append({
            "id": p.id,
            "sku": p.sku,
            "name": p.name,
            "category": p.category,
            "price": float(p.price),
            "current_stock": p.stock_quantity,
            "reorder_level": p.reorder_level,
            "shortage": p.reorder_level - p.stock_quantity if p.reorder_level > p.stock_quantity else 0,
        })
    return {
        "count": len(items),
        "low_stock_products": items,
        "recommendation": "Consider creating Stock IN movements for these items to maintain safety buffer.",
    }


tool_registry.register(
    ToolDefinition(
        name="get_low_stock_products",
        description="Retrieve all products that are currently at or below their safety reorder threshold.",
        parameters=[],
        is_mutation=False,
        handler=handle_get_low_stock_products,
    )
)


# ---------------------------------------------------------------------------
# 2. Product Management Tools
# ---------------------------------------------------------------------------

async def handle_search_products(db: AsyncSession, current_user: User, args: dict[str, Any]) -> dict[str, Any]:
    query_str = args.get("query", "").strip()
    category = args.get("category")
    stmt = select(Product).where(Product.is_deleted == False)

    if query_str:
        term = f"%{query_str}%"
        stmt = stmt.where(
            or_(
                Product.name.ilike(term),
                Product.sku.ilike(term),
                Product.category.ilike(term),
            )
        )
    if category and category.lower() != "all":
        stmt = stmt.where(Product.category.ilike(category.strip()))

    stmt = stmt.order_by(Product.name.asc()).limit(args.get("limit", 15))
    res = await db.execute(stmt)
    products = res.scalars().all()

    return {
        "count": len(products),
        "products": [
            {
                "id": p.id,
                "sku": p.sku,
                "name": p.name,
                "category": p.category,
                "price": float(p.price),
                "stock_quantity": p.stock_quantity,
                "reorder_level": p.reorder_level,
                "is_low_stock": p.stock_quantity <= p.reorder_level,
            }
            for p in products
        ],
    }


tool_registry.register(
    ToolDefinition(
        name="search_products",
        description="Search for active products by name, SKU, or category.",
        parameters=[
            ToolParameter(name="query", type="string", description="Search keyword for name, SKU, or category", required=False),
            ToolParameter(name="category", type="string", description="Filter by category", required=False),
            ToolParameter(name="limit", type="integer", description="Max records to return (default 15)", required=False, default=15),
        ],
        is_mutation=False,
        handler=handle_search_products,
    )
)


async def handle_create_product(db: AsyncSession, current_user: User, args: dict[str, Any]) -> dict[str, Any]:
    name = args["name"].strip()
    sku = args["sku"].strip().upper()
    category = args.get("category", "General").strip() or "General"
    price = Decimal(str(args["price"]))
    stock_quantity = int(args.get("stock_quantity", 0))
    reorder_level = int(args.get("reorder_level", 5))

    # Verify duplicate SKU across all records (including soft-deleted to avoid DB unique constraint crash)
    existing = await db.execute(select(Product).where(Product.sku == sku))
    dup = existing.scalar_one_or_none()
    if dup:
        if dup.is_deleted:
            raise ValueError(f"Product SKU '{sku}' was previously soft-deleted. Please reactivate it or use a unique SKU.")
        raise ValueError(f"Product SKU '{sku}' is already in use by active product '{dup.name}'.")

    prod = Product(
        name=name,
        sku=sku,
        category=category,
        price=price,
        stock_quantity=stock_quantity,
        reorder_level=reorder_level,
    )
    db.add(prod)
    await db.flush()

    if stock_quantity > 0:
        mv = StockMovement(
            product_id=prod.id,
            user_id=current_user.id,
            movement_type="IN",
            quantity=stock_quantity,
            previous_stock=0,
            new_stock=stock_quantity,
            reason="Initial product creation stock via AI Assistant",
        )
        db.add(mv)

    await db.commit()
    await db.refresh(prod)

    return {
        "success": True,
        "product_id": prod.id,
        "name": prod.name,
        "sku": prod.sku,
        "price": float(prod.price),
        "stock_quantity": prod.stock_quantity,
        "category": prod.category,
    }


def preview_create_product(args: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    title = "Confirm Product Creation"
    summary = f"Create new product '{args.get('name')}' with SKU '{args.get('sku', '').upper()}' priced at Tk.{args.get('price')}."
    details = {
        "Product Name": args.get("name"),
        "SKU": str(args.get("sku", "")).upper(),
        "Category": args.get("category", "General"),
        "Price": f"Tk.{args.get('price')}",
        "Initial Stock": args.get("stock_quantity", 0),
        "Reorder Safety Level": args.get("reorder_level", 5),
    }
    return title, summary, details


tool_registry.register(
    ToolDefinition(
        name="create_product",
        description="Create a new product in the catalog with SKU, price, category, initial stock, and reorder level. Requires user confirmation.",
        parameters=[
            ToolParameter(name="name", type="string", description="Full name of the product", required=True),
            ToolParameter(name="sku", type="string", description="Unique SKU code (e.g. LOGI-MX3)", required=True),
            ToolParameter(name="price", type="number", description="Selling price per unit in Taka", required=True),
            ToolParameter(name="category", type="string", description="Product category (e.g. Gaming, Accessories)", required=False, default="General"),
            ToolParameter(name="stock_quantity", type="integer", description="Initial inventory quantity on hand", required=False, default=0),
            ToolParameter(name="reorder_level", type="integer", description="Safety threshold triggering low stock alerts", required=False, default=5),
        ],
        is_mutation=True,
        handler=handle_create_product,
        preview_generator=preview_create_product,
    )
)


# ---------------------------------------------------------------------------
# 3. Customer Management Tools
# ---------------------------------------------------------------------------

async def handle_search_customers(db: AsyncSession, current_user: User, args: dict[str, Any]) -> dict[str, Any]:
    query_str = args.get("query", "").strip()
    stmt = (
        select(Customer, func.count(Order.id).label("orders_count"))
        .outerjoin(Order, (Order.customer_id == Customer.id))
        .where(Customer.is_deleted == False)
        .group_by(Customer.id)
    )
    if query_str:
        term = f"%{query_str}%"
        stmt = stmt.where(
            or_(
                Customer.name.ilike(term),
                Customer.phone.ilike(term),
                Customer.email.ilike(term),
            )
        )
    stmt = stmt.order_by(Customer.name.asc()).limit(args.get("limit", 15))
    res = await db.execute(stmt)
    rows = res.all()

    return {
        "count": len(rows),
        "customers": [
            {
                "id": c.id,
                "name": c.name,
                "phone": c.phone,
                "email": c.email,
                "address": c.address,
                "orders_count": count or 0,
            }
            for c, count in rows
        ],
    }


tool_registry.register(
    ToolDefinition(
        name="search_customers",
        description="Search for customers by name, phone number, or email.",
        parameters=[
            ToolParameter(name="query", type="string", description="Search term for name, phone, or email", required=False),
            ToolParameter(name="limit", type="integer", description="Max records to return", required=False, default=15),
        ],
        is_mutation=False,
        handler=handle_search_customers,
    )
)


async def handle_create_customer(db: AsyncSession, current_user: User, args: dict[str, Any]) -> dict[str, Any]:
    name = args["name"].strip()
    phone = args["phone"].strip()
    email = args.get("email", "").strip().lower() if args.get("email") else None
    address = args.get("address", "").strip() if args.get("address") else None
    notes = args.get("notes", "").strip() if args.get("notes") else None

    customer = Customer(
        name=name,
        phone=phone,
        email=email,
        address=address,
        notes=notes,
    )
    db.add(customer)
    await db.commit()
    await db.refresh(customer)

    return {
        "success": True,
        "customer_id": customer.id,
        "name": customer.name,
        "phone": customer.phone,
        "email": customer.email,
        "address": customer.address,
    }


def preview_create_customer(args: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    title = "Confirm New Customer"
    summary = f"Add new client record for '{args.get('name')}' (Phone: {args.get('phone')})."
    details = {
        "Client Name": args.get("name"),
        "Phone Number": args.get("phone"),
        "Email Address": args.get("email") or "Not provided",
        "Delivery Address": args.get("address") or "Not provided",
        "Notes": args.get("notes") or "None",
    }
    return title, summary, details


tool_registry.register(
    ToolDefinition(
        name="create_customer",
        description="Add a new customer to the database. Requires user confirmation.",
        parameters=[
            ToolParameter(name="name", type="string", description="Customer full name", required=True),
            ToolParameter(name="phone", type="string", description="Contact phone number", required=True),
            ToolParameter(name="email", type="string", description="Email address", required=False),
            ToolParameter(name="address", type="string", description="Delivery or billing address", required=False),
            ToolParameter(name="notes", type="string", description="Special notes or courier preferences", required=False),
        ],
        is_mutation=True,
        handler=handle_create_customer,
        preview_generator=preview_create_customer,
    )
)


# ---------------------------------------------------------------------------
# 4. Order Management Tools
# ---------------------------------------------------------------------------

async def handle_list_orders(db: AsyncSession, current_user: User, args: dict[str, Any]) -> dict[str, Any]:
    stmt = (
        select(Order)
        .options(selectinload(Order.customer), selectinload(Order.items))
        .order_by(Order.created_at.desc())
        .limit(args.get("limit", 10))
    )
    res = await db.execute(stmt)
    orders = res.scalars().all()
    return {
        "count": len(orders),
        "orders": [
            {
                "id": o.id,
                "order_number": o.order_number,
                "customer_name": o.customer.name if o.customer else "Unknown",
                "total_amount": float(o.total_amount),
                "order_status": o.order_status,
                "payment_status": o.payment_status,
                "created_at": o.created_at.strftime("%Y-%m-%d %H:%M"),
                "items_count": len(o.items),
            }
            for o in orders
        ],
    }


tool_registry.register(
    ToolDefinition(
        name="list_orders",
        description="List recent sales orders with customer names, statuses, and totals.",
        parameters=[
            ToolParameter(name="limit", type="integer", description="Max records (default 10)", required=False, default=10),
        ],
        is_mutation=False,
        handler=handle_list_orders,
    )
)


async def handle_create_order(db: AsyncSession, current_user: User, args: dict[str, Any]) -> dict[str, Any]:
    import secrets
    from datetime import datetime, timezone

    customer_id = args["customer_id"]
    items_data = args["items"]
    order_status = args.get("order_status", "Processing")
    payment_status = args.get("payment_status", "Unpaid")
    notes = args.get("notes")

    # 1. Customer check
    cust_res = await db.execute(select(Customer).where(Customer.id == customer_id, Customer.is_deleted == False))
    customer = cust_res.scalar_one_or_none()
    if not customer:
        raise ValueError(f"Customer with ID {customer_id} not found or inactive.")

    # 2. Products and stock lock
    product_pids = [it["product_id"] for it in items_data]
    prods_res = await db.execute(
        select(Product).where(Product.id.in_(product_pids), Product.is_deleted == False).with_for_update()
    )
    products_by_id = {p.id: p for p in prods_res.scalars().all()}

    grand_total = Decimal("0.00")
    order_items_to_add = []
    order_number = f"ORD-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{secrets.token_hex(2).upper()}"

    for it in items_data:
        pid = it["product_id"]
        qty = int(it["quantity"])
        if qty <= 0:
            raise ValueError("Item quantity must be greater than zero.")
        product = products_by_id.get(pid)
        if not product:
            raise ValueError(f"Product ID {pid} was not found.")
        if product.stock_quantity < qty:
            raise ValueError(f"Insufficient stock for '{product.name}' (SKU: {product.sku}). Available: {product.stock_quantity}, requested: {qty}.")

        unit_price = product.price
        line_total = unit_price * Decimal(qty)
        grand_total += line_total

        order_items_to_add.append(
            OrderItem(
                product_id=product.id,
                quantity=qty,
                unit_price=unit_price,
                line_total=line_total,
            )
        )

        # Deduct stock and log movement
        prev_stock = product.stock_quantity
        new_stock = prev_stock - qty
        product.stock_quantity = new_stock

        movement = StockMovement(
            product_id=product.id,
            user_id=current_user.id,
            movement_type="OUT",
            quantity=qty,
            previous_stock=prev_stock,
            new_stock=new_stock,
            reason=f"Order #{order_number} created via AI Assistant for {customer.name}",
        )
        db.add(movement)

    new_order = Order(
        order_number=order_number,
        customer_id=customer.id,
        total_amount=grand_total,
        order_status=order_status,
        payment_status=payment_status,
        notes=notes,
        items=order_items_to_add,
    )
    db.add(new_order)
    await db.commit()
    await db.refresh(new_order)

    return {
        "success": True,
        "order_id": new_order.id,
        "order_number": new_order.order_number,
        "customer": customer.name,
        "total_amount": float(new_order.total_amount),
        "order_status": new_order.order_status,
        "payment_status": new_order.payment_status,
        "items_count": len(order_items_to_add),
    }


def preview_create_order(args: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    title = "Confirm Order Creation"
    summary = f"Create new sales order for Customer ID {args.get('customer_id')} with {len(args.get('items', []))} line item(s)."
    details = {
        "Customer ID": args.get("customer_id"),
        "Order Status": args.get("order_status", "Processing"),
        "Payment Status": args.get("payment_status", "Unpaid"),
        "Items Requested": args.get("items", []),
        "Notes": args.get("notes") or "Standard delivery",
    }
    return title, summary, details


tool_registry.register(
    ToolDefinition(
        name="create_order",
        description="Create a customer order, automatically deduct inventory stock, and log audit trail. Requires user confirmation.",
        parameters=[
            ToolParameter(name="customer_id", type="integer", description="ID of the purchasing customer", required=True),
            ToolParameter(
                name="items",
                type="array",
                description="List of items, each with 'product_id' (int) and 'quantity' (int)",
                required=True,
                items={"type": "object", "properties": {"product_id": {"type": "integer"}, "quantity": {"type": "integer"}}},
            ),
            ToolParameter(name="order_status", type="string", description="Status", required=False, default="Processing", enum=["Pending", "Processing", "Shipped", "Delivered"]),
            ToolParameter(name="payment_status", type="string", description="Payment", required=False, default="Unpaid", enum=["Unpaid", "Partial", "Paid"]),
            ToolParameter(name="notes", type="string", description="Order notes", required=False),
        ],
        is_mutation=True,
        handler=handle_create_order,
        preview_generator=preview_create_order,
    )
)


# ---------------------------------------------------------------------------
# 5. Inventory & Stock Movement Tools
# ---------------------------------------------------------------------------

async def handle_record_stock_movement(db: AsyncSession, current_user: User, args: dict[str, Any]) -> dict[str, Any]:
    product_id = args["product_id"]
    movement_type = args["movement_type"].upper()
    qty = int(args["quantity"])
    reason = args.get("reason", "").strip() or f"Manual {movement_type} via AI Assistant"

    prod_res = await db.execute(select(Product).where(Product.id == product_id, Product.is_deleted == False).with_for_update())
    product = prod_res.scalar_one_or_none()
    if not product:
        raise ValueError(f"Product ID {product_id} not found.")

    prev_stock = product.stock_quantity
    if movement_type == "IN":
        new_stock = prev_stock + qty
    elif movement_type == "OUT":
        if prev_stock < qty:
            raise ValueError(f"Cannot deduct {qty} units. Current stock for '{product.name}' is only {prev_stock}.")
        new_stock = prev_stock - qty
    elif movement_type == "ADJUSTMENT":
        new_stock = qty
    else:
        raise ValueError("Movement type must be IN, OUT, or ADJUSTMENT.")

    product.stock_quantity = new_stock
    movement = StockMovement(
        product_id=product.id,
        user_id=current_user.id,
        movement_type=movement_type,
        quantity=qty,
        previous_stock=prev_stock,
        new_stock=new_stock,
        reason=reason,
    )
    db.add(movement)
    await db.commit()
    await db.refresh(product)

    return {
        "success": True,
        "product_id": product.id,
        "product_name": product.name,
        "movement_type": movement_type,
        "quantity": qty,
        "previous_stock": prev_stock,
        "new_stock": new_stock,
        "reason": reason,
    }


def preview_record_stock_movement(args: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    title = f"Confirm Stock {args.get('movement_type', 'UPDATE').upper()}"
    summary = f"Record a stock {args.get('movement_type', '').upper()} movement of {args.get('quantity')} units for Product ID {args.get('product_id')}."
    details = {
        "Product ID": args.get("product_id"),
        "Movement Type": args.get("movement_type"),
        "Quantity": args.get("quantity"),
        "Reason / Note": args.get("reason") or "Replenishment / Manual adjustment",
    }
    return title, summary, details


tool_registry.register(
    ToolDefinition(
        name="record_stock_movement",
        description="Record an inventory stock movement (IN, OUT, or ADJUSTMENT) for a product. Requires user confirmation.",
        parameters=[
            ToolParameter(name="product_id", type="integer", description="ID of target product", required=True),
            ToolParameter(name="movement_type", type="string", description="Type of movement", required=True, enum=["IN", "OUT", "ADJUSTMENT"]),
            ToolParameter(name="quantity", type="integer", description="Quantity units", required=True),
            ToolParameter(name="reason", type="string", description="Reason for stock change", required=False),
        ],
        is_mutation=True,
        handler=handle_record_stock_movement,
        preview_generator=preview_record_stock_movement,
    )
)


# ---------------------------------------------------------------------------
# 6. Additional Product Operations
# ---------------------------------------------------------------------------

async def handle_get_product_details(db: AsyncSession, current_user: User, args: dict[str, Any]) -> dict[str, Any]:
    product_id = args.get("product_id")
    sku = args.get("sku")

    stmt = select(Product).where(Product.is_deleted == False)
    if product_id:
        stmt = stmt.where(Product.id == int(product_id))
    elif sku:
        stmt = stmt.where(Product.sku == sku.strip().upper())
    else:
        raise ValueError("Either product_id or sku must be provided.")

    res = await db.execute(stmt)
    product = res.scalar_one_or_none()
    if not product:
        raise ValueError("Product not found.")

    return {
        "id": product.id,
        "name": product.name,
        "sku": product.sku,
        "category": product.category,
        "price": float(product.price),
        "stock_quantity": product.stock_quantity,
        "reorder_level": product.reorder_level,
        "is_low_stock": product.stock_quantity <= product.reorder_level,
    }


tool_registry.register(
    ToolDefinition(
        name="get_product_details",
        description="Retrieve comprehensive details for a product by its ID or exact SKU.",
        parameters=[
            ToolParameter(name="product_id", type="integer", description="Product ID", required=False),
            ToolParameter(name="sku", type="string", description="Exact product SKU", required=False),
        ],
        is_mutation=False,
        handler=handle_get_product_details,
    )
)


async def handle_update_product(db: AsyncSession, current_user: User, args: dict[str, Any]) -> dict[str, Any]:
    product_id = args["product_id"]
    res = await db.execute(select(Product).where(Product.id == product_id, Product.is_deleted == False))
    product = res.scalar_one_or_none()
    if not product:
        raise ValueError(f"Product ID {product_id} not found.")

    if args.get("name"):
        product.name = args["name"].strip()
    if args.get("category"):
        product.category = args["category"].strip()
    if args.get("price") is not None:
        product.price = Decimal(str(args["price"]))
    if args.get("reorder_level") is not None:
        product.reorder_level = int(args["reorder_level"])

    if args.get("stock_quantity") is not None and int(args["stock_quantity"]) != product.stock_quantity:
        new_q = int(args["stock_quantity"])
        prev = product.stock_quantity
        diff = new_q - prev
        mv = StockMovement(
            product_id=product.id,
            user_id=current_user.id,
            movement_type="IN" if diff > 0 else "OUT",
            quantity=abs(diff),
            previous_stock=prev,
            new_stock=new_q,
            reason="Product stock updated via AI Assistant",
        )
        db.add(mv)
        product.stock_quantity = new_q

    await db.commit()
    await db.refresh(product)
    return {
        "success": True,
        "product_id": product.id,
        "name": product.name,
        "price": float(product.price),
        "stock_quantity": product.stock_quantity,
    }


def preview_update_product(args: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    title = f"Confirm Product Update (ID: {args.get('product_id')})"
    summary = f"Update details for Product ID {args.get('product_id')}."
    details = {k: v for k, v in args.items() if v is not None}
    return title, summary, details


tool_registry.register(
    ToolDefinition(
        name="update_product",
        description="Update an existing product's name, category, price, stock, or reorder level. Requires user confirmation.",
        parameters=[
            ToolParameter(name="product_id", type="integer", description="ID of product to update", required=True),
            ToolParameter(name="name", type="string", description="New product name", required=False),
            ToolParameter(name="category", type="string", description="New category", required=False),
            ToolParameter(name="price", type="number", description="New price", required=False),
            ToolParameter(name="stock_quantity", type="integer", description="New stock quantity", required=False),
            ToolParameter(name="reorder_level", type="integer", description="New safety reorder level", required=False),
        ],
        is_mutation=True,
        handler=handle_update_product,
        preview_generator=preview_update_product,
    )
)


async def handle_delete_product(db: AsyncSession, current_user: User, args: dict[str, Any]) -> dict[str, Any]:
    product_id = args["product_id"]
    res = await db.execute(select(Product).where(Product.id == product_id, Product.is_deleted == False))
    product = res.scalar_one_or_none()
    if not product:
        raise ValueError(f"Product ID {product_id} not found.")

    # Integrity check: prevent deletion if historical order items exist
    chk = await db.execute(select(func.count(OrderItem.id)).where(OrderItem.product_id == product_id))
    cnt = chk.scalar_one() or 0
    if cnt > 0:
        raise ValueError(f"Cannot delete product '{product.name}' because it is linked to {cnt} historical order items. Mark stock as 0 instead.")

    product.is_deleted = True
    await db.commit()
    return {"success": True, "message": f"Product '{product.name}' (SKU: {product.sku}) was soft-deleted."}


def preview_delete_product(args: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    title = "Confirm Product Deletion"
    summary = f"Soft-delete Product ID {args.get('product_id')}. This action hides the product from the catalog."
    details = {"Product ID": args.get("product_id")}
    return title, summary, details


tool_registry.register(
    ToolDefinition(
        name="delete_product",
        description="Soft delete a product from active catalog. Will be blocked if orders reference it. Requires user confirmation.",
        parameters=[
            ToolParameter(name="product_id", type="integer", description="Product ID to delete", required=True),
        ],
        is_mutation=True,
        handler=handle_delete_product,
        preview_generator=preview_delete_product,
    )
)


# ---------------------------------------------------------------------------
# 7. Additional Customer Operations
# ---------------------------------------------------------------------------

async def handle_get_customer_order_history(db: AsyncSession, current_user: User, args: dict[str, Any]) -> dict[str, Any]:
    customer_id = args["customer_id"]
    res = await db.execute(select(Customer).where(Customer.id == customer_id, Customer.is_deleted == False))
    customer = res.scalar_one_or_none()
    if not customer:
        raise ValueError(f"Customer ID {customer_id} not found.")

    orders_stmt = (
        select(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.product))
        .where(Order.customer_id == customer_id)
        .order_by(Order.created_at.desc())
    )
    orders_res = await db.execute(orders_stmt)
    orders = orders_res.scalars().all()

    return {
        "customer": customer.name,
        "phone": customer.phone,
        "orders_count": len(orders),
        "orders": [
            {
                "order_number": o.order_number,
                "total_amount": float(o.total_amount),
                "order_status": o.order_status,
                "payment_status": o.payment_status,
                "created_at": o.created_at.strftime("%Y-%m-%d"),
                "items": [
                    {
                        "product": it.product.name if it.product else "N/A",
                        "quantity": it.quantity,
                        "line_total": float(it.line_total),
                    }
                    for it in o.items
                ],
            }
            for o in orders
        ],
    }


tool_registry.register(
    ToolDefinition(
        name="get_customer_order_history",
        description="Retrieve the complete order and purchase history for a specific customer.",
        parameters=[
            ToolParameter(name="customer_id", type="integer", description="Customer ID", required=True),
        ],
        is_mutation=False,
        handler=handle_get_customer_order_history,
    )
)


# ---------------------------------------------------------------------------
# 8. Order Status Management & Restoration
# ---------------------------------------------------------------------------

async def handle_update_order_status(db: AsyncSession, current_user: User, args: dict[str, Any]) -> dict[str, Any]:
    order_id = args["order_id"]
    new_order_status = args.get("order_status")
    new_payment_status = args.get("payment_status")
    notes = args.get("notes")

    stmt = select(Order).options(selectinload(Order.items).selectinload(OrderItem.product)).where(Order.id == order_id)
    res = await db.execute(stmt)
    order = res.scalar_one_or_none()
    if not order:
        raise ValueError(f"Order ID {order_id} not found.")

    old_status = order.order_status

    if new_order_status and new_order_status != old_status:
        # A. Transitioning to Cancelled -> restore stock
        if new_order_status == "Cancelled" and old_status != "Cancelled":
            for it in order.items:
                product = it.product
                if product:
                    prev = product.stock_quantity
                    new_q = prev + it.quantity
                    product.stock_quantity = new_q
                    mv = StockMovement(
                        product_id=product.id,
                        user_id=current_user.id,
                        movement_type="IN",
                        quantity=it.quantity,
                        previous_stock=prev,
                        new_stock=new_q,
                        reason=f"Order #{order.order_number} cancelled via AI Assistant - stock restored",
                    )
                    db.add(mv)

        # B. Reactivating from Cancelled -> re-verify and deduct stock
        elif old_status == "Cancelled" and new_order_status != "Cancelled":
            for it in order.items:
                product = it.product
                if not product or product.stock_quantity < it.quantity:
                    pname = product.name if product else "Product"
                    avail = product.stock_quantity if product else 0
                    raise ValueError(f"Cannot reactivate order: insufficient stock for '{pname}'. Available: {avail}, needed: {it.quantity}.")

            for it in order.items:
                product = it.product
                prev = product.stock_quantity
                new_q = prev - it.quantity
                product.stock_quantity = new_q
                mv = StockMovement(
                    product_id=product.id,
                    user_id=current_user.id,
                    movement_type="OUT",
                    quantity=it.quantity,
                    previous_stock=prev,
                    new_stock=new_q,
                    reason=f"Order #{order.order_number} reactivated via AI Assistant - stock deducted",
                )
                db.add(mv)

        order.order_status = new_order_status

    if new_payment_status:
        order.payment_status = new_payment_status
    if notes:
        order.notes = notes

    await db.commit()
    await db.refresh(order)

    return {
        "success": True,
        "order_id": order.id,
        "order_number": order.order_number,
        "order_status": order.order_status,
        "payment_status": order.payment_status,
    }


def preview_update_order_status(args: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    title = f"Confirm Order Status Change (ID: {args.get('order_id')})"
    summary = f"Update Order ID {args.get('order_id')} to Status '{args.get('order_status') or 'Keep'}' and Payment '{args.get('payment_status') or 'Keep'}'."
    details = {
        "Order ID": args.get("order_id"),
        "Target Order Status": args.get("order_status") or "Unchanged",
        "Target Payment Status": args.get("payment_status") or "Unchanged",
        "Notes": args.get("notes") or "None",
    }
    return title, summary, details


tool_registry.register(
    ToolDefinition(
        name="update_order_status",
        description="Update order status (Pending, Processing, Shipped, Delivered, Cancelled) or payment status. Handles automatic stock restoration when cancelled. Requires user confirmation.",
        parameters=[
            ToolParameter(name="order_id", type="integer", description="Order ID", required=True),
            ToolParameter(name="order_status", type="string", description="New order status", required=False, enum=["Pending", "Processing", "Shipped", "Delivered", "Cancelled"]),
            ToolParameter(name="payment_status", type="string", description="New payment status", required=False, enum=["Unpaid", "Partial", "Paid"]),
            ToolParameter(name="notes", type="string", description="Order notes", required=False),
        ],
        is_mutation=True,
        handler=handle_update_order_status,
        preview_generator=preview_update_order_status,
    )
)


# ---------------------------------------------------------------------------
# 9. Inventory Movements Log Tool
# ---------------------------------------------------------------------------

async def handle_list_inventory_movements(db: AsyncSession, current_user: User, args: dict[str, Any]) -> dict[str, Any]:
    stmt = (
        select(StockMovement)
        .options(selectinload(StockMovement.product), selectinload(StockMovement.user))
        .order_by(StockMovement.created_at.desc())
        .limit(args.get("limit", 15))
    )
    if args.get("movement_type"):
        stmt = stmt.where(StockMovement.movement_type == args["movement_type"].upper())

    res = await db.execute(stmt)
    movements = res.scalars().all()
    return {
        "count": len(movements),
        "movements": [
            {
                "product": m.product.name if m.product else "Unknown",
                "sku": m.product.sku if m.product else "N/A",
                "type": m.movement_type,
                "quantity": m.quantity,
                "previous_stock": m.previous_stock,
                "new_stock": m.new_stock,
                "reason": m.reason,
                "user": m.user.full_name if m.user else "System",
                "created_at": m.created_at.strftime("%Y-%m-%d %H:%M"),
            }
            for m in movements
        ],
    }


tool_registry.register(
    ToolDefinition(
        name="list_inventory_movements",
        description="Retrieve recent stock movement audit history (IN, OUT, ADJUSTMENT).",
        parameters=[
            ToolParameter(name="movement_type", type="string", description="Filter by type (IN, OUT, ADJUSTMENT)", required=False, enum=["IN", "OUT", "ADJUSTMENT"]),
            ToolParameter(name="limit", type="integer", description="Max records (default 15)", required=False, default=15),
        ],
        is_mutation=False,
        handler=handle_list_inventory_movements,
    )
)


# ---------------------------------------------------------------------------
# 10. Advanced Query Tools: Existence, Date Sales, Product Sales & Totals
# ---------------------------------------------------------------------------

DHAKA_TZ = timezone(timedelta(hours=6))

def parse_business_date_range(date_str: str | None) -> tuple[datetime, datetime, str]:
    now_dhaka = datetime.now(DHAKA_TZ)
    target_date = now_dhaka.date()
    label = "Today"

    if not date_str or date_str.lower() in ["today", "আজ", "আজকে"]:
        target_date = now_dhaka.date()
        label = f"Today ({target_date.strftime('%d %B %Y')})"
    elif date_str.lower() in ["yesterday", "গতকাল"]:
        target_date = now_dhaka.date() - timedelta(days=1)
        label = f"Yesterday ({target_date.strftime('%d %B %Y')})"
    else:
        cleaned = date_str.strip().lower()
        cleaned = cleaned.replace("th", "").replace("st", "").replace("nd", "").replace("rd", "")
        m_iso = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", cleaned)
        if m_iso:
            target_date = date(int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3)))
            label = target_date.strftime("%d %B %Y")
        else:
            month_names = {
                "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
                "apr": 4, "april": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
                "aug": 8, "august": 8, "sep": 9, "september": 9, "oct": 10, "october": 10,
                "nov": 11, "november": 11, "dec": 12, "december": 12,
            }
            found = False
            for m_name, m_num in month_names.items():
                if m_name in cleaned:
                    m_day = re.search(r"(\d{1,2})", cleaned)
                    if m_day:
                        day = int(m_day.group(1))
                        year = now_dhaka.year
                        m_year = re.search(r"(\d{4})", cleaned)
                        if m_year:
                            year = int(m_year.group(1))
                        target_date = date(year, m_num, day)
                        label = target_date.strftime("%d %B %Y")
                        found = True
                        break
            if not found:
                target_date = now_dhaka.date()
                label = target_date.strftime("%d %B %Y")

    start_dt = datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0, tzinfo=DHAKA_TZ)
    end_dt = start_dt + timedelta(days=1)
    return start_dt.astimezone(timezone.utc), end_dt.astimezone(timezone.utc), label


async def handle_get_customer_existence(db: AsyncSession, current_user: User, args: dict[str, Any]) -> dict[str, Any]:
    query_str = args.get("query", "").strip()
    if not query_str:
        return {"exists": False, "count": 0, "message": "No customer name provided."}

    stmt = (
        select(Customer, func.count(Order.id).label("orders_count"))
        .outerjoin(Order, (Order.customer_id == Customer.id))
        .where(Customer.is_deleted == False, Customer.name.ilike(f"%{query_str}%"))
        .group_by(Customer.id)
    )
    res = await db.execute(stmt)
    rows = res.all()

    if not rows:
        return {
            "exists": False,
            "count": 0,
            "query": query_str,
            "message": f"No customer found matching '{query_str}'.",
        }

    if len(rows) == 1:
        c, ord_count = rows[0]
        return {
            "exists": True,
            "count": 1,
            "query": query_str,
            "customer": {
                "id": c.id,
                "name": c.name,
                "phone": c.phone,
                "email": c.email,
                "address": c.address,
                "orders_count": ord_count or 0,
            },
        }

    return {
        "exists": True,
        "count": len(rows),
        "query": query_str,
        "is_ambiguous": True,
        "matches": [
            {
                "id": c.id,
                "name": c.name,
                "phone": c.phone,
                "orders_count": ord_count or 0,
            }
            for c, ord_count in rows
        ],
    }


tool_registry.register(
    ToolDefinition(
        name="get_customer_existence",
        description="Check if a customer exists by name, returning match confirmation, customer details, or disambiguation list.",
        parameters=[
            ToolParameter(name="query", type="string", description="Customer name to check (e.g. 'Rahim Ahmed')", required=True),
        ],
        is_mutation=False,
        handler=handle_get_customer_existence,
    )
)


async def handle_get_customer_order_totals(db: AsyncSession, current_user: User, args: dict[str, Any]) -> dict[str, Any]:
    customer_id = args.get("customer_id")
    customer_name = args.get("customer_name")

    if not customer_id and not customer_name:
        raise ValueError("Either customer_id or customer_name must be provided.")

    customer = None
    if customer_id:
        res = await db.execute(select(Customer).where(Customer.id == int(customer_id), Customer.is_deleted == False))
        customer = res.scalar_one_or_none()
    elif customer_name:
        res = await db.execute(select(Customer).where(Customer.name.ilike(f"%{customer_name.strip()}%"), Customer.is_deleted == False))
        matches = res.scalars().all()
        if not matches:
            return {"found": False, "message": f"No customer found matching '{customer_name}'."}
        if len(matches) > 1:
            return {
                "found": True,
                "is_ambiguous": True,
                "message": f"Multiple customers found matching '{customer_name}'. Please clarify which customer you mean.",
                "matches": [{"id": m.id, "name": m.name, "phone": m.phone} for m in matches],
            }
        customer = matches[0]

    if not customer:
        return {"found": False, "message": "Customer not found."}

    orders_res = await db.execute(
        select(Order).where(Order.customer_id == customer.id).order_by(Order.created_at.desc())
    )
    orders = orders_res.scalars().all()

    total_amount = Decimal("0.00")
    delivered_paid_amount = Decimal("0.00")
    status_counts: dict[str, int] = {}

    for o in orders:
        status_counts[o.order_status] = status_counts.get(o.order_status, 0) + 1
        if o.order_status != "Cancelled":
            total_amount += o.total_amount
        if o.order_status == "Delivered" and o.payment_status == "Paid":
            delivered_paid_amount += o.total_amount

    return {
        "found": True,
        "customer_id": customer.id,
        "customer_name": customer.name,
        "customer_phone": customer.phone,
        "total_orders": len(orders),
        "total_amount_tk": float(total_amount),
        "delivered_paid_amount_tk": float(delivered_paid_amount),
        "status_breakdown": status_counts,
    }


tool_registry.register(
    ToolDefinition(
        name="get_customer_order_totals",
        description="Calculate total monetary order value, total orders, and status breakdown for a customer.",
        parameters=[
            ToolParameter(name="customer_id", type="integer", description="Customer ID", required=False),
            ToolParameter(name="customer_name", type="string", description="Customer name", required=False),
        ],
        is_mutation=False,
        handler=handle_get_customer_order_totals,
    )
)


async def handle_get_sales_by_date(db: AsyncSession, current_user: User, args: dict[str, Any]) -> dict[str, Any]:
    date_str = args.get("date_str", "today")
    start_utc, end_utc, label = parse_business_date_range(date_str)

    stmt = select(Order).where(Order.created_at >= start_utc, Order.created_at < end_utc)
    res = await db.execute(stmt)
    orders = res.scalars().all()

    total_sales_tk = Decimal("0.00")
    delivered_paid_count = 0
    all_valid_total = Decimal("0.00")

    for o in orders:
        if o.order_status != "Cancelled":
            all_valid_total += o.total_amount
        if o.order_status == "Delivered" and o.payment_status == "Paid":
            total_sales_tk += o.total_amount
            delivered_paid_count += 1

    return {
        "date_label": label,
        "date_query": date_str,
        "total_sales_tk": float(total_sales_tk),
        "total_orders": len(orders),
        "delivered_paid_orders": delivered_paid_count,
        "all_valid_orders_total_tk": float(all_valid_total),
        "rule": "Strictly Delivered and Paid orders only",
        "currency": "৳",
    }


tool_registry.register(
    ToolDefinition(
        name="get_sales_by_date",
        description="Retrieve total sales revenue and orders count for a specific business date (today, yesterday, or specific date).",
        parameters=[
            ToolParameter(name="date_str", type="string", description="Date: 'today', 'yesterday', 'YYYY-MM-DD', or 'Month Day'", required=False, default="today"),
        ],
        is_mutation=False,
        handler=handle_get_sales_by_date,
    )
)


async def handle_get_product_sales(db: AsyncSession, current_user: User, args: dict[str, Any]) -> dict[str, Any]:
    product_name = args.get("product_name")
    product_id = args.get("product_id")
    date_str = args.get("date_str")

    product = None
    if product_id:
        res = await db.execute(select(Product).where(Product.id == int(product_id), Product.is_deleted == False))
        product = res.scalar_one_or_none()
    elif product_name:
        res = await db.execute(select(Product).where(Product.name.ilike(f"%{product_name.strip()}%"), Product.is_deleted == False))
        matches = res.scalars().all()
        if not matches:
            return {"found": False, "message": f"No product found matching '{product_name}'."}
        if len(matches) > 1:
            return {
                "found": True,
                "is_ambiguous": True,
                "message": f"Multiple products match '{product_name}'. Please clarify which product you mean.",
                "matches": [{"id": p.id, "name": p.name, "sku": p.sku} for p in matches],
            }
        product = matches[0]

    if not product:
        return {"found": False, "message": "Product not found."}

    stmt = (
        select(OrderItem, Order)
        .join(Order, Order.id == OrderItem.order_id)
        .where(OrderItem.product_id == product.id, Order.order_status != "Cancelled")
    )

    date_label = "All Time"
    if date_str and date_str.lower() != "all":
        start_utc, end_utc, date_label = parse_business_date_range(date_str)
        stmt = stmt.where(Order.created_at >= start_utc, Order.created_at < end_utc)

    res = await db.execute(stmt)
    rows = res.all()

    total_qty = sum(item.quantity for item, order in rows)
    total_revenue = sum(float(item.line_total) for item, order in rows)

    return {
        "found": True,
        "product_id": product.id,
        "product_name": product.name,
        "sku": product.sku,
        "current_stock": product.stock_quantity,
        "price": float(product.price),
        "date_period": date_label,
        "quantity_sold": total_qty,
        "total_sales_tk": total_revenue,
        "orders_count": len(rows),
        "currency": "৳",
    }


tool_registry.register(
    ToolDefinition(
        name="get_product_sales",
        description="Retrieve sales quantity and monetary total for a specific product for a given date or period.",
        parameters=[
            ToolParameter(name="product_name", type="string", description="Name of the product", required=False),
            ToolParameter(name="product_id", type="integer", description="Product ID", required=False),
            ToolParameter(name="date_str", type="string", description="Date: 'today', 'yesterday', 'all', or date string", required=False, default="today"),
        ],
        is_mutation=False,
        handler=handle_get_product_sales,
    )
)


# ---------------------------------------------------------------------------
# 11. Business Intelligence & Ranking Tools
# ---------------------------------------------------------------------------

async def handle_get_top_sales_date(db: AsyncSession, current_user: User, args: dict[str, Any]) -> dict[str, Any]:
    period = args.get("period", "all_time")
    now_dhaka = datetime.now(DHAKA_TZ)
    stmt = select(Order).where(Order.order_status == "Delivered", Order.payment_status == "Paid")

    date_filter_label = "All Time"
    if period in ["this_month", "current_month", "এই মাস", "এই মাসে"]:
        start_month = datetime(now_dhaka.year, now_dhaka.month, 1, 0, 0, 0, tzinfo=DHAKA_TZ).astimezone(timezone.utc)
        stmt = stmt.where(Order.created_at >= start_month)
        date_filter_label = f"This Month ({now_dhaka.strftime('%B %Y')})"
    elif period in ["this_year", "current_year", "এই বছর"]:
        start_year = datetime(now_dhaka.year, 1, 1, 0, 0, 0, tzinfo=DHAKA_TZ).astimezone(timezone.utc)
        stmt = stmt.where(Order.created_at >= start_year)
        date_filter_label = f"This Year ({now_dhaka.year})"

    res = await db.execute(stmt)
    orders = res.scalars().all()

    if not orders:
        return {
            "found": False,
            "period": date_filter_label,
            "message": "No delivered and paid sales records found for this period.",
        }

    daily_sales: dict[date, Decimal] = {}
    daily_orders: dict[date, int] = {}
    for o in orders:
        if o.created_at:
            o_dt = o.created_at
            if o_dt.tzinfo is None:
                o_dt = o_dt.replace(tzinfo=timezone.utc)
            d_date = o_dt.astimezone(DHAKA_TZ).date()
            daily_sales[d_date] = daily_sales.get(d_date, Decimal("0.00")) + o.total_amount
            daily_orders[d_date] = daily_orders.get(d_date, 0) + 1

    if not daily_sales:
        return {
            "found": False,
            "period": date_filter_label,
            "message": "No sales recorded.",
        }

    top_date = max(daily_sales, key=lambda d: daily_sales[d])
    top_revenue = float(daily_sales[top_date])
    top_order_count = daily_orders[top_date]

    return {
        "found": True,
        "top_date": top_date.strftime("%Y-%m-%d"),
        "top_date_formatted": top_date.strftime("%d %B %Y"),
        "total_sales_tk": top_revenue,
        "orders_count": top_order_count,
        "period": date_filter_label,
        "currency": "৳",
        "rule": "Strictly Delivered and Paid orders only",
    }


tool_registry.register(
    ToolDefinition(
        name="get_top_sales_date",
        description="Retrieve the specific historical calendar date that achieved the highest total sales revenue.",
        parameters=[
            ToolParameter(name="period", type="string", description="Time period filter: 'all_time', 'this_month', 'this_year'", required=False, default="all_time"),
        ],
        is_mutation=False,
        handler=handle_get_top_sales_date,
    )
)


async def handle_get_top_selling_products(db: AsyncSession, current_user: User, args: dict[str, Any]) -> dict[str, Any]:
    limit = int(args.get("limit", 5) or 5)
    period = args.get("period", "all_time")
    now_dhaka = datetime.now(DHAKA_TZ)

    stmt = (
        select(
            Product.id,
            Product.name,
            Product.sku,
            Product.price,
            func.sum(OrderItem.quantity).label("units_sold"),
            func.sum(OrderItem.line_total).label("total_revenue"),
        )
        .join(OrderItem, OrderItem.product_id == Product.id)
        .join(Order, Order.id == OrderItem.order_id)
        .where(Product.is_deleted == False, Order.order_status != "Cancelled")
    )

    period_label = "All Time"
    if period in ["this_month", "current_month", "এই মাস", "এই মাসে"]:
        start_month = datetime(now_dhaka.year, now_dhaka.month, 1, 0, 0, 0, tzinfo=DHAKA_TZ).astimezone(timezone.utc)
        stmt = stmt.where(Order.created_at >= start_month)
        period_label = f"This Month ({now_dhaka.strftime('%B %Y')})"
    elif period in ["today", "আজ", "আজকে"]:
        start_today = datetime(now_dhaka.year, now_dhaka.month, now_dhaka.day, 0, 0, 0, tzinfo=DHAKA_TZ).astimezone(timezone.utc)
        stmt = stmt.where(Order.created_at >= start_today)
        period_label = f"Today ({now_dhaka.strftime('%d %B %Y')})"

    stmt = (
        stmt.group_by(Product.id, Product.name, Product.sku, Product.price)
        .order_by(func.sum(OrderItem.quantity).desc())
        .limit(limit)
    )

    res = await db.execute(stmt)
    rows = res.all()

    top_products = []
    for idx, (p_id, p_name, p_sku, p_price, units_sold, total_rev) in enumerate(rows, 1):
        top_products.append({
            "rank": idx,
            "id": p_id,
            "name": p_name,
            "sku": p_sku,
            "price": float(p_price),
            "units_sold": int(units_sold or 0),
            "total_revenue_tk": float(total_rev or 0.0),
        })

    return {
        "found": len(top_products) > 0,
        "count": len(top_products),
        "period": period_label,
        "products": top_products,
        "top_product": top_products[0] if top_products else None,
        "currency": "৳",
    }


tool_registry.register(
    ToolDefinition(
        name="get_top_selling_products",
        description="Retrieve top selling products ranked by units sold and revenue over a given period (this month, today, or all time).",
        parameters=[
            ToolParameter(name="period", type="string", description="Time period: 'this_month', 'today', 'all_time'", required=False, default="all_time"),
            ToolParameter(name="limit", type="integer", description="Number of products to return (default 5)", required=False, default=5),
        ],
        is_mutation=False,
        handler=handle_get_top_selling_products,
    )
)


async def handle_get_top_customers(db: AsyncSession, current_user: User, args: dict[str, Any]) -> dict[str, Any]:
    limit = int(args.get("limit", 5) or 5)

    stmt = (
        select(
            Customer.id,
            Customer.name,
            Customer.phone,
            func.count(Order.id).label("total_orders"),
            func.sum(Order.total_amount).label("total_spent"),
        )
        .join(Order, Order.customer_id == Customer.id)
        .where(Customer.is_deleted == False, Order.order_status != "Cancelled")
        .group_by(Customer.id, Customer.name, Customer.phone)
        .order_by(func.sum(Order.total_amount).desc())
        .limit(limit)
    )

    res = await db.execute(stmt)
    rows = res.all()

    top_customers = []
    for idx, (c_id, c_name, c_phone, total_orders, total_spent) in enumerate(rows, 1):
        top_customers.append({
            "rank": idx,
            "id": c_id,
            "name": c_name,
            "phone": c_phone,
            "total_orders": int(total_orders or 0),
            "total_spent_tk": float(total_spent or 0.0),
        })

    return {
        "found": len(top_customers) > 0,
        "count": len(top_customers),
        "customers": top_customers,
        "top_customer": top_customers[0] if top_customers else None,
        "currency": "৳",
    }


tool_registry.register(
    ToolDefinition(
        name="get_top_customers",
        description="Retrieve the top customer accounts ranked by total cumulative order spending.",
        parameters=[
            ToolParameter(name="limit", type="integer", description="Number of top customers to return (default 5)", required=False, default=5),
        ],
        is_mutation=False,
        handler=handle_get_top_customers,
    )
)


async def handle_compare_sales_dates(db: AsyncSession, current_user: User, args: dict[str, Any]) -> dict[str, Any]:
    date_1_str = args.get("date_1", "today")
    date_2_str = args.get("date_2", "yesterday")

    data_1 = await handle_get_sales_by_date(db, current_user, {"date_str": date_1_str})
    data_2 = await handle_get_sales_by_date(db, current_user, {"date_str": date_2_str})

    sales_1 = float(data_1.get("total_sales_tk", 0.0))
    sales_2 = float(data_2.get("total_sales_tk", 0.0))
    orders_1 = int(data_1.get("delivered_paid_orders", 0))
    orders_2 = int(data_2.get("delivered_paid_orders", 0))

    diff_sales = sales_1 - sales_2
    pct_change = None
    if sales_2 > 0:
        pct_change = round(((sales_1 - sales_2) / sales_2) * 100, 2)

    diff_orders = orders_1 - orders_2

    return {
        "date_1": {
            "label": data_1.get("date_label"),
            "sales_tk": sales_1,
            "orders": orders_1,
        },
        "date_2": {
            "label": data_2.get("date_label"),
            "sales_tk": sales_2,
            "orders": orders_2,
        },
        "difference_tk": diff_sales,
        "difference_orders": diff_orders,
        "percentage_change": pct_change,
        "is_higher": diff_sales > 0,
        "is_lower": diff_sales < 0,
        "is_equal": diff_sales == 0,
        "currency": "৳",
    }


tool_registry.register(
    ToolDefinition(
        name="compare_sales_dates",
        description="Compare sales revenue and orders count between two dates or periods (e.g. today vs yesterday).",
        parameters=[
            ToolParameter(name="date_1", type="string", description="First date (e.g. 'today')", required=False, default="today"),
            ToolParameter(name="date_2", type="string", description="Second date (e.g. 'yesterday')", required=False, default="yesterday"),
        ],
        is_mutation=False,
        handler=handle_compare_sales_dates,
    )
)
