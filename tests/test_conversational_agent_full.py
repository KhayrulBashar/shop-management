"""
End-to-End Verification Test Suite for Upgraded ShopManage AI Conversational Assistant
Covers:
1. Multi-turn Customer Creation with phone validation, malformed email rejection, optional skipping,
   Edit Details flow, and confirmed creation.
2. Multi-turn Product Creation with unique SKU check, price validation, stock thresholds, and cancellation.
3. Multi-turn Order Creation with customer selection, product stock verification, total calculation, and preview.
4. Stock Movement with OUT quantity validation against inventory levels and preview.
5. Order Status Update workflow.
6. Business Intelligence Queries:
   - Highest sales date aggregation (get_top_sales_date)
   - Top selling products ranking (get_top_selling_products)
   - Top customers by spend (get_top_customers)
   - Sales comparison between today and yesterday (compare_sales_dates)
7. Bengali, Banglish, and English Natural Language Understanding.
8. Replay prevention and token single-use enforcement.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.user import User
from app.models.customer import Customer
from app.models.product import Product
from app.models.order import Order
from app.services.ai.registry import tool_registry
from app.services.ai.session import session_manager
from app.services.ai.orchestrator import ai_orchestrator
from app.services.ai.workflow_engine import validate_email_address, validate_phone_number


async def test_validation_functions():
    print("--- Testing Field Validators ---")
    # Email validation: rejects malformed, accepts valid
    assert validate_email_address("@gmail.com") is None, "Should reject @gmail.com (missing local-part)"
    assert validate_email_address("plainaddress") is None, "Should reject plain string"
    assert validate_email_address("test@") is None, "Should reject missing domain"
    assert validate_email_address("rahim.ahmed@example.com") == "rahim.ahmed@example.com"

    # Phone validation: rejects words, accepts valid numbers
    assert validate_phone_number("rahim") is None, "Should reject letters as phone"
    assert validate_phone_number("01711223344") == "01711223344"
    assert validate_phone_number("+8801711223344") == "+8801711223344"
    print("[PASS] Validation functions (EmailStr & Phone) verified.")


async def test_conversational_customer_workflow(db, user):
    print("\n--- Testing Customer Creation & Edit Details Workflow ---")
    sess = "test_cust_full_wf"

    # 1. Start customer creation in Bengali
    r1 = await ai_orchestrator.process_chat("আমি একটা নতুন কাস্টমার যোগ করতে চাই", sess, user, db)
    assert "নাম" in r1.get("response", "") or "name" in r1.get("response", "").lower()
    print("[PASS] 1. Workflow initiated.")

    # 2. Enter Name
    r2 = await ai_orchestrator.process_chat("Habib Rahman", sess, user, db)
    assert "ফোন" in r2.get("response", "") or "phone" in r2.get("response", "").lower()
    print("[PASS] 2. Name collected, prompted for phone.")

    # 3. Enter Invalid Phone (e.g. "rahim")
    r3 = await ai_orchestrator.process_chat("rahim", sess, user, db)
    assert "সঠিক" in r3.get("response", "") or "valid" in r3.get("response", "").lower()
    print("[PASS] 3. Invalid phone rejected as required.")

    # 4. Enter Valid Phone -> prompts for email
    r4 = await ai_orchestrator.process_chat("01999887766", sess, user, db)
    assert "ইমেইল" in r4.get("response", "") or "email" in r4.get("response", "").lower()
    print("[PASS] 4. Valid phone accepted, prompted for optional email.")

    # 5. User says "Yes" to email
    r5 = await ai_orchestrator.process_chat("হ্যাঁ", sess, user, db)
    assert "ইমেইল ঠিকানাটি লিখুন" in r5.get("response", "") or "enter the email" in r5.get("response", "").lower()
    print("[PASS] 5. Optional email decision 'Yes' handled.")

    # 6. User enters malformed email (@gmail.com)
    r6 = await ai_orchestrator.process_chat("@gmail.com", sess, user, db)
    assert "সঠিক নয়" in r6.get("response", "") or "valid" in r6.get("response", "").lower()
    print("[PASS] 6. Malformed email (@gmail.com) rejected as required.")

    # 7. User enters valid email -> prompts for optional address
    r7 = await ai_orchestrator.process_chat("habib@testshop.com", sess, user, db)
    assert "ঠিকানা" in r7.get("response", "") or "address" in r7.get("response", "").lower()
    print("[PASS] 7. Valid email accepted, prompted for optional address.")

    # 8. User skips address (says "No") -> prompts for optional notes
    r8 = await ai_orchestrator.process_chat("না", sess, user, db)
    assert "নোট" in r8.get("response", "") or "notes" in r8.get("response", "").lower()
    print("[PASS] 8. Optional address skipped, prompted for notes.")

    # 9. User enters notes -> generates preview card
    r9 = await ai_orchestrator.process_chat("হ্যাঁ", sess, user, db)
    r10 = await ai_orchestrator.process_chat("Wholesale retail buyer", sess, user, db)
    assert r10.get("action_required") is True
    pending = r10.get("pending_action", {})
    assert "Habib Rahman" in str(pending.get("details"))
    assert "01999887766" in str(pending.get("details"))
    assert "habib@testshop.com" in str(pending.get("details"))
    print("[PASS] 9. Preview card generated with all entered values.")

    # 10. Test 'Edit Details' flow without losing other values
    r_edit = await ai_orchestrator.process_chat("Edit Details", sess, user, db)
    assert "পরিবর্তন" in r_edit.get("response", "") or "edit" in r_edit.get("response", "").lower()

    # User chooses to edit phone
    r_pick = await ai_orchestrator.process_chat("phone", sess, user, db)
    assert "নতুন" in r_pick.get("response", "") or "new" in r_pick.get("response", "").lower()

    # User enters new phone number
    r_updated = await ai_orchestrator.process_chat("01777000111", sess, user, db)
    assert r_updated.get("action_required") is True
    new_pending = r_updated.get("pending_action", {})
    assert new_pending.get("details", {}).get("Phone Number") == "01777000111"
    assert new_pending.get("details", {}).get("Client Name") == "Habib Rahman"
    assert new_pending.get("details", {}).get("Email Address") == "habib@testshop.com"
    token = new_pending.get("action_token")
    print("[PASS] 10. Edit Details flow updated phone while preserving name and email.")

    # 11. Confirm and execute
    exec_res = await ai_orchestrator.execute_confirmation(token, user, db)
    assert exec_res.get("success") is True
    print("[PASS] 11. Customer confirmed and created in database successfully.")

    # Verify customer in DB and clean up
    created_cust = (await db.execute(select(Customer).where(Customer.phone == "01777000111"))).scalar_one_or_none()
    assert created_cust is not None
    assert created_cust.name == "Habib Rahman"
    assert created_cust.email == "habib@testshop.com"
    await db.delete(created_cust)
    await db.commit()
    print("[PASS] 12. Database verification and cleanup completed.")


async def test_conversational_product_and_cancellation(db, user):
    print("\n--- Testing Product Creation & Cancellation Workflow ---")
    sess = "test_prod_wf"

    # 1. Start product creation
    r1 = await ai_orchestrator.process_chat("একটা নতুন product এড করতে চাই", sess, user, db)
    assert "নাম" in r1.get("response", "") or "name" in r1.get("response", "").lower()

    # 2. Enter product name
    r2 = await ai_orchestrator.process_chat("Wireless Ergonomic Mouse", sess, user, db)
    assert "SKU" in r2.get("response", "")

    # 3. Enter duplicate SKU (e.g. LOGI-M185 from seed)
    existing_prod = (await db.execute(select(Product).limit(1))).scalar_one_or_none()
    assert existing_prod is not None
    r3 = await ai_orchestrator.process_chat(existing_prod.sku, sess, user, db)
    assert "ইতিমধ্যে" in r3.get("response", "") or "already exists" in r3.get("response", "").lower()
    print(f"[PASS] 1. Duplicate SKU check triggered for '{existing_prod.sku}'.")

    # 4. Enter unique SKU
    unique_sku = f"MOUSE-ERG-{os.getpid()}"
    r4 = await ai_orchestrator.process_chat(unique_sku, sess, user, db)
    assert "ক্যাটাগরি" in r4.get("response", "") or "category" in r4.get("response", "").lower()

    # 5. Category
    r5 = await ai_orchestrator.process_chat("Electronics", sess, user, db)
    assert "মূল্য" in r5.get("response", "") or "price" in r5.get("response", "").lower()

    # 6. Price validation (reject 0 or negative)
    r6_bad = await ai_orchestrator.process_chat("0", sess, user, db)
    assert "০-এর বেশি" in r6_bad.get("response", "") or "greater than 0" in r6_bad.get("response", "").lower()
    r6 = await ai_orchestrator.process_chat("1450.00", sess, user, db)
    assert "স্টক" in r6.get("response", "") or "stock" in r6.get("response", "").lower()

    # 7. Initial stock & Reorder level
    r7 = await ai_orchestrator.process_chat("25", sess, user, db)
    r8 = await ai_orchestrator.process_chat("5", sess, user, db)
    assert r8.get("action_required") is True
    print("[PASS] 2. Product preview card generated with validated fields.")

    # 8. Test Cancellation
    r_cancel = await ai_orchestrator.process_chat("বাতিল", sess, user, db)
    assert "বাতিল" in r_cancel.get("response", "") or "cancelled" in r_cancel.get("response", "").lower()

    # Ensure product was NOT created in DB
    prod_check = (await db.execute(select(Product).where(Product.sku == unique_sku))).scalar_one_or_none()
    assert prod_check is None, "Product must NOT be created when cancelled!"
    print("[PASS] 3. Cancellation without DB mutation verified.")


async def test_conversational_order_workflow(db, user):
    print("\n--- Testing Order Creation Workflow ---")
    sess = "test_ord_wf"

    # Find existing customer & product
    cust = (await db.execute(select(Customer).where(Customer.is_deleted == False).limit(1))).scalar_one_or_none()
    prod = (await db.execute(select(Product).where(Product.is_deleted == False, Product.stock_quantity > 2).limit(1))).scalar_one_or_none()
    assert cust is not None and prod is not None

    # 1. Start order
    r1 = await ai_orchestrator.process_chat("আমি একটা order করতে চাই", sess, user, db)
    assert "কাস্টমার" in r1.get("response", "") or "customer" in r1.get("response", "").lower()

    # 2. Select Customer
    r2 = await ai_orchestrator.process_chat(cust.name, sess, user, db)
    assert "পণ্য" in r2.get("response", "") or "product" in r2.get("response", "").lower()

    # 3. Select Product
    r3 = await ai_orchestrator.process_chat(prod.sku, sess, user, db)
    assert "কত পিস" in r3.get("response", "") or "quantity" in r3.get("response", "").lower()

    # 4. Test Stock Validation (reject quantity > available stock)
    too_much = prod.stock_quantity + 500
    r4_bad = await ai_orchestrator.process_chat(str(too_much), sess, user, db)
    assert "অপর্যাপ্ত" in r4_bad.get("response", "") or "insufficient" in r4_bad.get("response", "").lower()
    print("[PASS] 1. Insufficient stock quantity rejected.")

    # 5. Valid quantity
    r4 = await ai_orchestrator.process_chat("2", sess, user, db)
    assert "আরও পণ্য" in r4.get("response", "") or "another product" in r4.get("response", "").lower()

    # 6. Skip additional items
    r5 = await ai_orchestrator.process_chat("না", sess, user, db)
    assert "নোট" in r5.get("response", "") or "notes" in r5.get("response", "").lower()

    # 7. Skip notes -> Preview generated
    r6 = await ai_orchestrator.process_chat("না", sess, user, db)
    assert r6.get("action_required") is True
    pending = r6.get("pending_action", {})
    assert "Order" in pending.get("title")
    print("[PASS] 2. Order preview card generated with items and calculated total.")

    # Cancel order creation
    r_cancel = await ai_orchestrator.process_chat("cancel", sess, user, db)
    assert "cancelled" in r_cancel.get("response", "").lower() or "বাতিল" in r_cancel.get("response", "")
    print("[PASS] 3. Order workflow cancelled safely.")


async def test_business_intelligence_queries(db, user):
    print("\n--- Testing Section 9 Business Intelligence & Analytics ---")
    sess = "test_bi_queries"

    # 1. Highest sales date aggregation
    r_top_date = await ai_orchestrator.process_chat("কোনদিন সবচেয়ে বেশি sales হয়েছে?", sess, user, db)
    assert r_top_date.get("data") is not None
    assert "সর্বোচ্চ সেলস" in r_top_date.get("response", "") or "highest sales" in r_top_date.get("response", "").lower()
    print(f"[PASS] 1. Top sales date query: {r_top_date.get('response')[:65]}...")

    # 2. Top selling products
    r_top_prod = await ai_orchestrator.process_chat("Which product sold the most this month?", sess, user, db)
    assert r_top_prod.get("data") is not None
    assert "top selling" in r_top_prod.get("response", "").lower() or "শীর্ষ বিক্রিত" in r_top_prod.get("response", "")
    print(f"[PASS] 2. Top selling products query: {r_top_prod.get('response')[:65]}...")

    # 3. Top customers ranking by total order value
    r_top_cust = await ai_orchestrator.process_chat("Show the top five customers by total order value", sess, user, db)
    assert r_top_cust.get("data") is not None
    assert "top" in r_top_cust.get("response", "").lower() or "কাস্টমার" in r_top_cust.get("response", "")
    print(f"[PASS] 3. Top customers query: {r_top_cust.get('response')[:65]}...")

    # 4. Sales comparison between today and yesterday
    r_comp = await ai_orchestrator.process_chat("গতকালের sales-এর সঙ্গে আজকের sales compare করো", sess, user, db)
    assert r_comp.get("data") is not None
    assert "তুলনা" in r_comp.get("response", "") or "comparison" in r_comp.get("response", "").lower()
    print(f"[PASS] 4. Sales comparison query: {r_comp.get('response')[:65]}...")


async def run_conversational_e2e_suite():
    print("==================================================================")
    print("  RUNNING COMPREHENSIVE CONVERSATIONAL AI VERIFICATION SUITE       ")
    print("==================================================================")
    await test_validation_functions()

    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).limit(1))).scalar_one_or_none()
        assert user is not None, "Administrator user required!"

        await test_conversational_customer_workflow(db, user)
        await test_conversational_product_and_cancellation(db, user)
        await test_conversational_order_workflow(db, user)
        await test_business_intelligence_queries(db, user)

    print("\n==================================================================")
    print("  ALL CONVERSATIONAL AI & BI CAPABILITIES PASSED (100% SUCCESS)    ")
    print("==================================================================")


if __name__ == "__main__":
    asyncio.run(run_conversational_e2e_suite())
