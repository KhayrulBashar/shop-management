import logging
import re
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.ai.provider import FallbackRuleBasedProvider, get_ai_provider, is_bengali_input
from app.services.ai.registry import tool_registry
from app.services.ai.session import session_manager
from app.services.ai.workflow_engine import conversational_workflow_engine
# Ensure tool implementations are registered
import app.services.ai.tools_impl

logger = logging.getLogger("shop_management.ai")

SYSTEM_PROMPT = """You are an intelligent, reliable AI assistant inside the Shop Management System (FastAPI + PostgreSQL ERP).
Your role is to assist the store manager with products, customers, orders, inventory movements, sales reports, and dashboard analytics.

CORE OPERATIONAL RULES:
1. Language matching: Respond in the language of the user's latest query:
   - If the user writes or speaks in Bengali or Banglish -> respond in natural, polite Bengali.
   - If the user writes in English -> respond in clear English.
2. Carefully understand the user's intent from Bengali, Banglish, or English.
3. For factual questions (customer count, customer existence, order totals, sales on a specific date, product stock, low stock, dashboard stats), ALWAYS call the appropriate registered tool.
4. Preserve all database values, customer names, product names, SKUs, numbers, and currency (৳) exactly as stored. Never invent or alter them.
5. For write operations (create product, create customer, create order, stock adjustments), call the appropriate tool. The system intercepts mutations and shows an exact confirmation card requiring user approval.
6. If a request is ambiguous or lacks required details, ask a polite, targeted clarification question.
7. If a request is completely outside the scope of shop management (weather, general knowledge, movies), politely explain the assistant's scope.
8. Be concise, polite, helpful, and professional.
"""


class AIOrchestrator:
    """
    Coordinates language understanding, conversational slot-filling, context resolution,
    model routing, tool dispatch, and confirmation workflows.
    """

    async def process_chat(
        self,
        user_message: str,
        session_id: str | None,
        user: User,
        db: AsyncSession,
    ) -> dict[str, Any]:
        # 1. Resolve or create user session
        active_session_id = await session_manager.get_or_create_session(session_id, user.id)
        await session_manager.add_message(active_session_id, "user", user_message)

        is_bn = is_bengali_input(user_message)
        msg_clean = user_message.strip().lower()

        # 2. Check if user wants to cancel an active multi-turn workflow
        if any(w in msg_clean for w in ["cancel", "বাতিল", "দরকার নেই", "থাক", "stop", "exit"]):
            current_wf = await session_manager.get_pending_workflow(active_session_id)
            if current_wf:
                await session_manager.clear_pending_workflow(active_session_id)
                cancel_reply = "ওয়ার্কফ্লো এবং এন্ট্রি প্রক্রিয়াটি বাতিল করা হয়েছে।" if is_bn else "The conversational workflow has been cancelled."
                await session_manager.add_message(active_session_id, "assistant", cancel_reply)
                return {
                    "session_id": active_session_id,
                    "response": cancel_reply,
                    "action_required": False,
                    "pending_action": None,
                    "quick_replies": [],
                    "data": None,
                }

        # 3. Check if there is an active pending workflow
        current_wf = await session_manager.get_pending_workflow(active_session_id)
        if current_wf:
            wf_res = await conversational_workflow_engine.handle_turn(
                active_session_id, user_message, current_wf, user, db
            )
            await session_manager.add_message(active_session_id, "assistant", wf_res.get("response", ""))
            return wf_res

        # 4. Check if user is starting one of the 5 form workflows in this turn:

        # 4a. Customer Creation
        if any(w in msg_clean for w in ["নতুন কাস্টমার", "নতুন গ্রাহক", "কাস্টমার এড", "কাস্টমার যোগ", "কাস্টমার তৈরি", "add customer", "create customer", "new customer", "add new customer", "customer add"]):
            name_match = re.search(r"(?:customer|কাস্টমার|গ্রাহক)\s+([a-zA-Z0-9\u0980-\u09FF\s]+?)(?:\s+(?:phone|মোবাইল|ফোন)|$)", user_message, re.I)
            init_name = name_match.group(1).strip() if name_match else None
            if init_name and any(w in init_name.lower() for w in ["এড", "করতে", "চাই", "new", "add", "create", "যোগ"]):
                init_name = None
            start_res = await conversational_workflow_engine.start_customer_workflow(active_session_id, is_bn, init_name)
            await session_manager.add_message(active_session_id, "assistant", start_res.get("response", ""))
            return {
                "session_id": active_session_id,
                "response": start_res.get("response", ""),
                "action_required": False,
                "pending_action": None,
                "quick_replies": start_res.get("quick_replies", []),
                "data": None,
            }

        # 4b. Product Creation
        if any(w in msg_clean for w in ["নতুন প্রোডাক্ট", "নতুন প্রডাক্ট", "নতুন পণ্য", "প্রোডাক্ট এড", "প্রোডাক্ট যোগ", "প্রোডাক্ট তৈরি", "পণ্য যোগ", "নতুন product", "product এড", "product যোগ", "product তৈরি", "add product", "create product", "new product", "add new product"]):
            pname_match = re.search(r"(?:product|প্রোডাক্ট|পণ্য)\s+([a-zA-Z0-9\u0980-\u09FF\s]+?)(?:\s+(?:sku|price|দাম|মূল্য)|$)", user_message, re.I)
            init_pname = pname_match.group(1).strip() if pname_match else None
            if init_pname and any(w in init_pname.lower() for w in ["এড", "করতে", "চাই", "new", "add", "create", "যোগ"]):
                init_pname = None
            start_res = await conversational_workflow_engine.start_product_workflow(active_session_id, is_bn, init_pname)
            await session_manager.add_message(active_session_id, "assistant", start_res.get("response", ""))
            return {
                "session_id": active_session_id,
                "response": start_res.get("response", ""),
                "action_required": False,
                "pending_action": None,
                "quick_replies": start_res.get("quick_replies", []),
                "data": None,
            }

        # 4c. Order Creation
        if any(w in msg_clean for w in ["নতুন অর্ডার", "অর্ডার তৈরি", "অর্ডার করতে চাই", "অর্ডার এড", "অর্ডার যোগ", "order করতে চাই", "নতুন order", "order তৈরি", "order এড", "create order", "add order", "new order", "place order"]):
            start_res = await conversational_workflow_engine.start_order_workflow(active_session_id, is_bn)
            await session_manager.add_message(active_session_id, "assistant", start_res.get("response", ""))
            return {
                "session_id": active_session_id,
                "response": start_res.get("response", ""),
                "action_required": False,
                "pending_action": None,
                "quick_replies": start_res.get("quick_replies", []),
                "data": None,
            }

        # 4d. Stock Movement
        if any(w in msg_clean for w in ["স্টক মুভমেন্ট", "স্টক আপডেট করতে চাই", "স্টক পরিবর্তন", "স্টক ইন", "স্টক আউট", "stock movement", "record stock movement", "update stock"]):
            start_res = await conversational_workflow_engine.start_stock_movement_workflow(active_session_id, is_bn)
            await session_manager.add_message(active_session_id, "assistant", start_res.get("response", ""))
            return {
                "session_id": active_session_id,
                "response": start_res.get("response", ""),
                "action_required": False,
                "pending_action": None,
                "quick_replies": start_res.get("quick_replies", []),
                "data": None,
            }

        # 4e. Order Status Update
        if any(w in msg_clean for w in ["অর্ডারের স্ট্যাটাস", "অর্ডার স্ট্যাটাস", "স্ট্যাটাস পরিবর্তন করতে চাই", "স্ট্যাটাস আপডেট", "update order status", "change order status"]):
            start_res = await conversational_workflow_engine.start_order_status_workflow(active_session_id, is_bn)
            await session_manager.add_message(active_session_id, "assistant", start_res.get("response", ""))
            return {
                "session_id": active_session_id,
                "response": start_res.get("response", ""),
                "action_required": False,
                "pending_action": None,
                "quick_replies": start_res.get("quick_replies", []),
                "data": None,
            }

        # 5. Retrieve conversation history & context
        history = await session_manager.get_history(active_session_id, user.id)
        session_context = await session_manager.get_session_context(active_session_id)

        # 6. Get provider and tool definitions
        provider = get_ai_provider()
        tools_schema = tool_registry.to_json_schemas()

        # 7. Generate model response
        response = await provider.generate_response(
            messages=history,
            tools_schema=tools_schema,
            system_prompt=SYSTEM_PROMPT,
        )

        # Fallback to intelligent rule-based engine if provider fails, 429s, or returns empty
        if response.error or (not response.tool_calls and not response.text):
            logger.info(f"Primary AI provider status: {response.error or 'No output'}. Routing through contextual parser.")
            fallback_provider = FallbackRuleBasedProvider()
            response = await fallback_provider.generate_response(
                messages=history,
                tools_schema=tools_schema,
                system_prompt=SYSTEM_PROMPT,
                session_context=session_context,
            )
        elif not response.tool_calls:
            # If primary provider returned pure text without calling tools for a domain query,
            # consult the contextual rule engine to see if a DB tool call should have been triggered.
            fallback_provider = FallbackRuleBasedProvider()
            candidate = await fallback_provider.generate_response(
                messages=history,
                tools_schema=tools_schema,
                system_prompt=SYSTEM_PROMPT,
                session_context=session_context,
            )
            if candidate.tool_calls:
                response = candidate

        # 8. Handle Tool Calls
        if response.tool_calls:
            first_call = response.tool_calls[0]
            tool_name = first_call.name
            tool_args = first_call.arguments
            tool_def = tool_registry.get(tool_name)

            if not tool_def:
                error_msg = f"Unknown tool '{tool_name}' requested. Please try again."
                await session_manager.add_message(active_session_id, "assistant", error_msg)
                return {
                    "session_id": active_session_id,
                    "response": error_msg,
                    "action_required": False,
                    "pending_action": None,
                }

            # Check if this tool is a MUTATION requiring confirmation
            if tool_def.is_mutation:
                if tool_def.preview_generator:
                    title, summary, details = tool_def.preview_generator(tool_args)
                else:
                    title = f"Confirm {tool_name}"
                    summary = f"Execute {tool_name} with provided arguments."
                    details = tool_args

                action = await session_manager.create_pending_action(
                    session_id=active_session_id,
                    user_id=user.id,
                    tool_name=tool_name,
                    arguments=tool_args,
                    preview_title=title,
                    preview_summary=summary,
                    preview_details=details,
                )

                confirm_prompt = (
                    f"অপারেশনটির বিস্তারিত নিচে তৈরি করা হলো। অনুগ্রহ করে তথ্য যাচাই করে নিশ্চিত করুন:"
                    if is_bn
                    else f"I have prepared this operation for you. Please review the details below and confirm to execute:"
                )
                await session_manager.add_message(active_session_id, "assistant", confirm_prompt)

                return {
                    "session_id": active_session_id,
                    "response": confirm_prompt,
                    "action_required": True,
                    "pending_action": {
                        "action_token": action.action_token,
                        "title": action.preview_title,
                        "summary": action.preview_summary,
                        "details": action.preview_details,
                        "expires_at": action.expires_at.isoformat(),
                    },
                    "data": None,
                }

            # Otherwise, tool is READ-ONLY: execute immediately
            try:
                result_data = await tool_def.handler(db, user, tool_args)

                # Update session context based on tool execution for follow-up resolutions
                if tool_name in ["get_customer_existence", "search_customers", "get_customer_order_totals"]:
                    cust = result_data.get("customer")
                    if cust and isinstance(cust, dict):
                        await session_manager.update_session_context(
                            active_session_id,
                            {"last_customer_id": cust.get("id"), "last_customer_name": cust.get("name"), "last_customer_phone": cust.get("phone")}
                        )
                    elif result_data.get("customers") and len(result_data["customers"]) == 1:
                        c0 = result_data["customers"][0]
                        await session_manager.update_session_context(
                            active_session_id,
                            {"last_customer_id": c0.get("id"), "last_customer_name": c0.get("name"), "last_customer_phone": c0.get("phone")}
                        )
                    elif result_data.get("customer_id"):
                        await session_manager.update_session_context(
                            active_session_id,
                            {"last_customer_id": result_data.get("customer_id"), "last_customer_name": result_data.get("customer_name")}
                        )

                if tool_name in ["search_products", "get_product_sales", "get_product_details"]:
                    if result_data.get("product_id"):
                        await session_manager.update_session_context(
                            active_session_id,
                            {"last_product_id": result_data.get("product_id"), "last_product_name": result_data.get("product_name"), "last_topic": "product_sales"}
                        )
                    elif result_data.get("products") and len(result_data["products"]) == 1:
                        p0 = result_data["products"][0]
                        await session_manager.update_session_context(
                            active_session_id,
                            {"last_product_id": p0.get("id"), "last_product_name": p0.get("name"), "last_topic": "product"}
                        )

                if tool_name == "get_sales_by_date":
                    await session_manager.update_session_context(
                        active_session_id,
                        {"last_topic": "sales", "last_date": result_data.get("date_label")}
                    )

                # Attempt dynamic natural language summary via Gemini if available
                dynamic_summary = None
                if hasattr(provider, "summarize_tool_result"):
                    try:
                        dynamic_summary = await provider.summarize_tool_result(
                            messages=history,
                            tool_name=tool_name,
                            tool_result=result_data,
                            system_prompt=SYSTEM_PROMPT,
                        )
                    except Exception as e:
                        logger.warning(f"Could not get summary from provider: {e}")

                if dynamic_summary:
                    reply_text = dynamic_summary
                elif response.text and not response.is_fallback:
                    reply_text = response.text
                else:
                    reply_text = self._format_readable_summary(tool_name, result_data, user_message)

                await session_manager.add_message(
                    active_session_id,
                    "assistant",
                    reply_text,
                    tool_name=tool_name,
                )

                return {
                    "session_id": active_session_id,
                    "response": reply_text,
                    "action_required": False,
                    "pending_action": None,
                    "data": result_data,
                }
            except Exception as exc:
                logger.error(f"Error executing read tool '{tool_name}': {exc}", exc_info=True)
                err_reply = f"Error retrieving information: {str(exc)}"
                await session_manager.add_message(active_session_id, "assistant", err_reply)
                return {
                    "session_id": active_session_id,
                    "response": err_reply,
                    "action_required": False,
                    "pending_action": None,
                    "error": str(exc),
                }

        # 9. Standard text response without tool calls (e.g. clarification or scope explanation)
        final_text = response.text or (
            "আমি আপনার শপ ম্যানেজমেন্টের দৈনন্দিন কাজে সাহায্য করতে প্রস্তুত। আপনি কী জানতে চান?"
            if is_bn
            else "I am ready to help you with shop management operations. How can I assist you today?"
        )
        await session_manager.add_message(active_session_id, "assistant", final_text)

        return {
            "session_id": active_session_id,
            "response": final_text,
            "action_required": False,
            "pending_action": None,
            "data": None,
        }

    def _format_readable_summary(self, tool_name: str, data: dict[str, Any], user_query: str) -> str:
        q_lower = (user_query or "").lower()
        is_bn = is_bengali_input(user_query)

        # 1. Dashboard & Analytics Tool
        if tool_name == "get_dashboard_stats":
            cust = data.get("total_customers", 0)
            sales = float(data.get("total_sales_tk") or 0.0)
            prod = data.get("total_products", 0)
            orders = data.get("total_orders", 0)
            low = data.get("low_stock_items_count", 0)

            if any(w in q_lower for w in ["কাস্টমার", "customer", "গ্রাহক"]):
                return (
                    f"বর্তমানে ডাটাবেসে মোট **{cust} জন** সক্রিয় কাস্টমার নিবন্ধিত রয়েছে।"
                    if is_bn
                    else f"You currently have **{cust} registered customer(s)** in your shop database."
                )

            if any(w in q_lower for w in ["পণ্য", "প্রোডাক্ট", "product"]):
                return (
                    f"বর্তমানে আপনার শপে মোট **{prod}টি** অ্যাক্টিভ প্রোডাক্ট ক্যাটালগে রয়েছে।"
                    if is_bn
                    else f"There are currently **{prod} active product(s)** in your catalog."
                )

            if any(w in q_lower for w in ["অর্ডার", "order", "orders"]):
                return (
                    f"বর্তমানে আপনার শপে মোট **{orders}টি** অর্ডার রেকর্ড করা আছে।"
                    if is_bn
                    else f"There are currently **{orders} total order(s)** recorded in your shop."
                )

            if any(w in q_lower for w in ["কম স্টক", "low stock", "ঘাটতি"]):
                return (
                    f"বর্তমানে **{low}টি** পণ্যের স্টক নির্ধারিত সতর্কতার সীমার নিচে রয়েছে।"
                    if is_bn
                    else f"There are currently **{low} low stock item(s)** below reorder alert levels."
                )

            if any(w in q_lower for w in ["রেভিনিউ", "বিক্রি", "সেলস", "revenue", "sales", "টাকা", "আয়", "বিক্রয়", "লাভ", "ইনকাম"]):
                return (
                    f"ড্যাশবোর্ডের মোট অনুমোদিত বিক্রয়/রেভিনিউ **৳{sales:,.2f}** (ক্যালকুলেশন নিয়ম: শুধুমাত্র Delivered এবং Paid অর্ডার)।"
                    if is_bn
                    else f"The total verified revenue shown on your dashboard is **৳{sales:,.2f}** (calculated strictly from Delivered and Paid orders)."
                )

            # Combined overview
            if is_bn:
                return (
                    f"দোকানের বর্তমান সামগ্রিক পরিসংখ্যান:\n\n"
                    f"• **মোট কাস্টমার:** {cust} জন\n"
                    f"• **অ্যাক্টিভ প্রোডাক্ট:** {prod}টি\n"
                    f"• **মোট অর্ডার:** {orders}টি\n"
                    f"• **অনুমোদিত মোট রেভিনিউ:** ৳{sales:,.2f} *(শুধুমাত্র Delivered ও Paid)*\n"
                    f"• **কম স্টকের পণ্য:** {low}টি"
                )
            return (
                f"Here are your shop's latest metrics:\n\n"
                f"• **Total Customers:** {cust}\n"
                f"• **Active Products:** {prod}\n"
                f"• **Total Orders:** {orders}\n"
                f"• **Total Verified Revenue:** ৳{sales:,.2f} *(Delivered & Paid only)*\n"
                f"• **Low Stock Items:** {low}"
            )

        # 2. Customer Existence Check Tool
        elif tool_name == "get_customer_existence":
            query = data.get("query", "")
            if not data.get("exists"):
                return (
                    f"না, **'{query}'** নামে কোনো কাস্টমার ডাটাবেসে পাওয়া যায়নি।"
                    if is_bn
                    else f"No, I could not find any customer named **'{query}'** in the database."
                )

            if data.get("is_ambiguous"):
                matches = data.get("matches", [])
                lines = [f"• **{m.get('name')}** (ফোন: {m.get('phone') or 'N/A'}, মোট অর্ডার: {m.get('orders_count', 0)}টি)" for m in matches]
                joined = "\n".join(lines)
                if is_bn:
                    return f"আমি **'{query}'** নামে একাধিক কাস্টমার পেয়েছি। আপনি কোনজনকে বোঝাচ্ছেন?\n\n{joined}"
                return f"I found multiple customers matching **'{query}'**. Which one do you mean?\n\n{joined}"

            c = data.get("customer", {})
            c_name = c.get("name", query)
            c_phone = c.get("phone") or "N/A"
            c_orders = c.get("orders_count", 0)
            if is_bn:
                return f"হ্যাঁ, **'{c_name}'** নামে কাস্টমার পাওয়া গেছে (ফোন: {c_phone}, মোট অর্ডার: {c_orders}টি)।"
            return f"Yes, I found a customer named **{c_name}** (Phone: {c_phone}, Total Orders: {c_orders})."

        # 3. Customer Order Totals Tool
        elif tool_name == "get_customer_order_totals":
            if not data.get("found"):
                return (
                    "কাস্টমারের কোনো তথ্য বা অর্ডার পাওয়া যায়নি।"
                    if is_bn
                    else "No customer order records found."
                )

            if data.get("is_ambiguous"):
                matches = data.get("matches", [])
                lines = [f"• **{m.get('name')}** (ফোন: {m.get('phone') or 'N/A'})" for m in matches]
                joined = "\n".join(lines)
                return (
                    f"একাধিক কাস্টমার পাওয়া গেছে। আপনি কোনজনকে বোঝাচ্ছেন?\n\n{joined}"
                    if is_bn
                    else f"Multiple customers found. Which one do you mean?\n\n{joined}"
                )

            name = data.get("customer_name")
            orders = data.get("total_orders", 0)
            total = float(data.get("total_amount_tk") or 0.0)
            paid = float(data.get("delivered_paid_amount_tk") or 0.0)
            if is_bn:
                return f"**{name}** মোট **{orders}টি** অর্ডার করেছেন, যার সর্বমোট মূল্য **৳{total:,.2f}** (অনুমোদিত Delivered & Paid: ৳{paid:,.2f})।"
            return f"**{name}** has placed **{orders}** order(s) totaling **৳{total:,.2f}** (Verified Delivered & Paid: ৳{paid:,.2f})."

        # 4. Date-based Sales Reporting Tool
        elif tool_name == "get_sales_by_date":
            label = data.get("date_label")
            total = float(data.get("total_sales_tk") or 0.0)
            orders = data.get("total_orders", 0)
            paid = data.get("delivered_paid_orders", 0)
            if is_bn:
                return f"**{label}**-এর মোট অনুমোদিত সেলস: **৳{total:,.2f}** (মোট {orders}টি অর্ডারের মধ্যে {paid}টি Delivered ও Paid)।"
            return f"Total verified sales for **{label}**: **৳{total:,.2f}** ({paid} Delivered & Paid orders out of {orders} total)."

        # 5. Product Sales Tool
        elif tool_name == "get_product_sales":
            if not data.get("found"):
                return (
                    "পণ্যটি পাওয়া যায়নি বা কোনো বিক্রয় রেকর্ড নেই।"
                    if is_bn
                    else "Product not found or no sales records available."
                )

            if data.get("is_ambiguous"):
                matches = data.get("matches", [])
                lines = [f"• **{m.get('name')}** (SKU: {m.get('sku')})" for m in matches]
                joined = "\n".join(lines)
                return (
                    f"একাধিক পণ্য পাওয়া গেছে। আপনি কোন পণ্যটির সেলস জানতে চান?\n\n{joined}"
                    if is_bn
                    else f"Multiple products match. Which one do you mean?\n\n{joined}"
                )

            name = data.get("product_name")
            sku = data.get("sku")
            qty = data.get("quantity_sold", 0)
            total = float(data.get("total_sales_tk") or 0.0)
            period = data.get("date_period", "All Time")
            stock = data.get("current_stock", 0)
            if is_bn:
                return f"**{name}** (SKU: {sku}) পণ্যটি **{period}**-এ মোট **{qty}টি** বিক্রি হয়েছে, যার মোট বিক্রয়মূল্য **৳{total:,.2f}** (বর্তমান মজুদ: {stock}টি)।"
            return f"A total of **{qty} unit(s)** of **{name}** (SKU: {sku}) were sold during **{period}** totaling **৳{total:,.2f}** (Current stock: {stock})."

        # 6. Low Stock Tool
        elif tool_name == "get_low_stock_products":
            cnt = data.get("count", 0)
            products = data.get("low_stock_products", [])
            if products:
                lines = []
                for p in products[:5]:
                    lines.append(f"• **{p.get('name')}** (SKU: {p.get('sku')}): বর্তমান স্টক **{p.get('current_stock')}** (সতর্কসীমা: {p.get('reorder_level')})" if is_bn else f"• **{p.get('name')}** (SKU: {p.get('sku')}): Current Stock: **{p.get('current_stock')}** (Reorder Level: {p.get('reorder_level')})")
                items = "\n".join(lines)
                more = f"\n*(এবং আরও {cnt - 5}টি পণ্য...)*" if (is_bn and cnt > 5) else (f"\n*(and {cnt - 5} more items...)*" if cnt > 5 else "")
                if is_bn:
                    return f"বর্তমানে **{cnt}টি** পণ্যের স্টক সতর্কসীমার (Reorder Level) নিচে রয়েছে:\n\n{items}{more}"
                return f"There are currently **{cnt} product(s)** at or below their safety reorder threshold:\n\n{items}{more}"
            return "চমৎকার খবর! বর্তমানে কোনো পণ্যের স্টক সতর্কসীমার নিচে নেই।" if is_bn else "Great news! No products are currently below their reorder threshold."

        # 7. Customer Directory Tool
        elif tool_name == "search_customers":
            cnt = data.get("count", 0)
            customers = data.get("customers", [])
            if customers:
                lines = []
                for c in customers[:5]:
                    phone = c.get("phone") or "N/A"
                    ords = c.get("orders_count", 0)
                    lines.append(f"• **{c.get('name')}** - ফোন: {phone}, অর্ডার: {ords}টি" if is_bn else f"• **{c.get('name')}** - Phone: {phone}, Orders: {ords}")
                items = "\n".join(lines)
                more = f"\n*(এবং আরও {cnt - 5} জন কাস্টমার...)*" if (is_bn and cnt > 5) else (f"\n*(and {cnt - 5} more customers...)*" if cnt > 5 else "")
                if is_bn:
                    return f"আপনার ডিরেক্টরিতে **{cnt} জন** কাস্টমার পাওয়া গেছে:\n\n{items}{more}"
                return f"Found **{cnt} customer(s)** in your directory:\n\n{items}{more}"
            return "আপনার অনুসন্ধানের সাথে মিলে এমন কোনো কাস্টমার পাওয়া যায়নি।" if is_bn else "No customer records found matching your query."

        # 8. Product Search Tool
        elif tool_name == "search_products":
            cnt = data.get("count", 0)
            products = data.get("products", [])
            if products:
                lines = []
                for p in products[:5]:
                    price = p.get("price") if p.get("price") is not None else p.get("selling_price")
                    price_str = f"৳{float(price):,.2f}" if price is not None else "N/A"
                    stock = p.get("stock_quantity", 0)
                    lines.append(f"• **{p.get('name')}** (SKU: {p.get('sku')}): স্টক **{stock}**, মূল্য **{price_str}**" if is_bn else f"• **{p.get('name')}** (SKU: {p.get('sku')}): Stock: **{stock}**, Price: **{price_str}**")
                items = "\n".join(lines)
                more = f"\n*(এবং আরও {cnt - 5}টি পণ্য...)*" if (is_bn and cnt > 5) else (f"\n*(and {cnt - 5} more products...)*" if cnt > 5 else "")
                if is_bn:
                    return f"ক্যাটালগে **{cnt}টি** পণ্য পাওয়া গেছে:\n\n{items}{more}"
                return f"Found **{cnt} product(s)** in your catalog:\n\n{items}{more}"
            return "আপনার অনুসন্ধানের সাথে মিলে এমন কোনো পণ্য পাওয়া যায়নি।" if is_bn else "No products found matching your search."

        # 9. List Orders Tool
        elif tool_name == "list_orders":
            cnt = data.get("count", 0)
            orders = data.get("orders", [])
            if orders:
                lines = []
                for o in orders[:5]:
                    total = o.get("total_amount")
                    total_str = f"৳{float(total):,.2f}" if total is not None else "৳0.00"
                    lines.append(
                        f"• অর্ডার #{o.get('order_number') or o.get('id')}: মোট **{total_str}** | স্ট্যাটাস: {o.get('order_status')} | পেমেন্ট: {o.get('payment_status')}"
                        if is_bn
                        else f"• Order #{o.get('order_number') or o.get('id')}: Total **{total_str}** | Status: {o.get('order_status')} | Payment: {o.get('payment_status')}"
                    )
                items = "\n".join(lines)
                more = f"\n*(এবং আরও {cnt - 5}টি অর্ডার...)*" if (is_bn and cnt > 5) else (f"\n*(and {cnt - 5} more orders...)*" if cnt > 5 else "")
                return f"সর্বমোট **{cnt}টি** সাম্প্রতিক অর্ডার:\n\n{items}{more}" if is_bn else f"Retrieved **{cnt}** recent order(s):\n\n{items}{more}"
            return "কোনো অর্ডার পাওয়া যায়নি।" if is_bn else "No orders found."

        # 10. List Inventory Movements Tool
        elif tool_name == "list_inventory_movements":
            cnt = data.get("count", 0)
            movements = data.get("movements", [])
            if movements:
                lines = []
                for m in movements[:5]:
                    lines.append(
                        f"• {m.get('type')}: {m.get('product')}, পরিমাণ: {m.get('quantity')}, কারণ: {m.get('reason') or 'N/A'}"
                        if is_bn
                        else f"• {m.get('type')}: {m.get('product')}, Qty: {m.get('quantity')}, Reason: {m.get('reason') or 'N/A'}"
                    )
                items = "\n".join(lines)
                more = f"\n*(এবং আরও {cnt - 5}টি মুভমেন্ট...)*" if (is_bn and cnt > 5) else (f"\n*(and {cnt - 5} more movements...)*" if cnt > 5 else "")
                return f"সাম্প্রতিক **{cnt}টি** স্টক মুভমেন্ট রেকর্ড:\n\n{items}{more}" if is_bn else f"Retrieved **{cnt}** recent inventory movement audit log(s):\n\n{items}{more}"
            return "কোনো স্টক মুভমেন্ট রেকর্ড পাওয়া যায়নি।" if is_bn else "Retrieved 0 inventory stock movement logs."

        # 11. Top Sales Date Tool
        elif tool_name == "get_top_sales_date":
            if not data.get("found"):
                return (
                    f"{data.get('period', 'নির্ধারিত সময়ে')} কোনো অনুমোদিত বিক্রয় রেকর্ড পাওয়া যায়নি।"
                    if is_bn
                    else f"No verified sales records found for {data.get('period', 'the specified period')}."
                )
            d_label = data.get("top_date_formatted") or data.get("top_date")
            sales = float(data.get("total_sales_tk") or 0.0)
            orders = data.get("orders_count", 0)
            period = data.get("period", "All Time")
            if is_bn:
                return f"দোকানের ইতিহাসে ({period}) **{d_label}** তারিখে সর্বোচ্চ সেলস হয়েছিল: **৳{sales:,.2f}** (মোট {orders}টি Delivered ও Paid অর্ডারের মাধ্যমে)।"
            return f"The highest sales date on record ({period}) was **{d_label}** with total revenue of **৳{sales:,.2f}** ({orders} Delivered & Paid orders)."

        # 12. Top Selling Products Tool
        elif tool_name == "get_top_selling_products":
            if not data.get("found"):
                return "কোনো বিক্রিত পণ্যের রেকর্ড পাওয়া যায়নি।" if is_bn else "No product sales records found."
            products = data.get("products", [])
            lines = []
            for p in products:
                rev = float(p.get("total_revenue_tk", 0.0))
                units = p.get("units_sold", 0)
                lines.append(f"{p.get('rank')}. **{p.get('name')}** (SKU: {p.get('sku')}): **{units}টি** বিক্রি, মোট **৳{rev:,.2f}**" if is_bn else f"{p.get('rank')}. **{p.get('name')}** (SKU: {p.get('sku')}): **{units} units sold**, Total **৳{rev:,.2f}**")
            joined = "\n".join(lines)
            period = data.get("period", "All Time")
            if is_bn:
                return f"**{period}**-এর শীর্ষ বিক্রিত পণ্যসমূহ:\n\n{joined}"
            return f"Top selling products for **{period}**:\n\n{joined}"

        # 13. Top Customers Tool
        elif tool_name == "get_top_customers":
            if not data.get("found"):
                return "কোনো কাস্টমার বা অর্ডারের রেকর্ড পাওয়া যায়নি।" if is_bn else "No customer order records found."
            customers = data.get("customers", [])
            lines = []
            for c in customers:
                spent = float(c.get("total_spent_tk", 0.0))
                ords = c.get("total_orders", 0)
                lines.append(f"{c.get('rank')}. **{c.get('name')}** (ফোন: {c.get('phone') or 'N/A'}): মোট **{ords}টি** অর্ডার, সর্বমোট ব্যয় **৳{spent:,.2f}**" if is_bn else f"{c.get('rank')}. **{c.get('name')}** (Phone: {c.get('phone') or 'N/A'}): **{ords} orders**, Total Spent **৳{spent:,.2f}**")
            joined = "\n".join(lines)
            cnt = data.get("count", len(customers))
            if is_bn:
                return f"সর্বমোট অর্ডারের ভিত্তিতে শীর্ষ **{cnt} জন** কাস্টমার:\n\n{joined}"
            return f"Top **{cnt}** customers by total order spend:\n\n{joined}"

        # 14. Compare Sales Dates Tool
        elif tool_name == "compare_sales_dates":
            d1 = data.get("date_1", {})
            d2 = data.get("date_2", {})
            s1 = float(d1.get("sales_tk", 0.0))
            s2 = float(d2.get("sales_tk", 0.0))
            l1 = d1.get("label", "Date 1")
            l2 = d2.get("label", "Date 2")
            diff = float(data.get("difference_tk", 0.0))
            pct = data.get("percentage_change")
            diff_ords = data.get("difference_orders", 0)

            diff_str = f"+৳{diff:,.2f}" if diff > 0 else (f"-৳{abs(diff):,.2f}" if diff < 0 else "৳0.00")
            pct_str = f" ({'+' if diff > 0 else ''}{pct}%)" if pct is not None else ""
            ords_str = f"{'+' if diff_ords > 0 else ''}{diff_ords}টি" if is_bn else f"{'+' if diff_ords > 0 else ''}{diff_ords}"

            if is_bn:
                return (
                    f"### সেলস তুলনা রিপোর্ট:\n\n"
                    f"• **{l1}:** ৳{s1:,.2f} ({d1.get('orders', 0)}টি অর্ডার)\n"
                    f"• **{l2}:** ৳{s2:,.2f} ({d2.get('orders', 0)}টি অর্ডার)\n\n"
                    f"• **বিক্রয় পার্থক্য:** **{diff_str}**{pct_str}\n"
                    f"• **অর্ডার পার্থক্য:** {ords_str}"
                )
            return (
                f"### Sales Comparison Report:\n\n"
                f"• **{l1}:** ৳{s1:,.2f} ({d1.get('orders', 0)} order(s))\n"
                f"• **{l2}:** ৳{s2:,.2f} ({d2.get('orders', 0)} order(s))\n\n"
                f"• **Revenue Difference:** **{diff_str}**{pct_str}\n"
                f"• **Orders Difference:** {ords_str}"
            )

        return "তথ্য সফলভাবে উদ্ধার করা হয়েছে।" if is_bn else "Information retrieved successfully."

    async def execute_confirmation(
        self,
        action_token: str,
        user: User,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """
        Executes a pending action after explicit user confirmation.
        """
        action = await session_manager.consume_pending_action(action_token, user.id)
        if not action:
            return {
                "success": False,
                "message": "Action token is invalid, expired, or has already been executed.",
            }

        await session_manager.clear_pending_workflow(action.session_id)

        tool_def = tool_registry.get(action.tool_name)
        if not tool_def:
            return {
                "success": False,
                "message": f"Tool '{action.tool_name}' is not registered.",
            }

        try:
            result = await tool_def.handler(db, user, action.arguments)
            success_msg = f"Operation '{action.preview_title}' executed successfully."

            await session_manager.add_message(
                action.session_id,
                "assistant",
                f"✅ {success_msg}",
                tool_name=action.tool_name,
            )

            return {
                "success": True,
                "message": success_msg,
                "data": result,
            }
        except Exception as exc:
            logger.error(f"Error executing confirmed action '{action.tool_name}': {exc}", exc_info=True)
            return {
                "success": False,
                "message": f"Execution failed: {str(exc)}",
            }


ai_orchestrator = AIOrchestrator()
