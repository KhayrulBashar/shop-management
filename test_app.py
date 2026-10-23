"""
Automated Verification Suite for Shop Management System
Tests all 5 core features, authentication, stock movements, and templates.
"""
import asyncio
from httpx import AsyncClient, ASGITransport
from app.main import app


async def run_tests():
    print("=============================================================")
    print("   Starting Automated Shop Management System Test Suite     ")
    print("=============================================================")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Health check
        res = await client.get("/api/health")
        assert res.status_code == 200, f"Health check failed: {res.text}"
        print("[PASS] 1. /api/health -> 200 OK")

        # 2. Auth status
        res = await client.get("/api/auth/status")
        assert res.status_code == 200
        status_data = res.json()
        assert status_data["has_admin"] is True, "Admin should be detected"
        print(f"[PASS] 2. /api/auth/status -> has_admin={status_data['has_admin']}")

        # 3. Test Admin Login
        login_payload = {"email": "admin@shop.com", "password": "Admin123456"}
        res = await client.post("/api/auth/login", json=login_payload)
        assert res.status_code == 200, f"Login failed: {res.text}"
        assert "access_token" in client.cookies, "HttpOnly cookie access_token not set"
        print("[PASS] 3. /api/auth/login -> 200 OK & HttpOnly access_token cookie set")

        # 4. Dashboard Stats
        res = await client.get("/api/dashboard/stats")
        assert res.status_code == 200, f"Stats failed: {res.text}"
        stats = res.json()
        print(f"[PASS] 4. /api/dashboard/stats -> Products: {stats['total_products']}, Customers: {stats['total_customers']}, Orders: {stats['total_orders']}, Revenue: {stats['total_sales']}")

        # 5. Low stock endpoint
        res = await client.get("/api/dashboard/low-stock")
        assert res.status_code == 200
        low_items = res.json()
        print(f"[PASS] 5. /api/dashboard/low-stock -> Found {len(low_items)} low stock items")

        # 6. Product Management: Create & Duplicate SKU check
        test_sku = "TEST-MOUSE-999"
        prod_payload = {
            "name": "RGB Wireless Gaming Mouse",
            "sku": test_sku,
            "category": "Gaming",
            "price": 3500.00,
            "stock_quantity": 20,
            "reorder_level": 5,
        }
        res = await client.post("/api/products", json=prod_payload)
        assert res.status_code in [201, 400]
        if res.status_code == 201:
            prod_data = res.json()
            prod_id = prod_data["id"]
            print(f"[PASS] 6a. /api/products (POST) -> Created product ID: {prod_id}")
            
            # Duplicate SKU check
            dup_res = await client.post("/api/products", json=prod_payload)
            assert dup_res.status_code == 400
            print("[PASS] 6b. Duplicate SKU rejected with 400 Bad Request")
        else:
            print("[INFO] Test product already exists from prior test.")

        # 7. Customer Management: Create & List
        cust_payload = {
            "name": "Rafiqul Islam",
            "phone": "+8801799887766",
            "email": "rafiq.test@example.com",
            "address": "Mirpur 10, Dhaka",
            "notes": "Prefers evening courier",
        }
        res = await client.post("/api/customers", json=cust_payload)
        assert res.status_code == 201
        created_cust = res.json()
        cust_id = created_cust["id"]
        print(f"[PASS] 7. /api/customers (POST) -> Created customer ID: {cust_id}")

        # 8. Order Management: Create Order & Check Stock Deduction
        # Fetch product to verify initial stock
        prod_res = await client.get("/api/products?search=Logitech")
        prods = prod_res.json()["items"]
        assert len(prods) > 0
        target_prod = prods[0]
        initial_stock = target_prod["stock_quantity"]

        order_payload = {
            "customer_id": cust_id,
            "order_status": "Processing",
            "payment_status": "Partial",
            "notes": "Express delivery requested",
            "items": [{"product_id": target_prod["id"], "quantity": 2}],
        }
        order_res = await client.post("/api/orders", json=order_payload)
        assert order_res.status_code == 201, f"Order creation failed: {order_res.text}"
        order_data = order_res.json()
        order_id = order_data["id"]
        print(f"[PASS] 8a. /api/orders (POST) -> Created order #{order_data['order_number']}, Total: Tk.{order_data['total_amount']}")

        # Verify stock decreased by 2
        chk_prod_res = await client.get(f"/api/products/{target_prod['id']}")
        updated_stock = chk_prod_res.json()["stock_quantity"]
        assert updated_stock == initial_stock - 2, f"Expected {initial_stock - 2}, got {updated_stock}"
        print(f"[PASS] 8b. Automated Stock Deduction verified: {initial_stock} -> {updated_stock}")

        # 9. Order Cancellation -> Stock Restoration
        cancel_res = await client.patch(f"/api/orders/{order_id}/status", json={"order_status": "Cancelled"})
        assert cancel_res.status_code == 200
        restored_prod_res = await client.get(f"/api/products/{target_prod['id']}")
        restored_stock = restored_prod_res.json()["stock_quantity"]
        assert restored_stock == initial_stock, f"Stock restore failed: expected {initial_stock}, got {restored_stock}"
        print(f"[PASS] 9. Order Cancellation -> Stock restored successfully: {updated_stock} -> {restored_stock}")

        # 10. Stock Movement Form: Stock In
        mv_payload = {
            "product_id": target_prod["id"],
            "movement_type": "IN",
            "quantity": 5,
            "reason": "Test supplier intake",
        }
        mv_res = await client.post("/api/inventory/movement", json=mv_payload)
        assert mv_res.status_code == 201
        mv_data = mv_res.json()
        assert mv_data["new_stock"] == restored_stock + 5
        print(f"[PASS] 10. /api/inventory/movement (IN) -> Stock increased to {mv_data['new_stock']}")

        # 11. HTML Page Routes verification
        dash_res = await client.get("/dashboard")
        assert dash_res.status_code == 200, f"Dashboard returned {dash_res.status_code}"
        print("[PASS] 11a. Authenticated /dashboard -> 200 OK")

        # Now test logout and verify /login renders 200 OK
        client.cookies.clear()
        login_res = await client.get("/login")
        assert login_res.status_code == 200, f"Login returned {login_res.status_code}"
        print("[PASS] 11b. Unauthenticated /login -> 200 OK")

        # Verify unauthenticated /dashboard redirects to /login (302)
        dash_unauth = await client.get("/dashboard", follow_redirects=False)
        assert dash_unauth.status_code == 302
        print("[PASS] 11c. Unauthenticated /dashboard -> 302 Redirect to /login")

    print("=============================================================")
    print("   ALL TESTS PASSED WITH 100% SUCCESS!                       ")
    print("=============================================================")


if __name__ == "__main__":
    asyncio.run(run_tests())
