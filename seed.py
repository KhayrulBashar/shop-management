"""
Shop Management System - Presentation Seed Script
Populates the database with demo products, customers, stock movements, and orders.
Run with: python seed.py
"""
import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import secrets
from sqlalchemy import func, select
from app.core.database import AsyncSessionLocal, engine, Base
from app.core.security import get_password_hash
from app.models.user import User
from app.models.product import Product
from app.models.customer import Customer
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.stock_movement import StockMovement


async def run_seed():
    print("=====================================================")
    print("   Starting Shop Management System Demo Seeder...   ")
    print("=====================================================")

    # Ensure tables exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        # 1. Admin user check or creation
        user_res = await session.execute(select(User).limit(1))
        admin = user_res.scalar_one_or_none()
        if not admin:
            print("[*] Creating Default Administrator (admin@shop.com / Admin123456)...")
            admin = User(
                full_name="Mahmudul Hasan (Admin)",
                email="admin@shop.com",
                hashed_password=get_password_hash("Admin123456"),
                is_admin=True,
            )
            session.add(admin)
            await session.flush()
        else:
            print(f"[*] Existing Administrator found: {admin.email}")

        # 2. Check if products already exist
        prod_count_res = await session.execute(select(func.count(Product.id)))
        if (prod_count_res.scalar_one() or 0) > 0:
            print("[!] Products already exist in database. Skipping duplicate seed.")
            return

        print("[+] Adding Realistic Product Catalog...")
        demo_products = [
            # High-end Electronics
            {"name": "Logitech MX Master 3S Wireless Mouse", "sku": "ELEC-LOG-001", "category": "Electronics", "price": Decimal("11500.00"), "stock_quantity": 18, "reorder_level": 5},
            {"name": "Keychron K2 V2 Wireless Mechanical Keyboard", "sku": "ELEC-KEY-002", "category": "Electronics", "price": Decimal("9800.00"), "stock_quantity": 4, "reorder_level": 5}, # Low Stock!
            {"name": "Anker 737 Power Bank 24,000mAh 140W", "sku": "ELEC-ANK-003", "category": "Electronics", "price": Decimal("14200.00"), "stock_quantity": 12, "reorder_level": 6},
            {"name": "Sony WH-1000XM5 Noise Canceling Headphones", "sku": "ELEC-SNY-004", "category": "Electronics", "price": Decimal("38500.00"), "stock_quantity": 2, "reorder_level": 4}, # Low Stock!
            {"name": "Apple 20W USB-C Power Adapter", "sku": "ELEC-APL-005", "category": "Electronics", "price": Decimal("2450.00"), "stock_quantity": 45, "reorder_level": 10},

            # Apparel & Fashion
            {"name": "Premium Cotton Oxford Slim-fit Shirt", "sku": "APPL-SHT-010", "category": "Apparel", "price": Decimal("2250.00"), "stock_quantity": 30, "reorder_level": 8},
            {"name": "Classic Indigo Stretch Denim Jeans", "sku": "APPL-JNS-011", "category": "Apparel", "price": Decimal("3200.00"), "stock_quantity": 22, "reorder_level": 5},
            {"name": "Genuine Leather Formal Dress Belt", "sku": "APPL-BLT-012", "category": "Apparel", "price": Decimal("1650.00"), "stock_quantity": 3, "reorder_level": 5}, # Low Stock!
            {"name": "Minimalist Breathable Running Hoodie", "sku": "APPL-HOD-013", "category": "Apparel", "price": Decimal("2850.00"), "stock_quantity": 14, "reorder_level": 5},

            # Accessories & Lifestyle
            {"name": "Bellroy Slim Leather Sleeve Wallet", "sku": "ACC-WAL-020", "category": "Accessories", "price": Decimal("5400.00"), "stock_quantity": 8, "reorder_level": 4},
            {"name": "Hydro Flask 32oz Insulated Stainless Steel", "sku": "ACC-BOT-021", "category": "Accessories", "price": Decimal("3600.00"), "stock_quantity": 1, "reorder_level": 5}, # Low Stock / Danger!
            {"name": "Water-resistant Laptop Backpack 20L", "sku": "ACC-BAK-022", "category": "Accessories", "price": Decimal("4800.00"), "stock_quantity": 16, "reorder_level": 5},

            # Home & Office
            {"name": "Ergonomic Memory Foam Seat Cushion", "sku": "HOME-CSH-030", "category": "Home & Office", "price": Decimal("2100.00"), "stock_quantity": 25, "reorder_level": 6},
            {"name": "LED Smart Desk Lamp with Wireless Charger", "sku": "HOME-LMP-031", "category": "Home & Office", "price": Decimal("3400.00"), "stock_quantity": 0, "reorder_level": 5}, # Out of Stock!
        ]

        created_products = []
        for pdata in demo_products:
            prod = Product(**pdata)
            session.add(prod)
            created_products.append(prod)
        await session.flush()

        # Log initial stock movement for each product
        for prod in created_products:
            if prod.stock_quantity > 0:
                m = StockMovement(
                    product_id=prod.id,
                    user_id=admin.id,
                    movement_type="IN",
                    quantity=prod.stock_quantity,
                    previous_stock=0,
                    new_stock=prod.stock_quantity,
                    reason="Initial Demo Inventory Shipment",
                )
                session.add(m)

        print("[+] Adding Demo Customers...")
        demo_customers = [
            {"name": "Tanvir Ahmed", "phone": "+8801711223344", "email": "tanvir.ahmed@example.com", "address": "House 42, Road 11, Banani, Dhaka", "notes": "VIP Corporate buyer"},
            {"name": "Sabrina Rahman", "phone": "+8801819556677", "email": "sabrina.r@example.com", "address": "Flat B4, Sector 7, Uttara, Dhaka", "notes": "Regular online customer"},
            {"name": "Farhan Kabir", "phone": "+8801912998877", "email": "farhan.k@example.com", "address": "GEC Circle, Nasirabad, Chattogram", "notes": "Prefers express courier delivery"},
            {"name": "Nusrat Jahan", "phone": "+8801610443322", "email": "nusrat.jahan@example.com", "address": "Zindabazar, Sylhet", "notes": "Repeat customer for apparel"},
            {"name": "Kamrul Islam", "phone": "+8801515887766", "email": "kamrul.dev@example.com", "address": "Dhanmondi 27, Dhaka", "notes": "Tech accessories enthusiast"},
        ]

        created_customers = []
        for cdata in demo_customers:
            cust = Customer(**cdata)
            session.add(cust)
            created_customers.append(cust)
        await session.flush()

        print("[+] Generating Demo Orders & Movements...")
        order_templates = [
            {
                "customer": created_customers[0],
                "items": [(created_products[0], 1), (created_products[2], 1)],  # Mouse + Powerbank
                "order_status": "Delivered",
                "payment_status": "Paid",
                "notes": "Delivered on time via express courier.",
                "days_ago": 4,
            },
            {
                "customer": created_customers[1],
                "items": [(created_products[5], 2), (created_products[6], 1)],  # Shirt x2 + Jeans
                "order_status": "Delivered",
                "payment_status": "Paid",
                "notes": "Customer confirmed fitting and quality.",
                "days_ago": 3,
            },
            {
                "customer": created_customers[2],
                "items": [(created_products[1], 1)],  # Keyboard
                "order_status": "Shipped",
                "payment_status": "Paid",
                "notes": "In transit to Chattogram hub via Sundarban Courier.",
                "days_ago": 2,
            },
            {
                "customer": created_customers[3],
                "items": [(created_products[4], 2), (created_products[9], 1)],  # 20W charger x2 + Bellroy wallet
                "order_status": "Processing",
                "payment_status": "Partial",
                "notes": "50% advance received via bKash.",
                "days_ago": 1,
            },
            {
                "customer": created_customers[4],
                "items": [(created_products[3], 1)],  # Sony headphones
                "order_status": "Pending",
                "payment_status": "Unpaid",
                "notes": "Customer requested cash on delivery.",
                "days_ago": 0,
            },
        ]

        for ot in order_templates:
            order_date = datetime.now(timezone.utc) - timedelta(days=ot["days_ago"])
            order_num = f"ORD-{order_date.strftime('%Y%m%d')}-{secrets.token_hex(2).upper()}"
            grand_total = Decimal("0.00")
            db_items = []

            for prod, qty in ot["items"]:
                unit_price = prod.price
                line_total = unit_price * Decimal(qty)
                grand_total += line_total
                db_items.append(
                    OrderItem(
                        product_id=prod.id,
                        quantity=qty,
                        unit_price=unit_price,
                        line_total=line_total,
                        created_at=order_date,
                    )
                )

                # Log StockMovement OUT for placed order
                m = StockMovement(
                    product_id=prod.id,
                    user_id=admin.id,
                    movement_type="OUT",
                    quantity=qty,
                    previous_stock=prod.stock_quantity + qty,
                    new_stock=prod.stock_quantity,
                    reason=f"Order #{order_num} fulfilled",
                    created_at=order_date,
                )
                session.add(m)

            ord_record = Order(
                order_number=order_num,
                customer_id=ot["customer"].id,
                total_amount=grand_total,
                order_status=ot["order_status"],
                payment_status=ot["payment_status"],
                notes=ot["notes"],
                created_at=order_date,
                updated_at=order_date,
                items=db_items,
            )
            session.add(ord_record)

        await session.commit()
        print("=====================================================")
        print("[SUCCESS] Demo Data Seeded Successfully!")
        print("   - 1 Administrator account (admin@shop.com / Admin123456)")
        print(f"   - {len(created_products)} Products across 4 categories")
        print(f"   - {len(created_customers)} Customers with contact profiles")
        print(f"   - {len(order_templates)} Real Orders with stock movements")
        print("=====================================================")


if __name__ == "__main__":
    asyncio.run(run_seed())
