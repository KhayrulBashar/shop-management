"""
Unit and Integration Tests for AI Agent Backend (Phase B)
"""
import asyncio
import os
import sys

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from httpx import ASGITransport, AsyncClient
from app.main import app
from app.services.ai.registry import tool_registry
from app.services.ai.session import session_manager
from app.services.ai.provider import FallbackRuleBasedProvider


async def test_tool_registry_registration():
    tools = tool_registry.get_all()
    assert len(tools) >= 5, "Expected at least 5 registered tools"

    stats_tool = tool_registry.get("get_dashboard_stats")
    assert stats_tool is not None
    assert stats_tool.is_mutation is False

    prod_tool = tool_registry.get("create_product")
    assert prod_tool is not None
    assert prod_tool.is_mutation is True

    schemas = tool_registry.to_json_schemas()
    assert any(s["name"] == "create_order" for s in schemas)
    print("[PASS] Tool registry registration verified.")


async def test_session_manager_isolation_and_consumption():
    user1_id = 101
    user2_id = 102

    # Create session for user 1
    sess1 = await session_manager.get_or_create_session(None, user1_id)
    assert sess1.startswith("sess_")

    await session_manager.add_message(sess1, "user", "Hello assistant")
    history1 = await session_manager.get_history(sess1, user1_id)
    assert len(history1) == 1
    assert history1[0]["content"] == "Hello assistant"

    # User 2 cannot access user 1's history
    history2 = await session_manager.get_history(sess1, user2_id)
    assert len(history2) == 0

    # Pending action creation and single-use consumption
    action = await session_manager.create_pending_action(
        session_id=sess1,
        user_id=user1_id,
        tool_name="create_product",
        arguments={"name": "Test Wireless Mouse", "sku": "MOUSE-01", "price": 1200},
        preview_title="Confirm Product",
        preview_summary="Create product MOUSE-01",
        preview_details={"Price": 1200},
    )
    assert action.action_token.startswith("act_")

    # User 2 cannot consume user 1's action token
    consumed_user2 = await session_manager.consume_pending_action(action.action_token, user2_id)
    assert consumed_user2 is None

    # User 1 consumes action token
    consumed_user1 = await session_manager.consume_pending_action(action.action_token, user1_id)
    assert consumed_user1 is not None
    assert consumed_user1.tool_name == "create_product"

    # Replay attack prevention: token can NOT be consumed a second time
    replay_attempt = await session_manager.consume_pending_action(action.action_token, user1_id)
    assert replay_attempt is None
    print("[PASS] Session manager isolation & single-use confirmation token verified.")


async def test_fallback_provider_bengali_understanding():
    provider = FallbackRuleBasedProvider()

    # Bengali query for sales/revenue
    res_sales = await provider.generate_response(
        messages=[{"role": "user", "content": "আজকের মোট বিক্রি এবং রাজস্ব দেখাও"}],
        tools_schema=[],
        system_prompt="",
    )
    assert len(res_sales.tool_calls) == 1
    assert res_sales.tool_calls[0].name == "get_dashboard_stats"

    # Bengali query for low stock
    res_stock = await provider.generate_response(
        messages=[{"role": "user", "content": "কোন পণ্যগুলোর কম স্টক আছে?"}],
        tools_schema=[],
        system_prompt="",
    )
    assert len(res_stock.tool_calls) == 1
    assert res_stock.tool_calls[0].name == "get_low_stock_products"

    # English query for product search
    res_search = await provider.generate_response(
        messages=[{"role": "user", "content": "search product Logitech"}],
        tools_schema=[],
        system_prompt="",
    )
    assert len(res_search.tool_calls) == 1
    assert res_search.tool_calls[0].name == "search_products"
    assert res_search.tool_calls[0].arguments.get("query") == "logitech"
    print("[PASS] Fallback provider Bengali/English understanding verified.")


async def test_api_ai_route_protection():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Unauthenticated request must return 401 Unauthorized
        res = await client.post("/api/ai/chat", json={"message": "Show dashboard"})
        assert res.status_code == 401, f"Expected 401 Unauthorized, got {res.status_code}"

        res_cap = await client.get("/api/ai/capabilities")
        assert res_cap.status_code == 401, f"Expected 401 Unauthorized, got {res_cap.status_code}"

    print("[PASS] API /api/ai endpoints authentication protection verified (401 on unauthenticated).")


async def run_all():
    print("==================================================")
    print("Running AI Backend Unit Tests (Phase B)...")
    print("==================================================")
    await test_tool_registry_registration()
    await test_session_manager_isolation_and_consumption()
    await test_fallback_provider_bengali_understanding()
    await test_api_ai_route_protection()
    print("==================================================")
    print("ALL AI BACKEND TESTS PASSED SUCCESSFULLY (100%)!")
    print("==================================================")


if __name__ == "__main__":
    asyncio.run(run_all())
