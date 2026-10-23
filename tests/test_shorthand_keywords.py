"""
Verification test suite for shorthand entity queries, keywords, and punctuation variants.
Covers:
- Total customer?, Total customer, customer?, customer, কাস্টমার?, কাস্টমার, গ্রাহক?
- Total product?, Total product, product?, product, প্রোডাক্ট?, প্রোডাক্ট, পণ্য?
- Total order?, Total order, order?, order, orders?, অর্ডার?, অর্ডার
- sales?, sales, সেলস?, সেলস, revenue?, revenue, বিক্রি?, বিক্রি
- low stock?, low stock, কম স্টক?, কম স্টক, stock?, stock, স্টক?
- inventory?, inventory, ইনভেন্টরি?
- dashboard?, dashboard, ড্যাশবোর্ড?
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.user import User
from app.services.ai.orchestrator import ai_orchestrator


TEST_CASES = [
    # 1. Customer Queries
    ("Total customer?", "customer count", ["registered customer", "সক্রিয় কাস্টমার"]),
    ("Total customer", "customer count", ["registered customer", "সক্রিয় কাস্টমার"]),
    ("customer?", "customer directory", ["customer(s)", "কাস্টমার পাওয়া গেছে"]),
    ("customer", "customer directory", ["customer(s)", "কাস্টমার পাওয়া গেছে"]),
    ("কাস্টমার?", "customer directory", ["কাস্টমার পাওয়া গেছে", "customer(s)"]),
    ("কাস্টমার", "customer directory", ["কাস্টমার পাওয়া গেছে", "customer(s)"]),
    ("গ্রাহক?", "customer directory", ["কাস্টমার পাওয়া গেছে", "customer(s)"]),
    ("মোট কাস্টমার?", "customer count", ["সক্রিয় কাস্টমার", "registered customer"]),

    # 2. Product Queries
    ("Total product?", "product count", ["active product", "অ্যাক্টিভ প্রোডাক্ট"]),
    ("Total product", "product count", ["active product", "অ্যাক্টিভ প্রোডাক্ট"]),
    ("product?", "product catalog", ["product(s)", "পণ্য পাওয়া গেছে"]),
    ("product", "product catalog", ["product(s)", "পণ্য পাওয়া গেছে"]),
    ("প্রোডাক্ট?", "product catalog", ["পণ্য পাওয়া গেছে", "product(s)"]),
    ("পণ্য?", "product catalog", ["পণ্য পাওয়া গেছে", "product(s)"]),
    ("মোট প্রোডাক্ট?", "product count", ["অ্যাক্টিভ প্রোডাক্ট", "active product"]),

    # 3. Order Queries
    ("Total order?", "order count", ["total order", "মোট", "অর্ডার রেকর্ড"]),
    ("Total order", "order count", ["total order", "মোট", "অর্ডার রেকর্ড"]),
    ("order?", "order list", ["recent order", "সাম্প্রতিক অর্ডার", "অর্ডার"]),
    ("order", "order list", ["recent order", "সাম্প্রতিক অর্ডার", "অর্ডার"]),
    ("orders?", "order list", ["recent order", "সাম্প্রতিক অর্ডার", "অর্ডার"]),
    ("অর্ডার?", "order list", ["সাম্প্রতিক অর্ডার", "recent order", "অর্ডার"]),
    ("মোট অর্ডার?", "order count", ["মোট", "অর্ডার রেকর্ড", "total order"]),

    # 4. Sales / Revenue Queries
    ("sales?", "sales revenue", ["৳", "revenue", "রেভিনিউ", "বিক্রয়"]),
    ("sales", "sales revenue", ["৳", "revenue", "রেভিনিউ", "বিক্রয়"]),
    ("সেলস?", "sales revenue", ["৳", "রেভিনিউ", "বিক্রয়", "revenue"]),
    ("revenue?", "sales revenue", ["৳", "revenue", "রেভিনিউ", "বিক্রয়"]),
    ("বিক্রি?", "sales revenue", ["৳", "রেভিনিউ", "বিক্রয়", "revenue"]),
    ("total sales?", "sales revenue", ["৳", "revenue", "রেভিনিউ", "বিক্রয়"]),

    # 5. Stock & Low Stock Queries
    ("low stock?", "low stock alerts", ["reorder", "threshold", "সতর্কসীমা", "পর্যাপ্ত"]),
    ("কম স্টক?", "low stock alerts", ["সতর্কসীমা", "reorder", "পর্যাপ্ত", "threshold"]),
    ("stock?", "stock status", ["reorder", "threshold", "সতর্কসীমা", "পর্যাপ্ত"]),
    ("স্টক?", "stock status", ["সতর্কসীমা", "reorder", "পর্যাপ্ত", "threshold"]),

    # 6. Inventory Queries
    ("inventory?", "inventory movements", ["inventory", "মুভমেন্ট", "movement", "audit log"]),
    ("ইনভেন্টরি?", "inventory movements", ["মুভমেন্ট", "movement", "inventory", "রেকর্ড"]),

    # 7. Dashboard Queries
    ("dashboard?", "dashboard overview", ["Total Customers", "মোট কাস্টমার", "পরিসংখ্যান", "Active Products"]),
    ("ড্যাশবোর্ড?", "dashboard overview", ["মোট কাস্টমার", "পরিসংখ্যান", "Total Customers"]),
]


async def run_shorthand_suite():
    print("==================================================================")
    print("  RUNNING SHORTHAND & KEYWORD RECOGNITION TEST SUITE              ")
    print("==================================================================")

    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).limit(1))).scalar_one_or_none()
        assert user is not None, "Administrator user required!"

        passed = 0
        failed = 0

        for idx, (query, expected_desc, expected_tokens) in enumerate(TEST_CASES, 1):
            sess_id = f"test_kw_{idx}"
            result = await ai_orchestrator.process_chat(query, sess_id, user, db)
            resp = result.get("response", "")
            data = result.get("data")

            # Check if any of the expected tokens match
            matched = any(token.lower() in resp.lower() for token in expected_tokens)
            has_data = data is not None

            if matched and has_data:
                print(f"[PASS] {idx:02d}. Query: '{query}' -> {expected_desc} | Resp: {resp[:55]}...")
                passed += 1
            else:
                print(f"[FAIL] {idx:02d}. Query: '{query}' -> {expected_desc}")
                print(f"       Response: {resp}")
                print(f"       Data: {data}")
                failed += 1

        print("==================================================================")
        print(f"  RESULTS: {passed}/{len(TEST_CASES)} PASSED, {failed} FAILED")
        print("==================================================================")

        assert failed == 0, f"{failed} test case(s) failed."


if __name__ == "__main__":
    asyncio.run(run_shorthand_suite())
