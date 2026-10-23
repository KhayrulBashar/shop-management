import logging
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from pydantic import EmailStr, TypeAdapter
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.customer import Customer
from app.models.order import Order
from app.models.product import Product
from app.models.user import User
from app.services.ai.registry import tool_registry
from app.services.ai.session import session_manager

logger = logging.getLogger("shop_management.ai.workflow")

email_adapter = TypeAdapter(EmailStr)

DHAKA_TZ = timezone(datetime.now().astimezone().utcoffset() or timezone.utc.utcoffset(None))


def is_affirmative(text: str) -> bool:
    t = text.strip().lower()
    return any(w in t for w in ["yes", "y", "yeah", "yep", "sure", "ha", "ji", "হ্যাঁ", "হাঁ", "অবশ্যই", "ঠিক আছে", "হ্যা", "চাই"])


def is_negative(text: str) -> bool:
    t = text.strip().lower()
    return any(w in t for w in ["no", "n", "nope", "na", "skip", "না", "দরকার নেই", "থাক", "বাদ দাও", "স্কিপ", "পরে"])


def validate_phone_number(phone_raw: str) -> str | None:
    cleaned = phone_raw.strip()
    # If it contains letters (Bengali or English), it's not a phone number
    if re.search(r"[a-zA-Z\u0980-\u09FF]", cleaned):
        return None
    digits = re.sub(r"\D", "", cleaned)
    if 5 <= len(digits) <= 18:
        return cleaned
    return None


def validate_email_address(email_raw: str) -> str | None:
    cleaned = email_raw.strip().lower()
    try:
        validated = email_adapter.validate_python(cleaned)
        return str(validated)
    except Exception:
        return None


class ConversationalWorkflowEngine:
    """
    Reusable, multi-turn state machine managing form interactions,
    field validation, optional skipping, field-level editing, preview cards,
    and action generation for all 5 business entities.
    """

    async def handle_turn(
        self,
        session_id: str,
        user_message: str,
        workflow: dict[str, Any],
        user: User,
        db: AsyncSession,
    ) -> dict[str, Any]:
        action = workflow.get("action")
        lang = workflow.get("lang", "bn")
        is_bn = (lang == "bn")
        msg = user_message.strip()
        msg_lower = msg.lower()

        # Global Edit Details trigger from confirmation preview card
        if any(w in msg_lower for w in ["edit details", "edit", "change", "সংশোধন", "পরিবর্তন", "এডিট"]):
            workflow["step"] = "choose_edit_field"
            await session_manager.set_pending_workflow(session_id, workflow)
            return self._build_edit_field_choice_reply(workflow, is_bn)

        # Handle specific field being edited
        if workflow.get("step") == "choose_edit_field":
            return await self._handle_choose_edit_field(session_id, msg, workflow, is_bn, db, user)

        if workflow.get("step") == "enter_edit_value":
            return await self._handle_enter_edit_value(session_id, msg, workflow, is_bn, db, user)

        # Route by entity workflow
        if action == "create_customer":
            return await self._step_create_customer(session_id, msg, workflow, is_bn, db, user)
        elif action == "create_product":
            return await self._step_create_product(session_id, msg, workflow, is_bn, db, user)
        elif action == "create_order":
            return await self._step_create_order(session_id, msg, workflow, is_bn, db, user)
        elif action == "record_stock_movement":
            return await self._step_stock_movement(session_id, msg, workflow, is_bn, db, user)
        elif action == "update_order_status":
            return await self._step_update_order_status(session_id, msg, workflow, is_bn, db, user)

        return {
            "session_id": session_id,
            "response": "Workflow unrecognized. Say 'cancel' to start over." if not is_bn else "ওয়ার্কফ্লো চিনতে ব্যর্থ হয়েছে। নতুনভাবে শুরু করতে 'বাতিল' বলুন।",
            "action_required": False,
            "pending_action": None,
            "quick_replies": ["Cancel"] if not is_bn else ["বাতিল"],
        }

    # =========================================================================
    # 1. CUSTOMER CREATION WORKFLOW (Required: name, phone; Optional: email, address, notes)
    # =========================================================================
    async def start_customer_workflow(self, session_id: str, is_bn: bool, initial_name: str | None = None) -> dict[str, Any]:
        wf = {
            "action": "create_customer",
            "lang": "bn" if is_bn else "en",
            "step": "ask_phone" if initial_name else "ask_name",
            "data": {"name": initial_name} if initial_name else {},
        }
        await session_manager.set_pending_workflow(session_id, wf)

        if initial_name:
            reply = (
                f"ধন্যবাদ। এবার **'{initial_name}'**-এর ফোন নম্বরটি বলুন।"
                if is_bn
                else f"Sure. What is the contact phone number for **'{initial_name}'**?"
            )
            return {"response": reply, "quick_replies": ["Cancel"] if not is_bn else ["বাতিল"]}
        else:
            reply = (
                "আমি নতুন কাস্টমার যোগ করতে সাহায্য করতে পারি। কাস্টমারের পুরো নাম কী?"
                if is_bn
                else "Sure. What is the customer's name?"
            )
            return {"response": reply, "quick_replies": ["Cancel"] if not is_bn else ["বাতিল"]}

    async def _step_create_customer(
        self, session_id: str, msg: str, wf: dict[str, Any], is_bn: bool, db: AsyncSession, user: User
    ) -> dict[str, Any]:
        step = wf.get("step")
        data = wf.get("data", {})

        # Step 1: Collect Name
        if step == "ask_name":
            clean_name = re.sub(r"^(তার\s+নাম|নাম|নামটি|name\s+is|his\s+name\s+is|the\s+name\s+is)\s*[:=]?\s*", "", msg, flags=re.I).strip(".\"' ")
            if len(clean_name) < 2:
                reply = "অনুগ্রহ করে কাস্টমারের সঠিক নাম লিখুন (কমপক্ষে ২ অক্ষর)।" if is_bn else "Please enter a valid customer name (at least 2 characters)."
                return {"session_id": session_id, "response": reply, "quick_replies": ["Cancel"] if not is_bn else ["বাতিল"]}
            data["name"] = clean_name
            wf["step"] = "ask_phone"
            wf["data"] = data
            await session_manager.set_pending_workflow(session_id, wf)
            reply = f"ধন্যবাদ। এবার **'{clean_name}'**-এর ফোন নম্বরটি বলুন:" if is_bn else f"What is the customer's phone number?"
            return {"session_id": session_id, "response": reply, "quick_replies": ["Cancel"] if not is_bn else ["বাতিল"]}

        # Step 2: Collect Phone (Strict Validation)
        elif step == "ask_phone":
            phone_val = validate_phone_number(msg)
            if not phone_val:
                reply = (
                    "ফোন নম্বরটি সঠিক মনে হচ্ছে না। অনুগ্রহ করে একটি সঠিক ফোন নম্বর লিখুন (যেমন: 01711223344 বা +8801711223344):"
                    if is_bn
                    else "That doesn't look like a valid phone number. Please enter a valid phone number (e.g. 01711223344 or +8801711223344):"
                )
                return {"session_id": session_id, "response": reply, "quick_replies": ["Cancel"] if not is_bn else ["বাতিল"]}
            data["phone"] = phone_val
            wf["step"] = "ask_email_opt"
            wf["data"] = data
            await session_manager.set_pending_workflow(session_id, wf)
            reply = (
                f"আপনি কি **'{data.get('name')}'**-এর ইমেইল ঠিকানা যোগ করতে চান? হ্যাঁ অথবা না।"
                if is_bn
                else "Would you like to add an email address? Yes or no."
            )
            return {"session_id": session_id, "response": reply, "quick_replies": ["হ্যাঁ", "না"] if is_bn else ["Yes", "No"]}

        # Step 3: Ask Email Optional Decision
        elif step == "ask_email_opt":
            if is_affirmative(msg):
                wf["step"] = "enter_email"
                await session_manager.set_pending_workflow(session_id, wf)
                reply = "অনুগ্রহ করে ইমেইল ঠিকানাটি লিখুন (যেমন: user@example.com):" if is_bn else "Please enter the email address:"
                return {"session_id": session_id, "response": reply, "quick_replies": ["Skip"] if not is_bn else ["বাদ দিন"]}
            elif is_negative(msg):
                data["email"] = None
                wf["step"] = "ask_address_opt"
                wf["data"] = data
                await session_manager.set_pending_workflow(session_id, wf)
                reply = "আপনি কি কাস্টমারের ঠিকানা (Address) যোগ করতে চান? হ্যাঁ অথবা না।" if is_bn else "Would you like to add an address? Yes or no."
                return {"session_id": session_id, "response": reply, "quick_replies": ["হ্যাঁ", "না"] if is_bn else ["Yes", "No"]}
            else:
                reply = "অনুগ্রহ করে 'হ্যাঁ' অথবা 'না' বলুন:" if is_bn else "Please reply with Yes or No:"
                return {"session_id": session_id, "response": reply, "quick_replies": ["হ্যাঁ", "না"] if is_bn else ["Yes", "No"]}

        # Step 3b: Enter Email Value & Validate
        elif step == "enter_email":
            if is_negative(msg) or msg.lower() in ["skip", "বাদ"]:
                data["email"] = None
            else:
                email_val = validate_email_address(msg)
                if not email_val:
                    reply = (
                        "ইমেইল ঠিকানাটি সঠিক নয় (যেমন: user@example.com)। অনুগ্রহ করে সঠিক ইমেইল লিখুন অথবা 'skip' বলুন:"
                        if is_bn
                        else "That doesn't look like a valid email address (e.g. user@example.com). Please enter a valid email or say 'skip':"
                    )
                    return {"session_id": session_id, "response": reply, "quick_replies": ["Skip"] if not is_bn else ["বাদ দিন"]}
                data["email"] = email_val

            wf["step"] = "ask_address_opt"
            wf["data"] = data
            await session_manager.set_pending_workflow(session_id, wf)
            reply = "আপনি কি কাস্টমারের ঠিকানা (Address) যোগ করতে চান? হ্যাঁ অথবা না।" if is_bn else "Would you like to add an address? Yes or no."
            return {"session_id": session_id, "response": reply, "quick_replies": ["হ্যাঁ", "না"] if is_bn else ["Yes", "No"]}

        # Step 4: Ask Address Optional Decision
        elif step == "ask_address_opt":
            if is_affirmative(msg):
                wf["step"] = "enter_address"
                await session_manager.set_pending_workflow(session_id, wf)
                reply = "অনুগ্রহ করে ঠিকানাটি লিখুন:" if is_bn else "Please enter the address:"
                return {"session_id": session_id, "response": reply, "quick_replies": ["Skip"] if not is_bn else ["বাদ দিন"]}
            elif is_negative(msg):
                data["address"] = None
                wf["step"] = "ask_notes_opt"
                wf["data"] = data
                await session_manager.set_pending_workflow(session_id, wf)
                reply = "আপনি কি কোনো বিশেষ নোট (Notes) যোগ করতে চান? হ্যাঁ অথবা না।" if is_bn else "Would you like to add any notes? Yes or no."
                return {"session_id": session_id, "response": reply, "quick_replies": ["হ্যাঁ", "না"] if is_bn else ["Yes", "No"]}
            else:
                reply = "অনুগ্রহ করে 'হ্যাঁ' অথবা 'না' বলুন:" if is_bn else "Please reply with Yes or No:"
                return {"session_id": session_id, "response": reply, "quick_replies": ["হ্যাঁ", "না"] if is_bn else ["Yes", "No"]}

        # Step 4b: Enter Address Value
        elif step == "enter_address":
            if is_negative(msg) or msg.lower() in ["skip", "বাদ"]:
                data["address"] = None
            else:
                data["address"] = msg.strip()

            wf["step"] = "ask_notes_opt"
            wf["data"] = data
            await session_manager.set_pending_workflow(session_id, wf)
            reply = "আপনি কি কোনো বিশেষ নোট (Notes) যোগ করতে চান? হ্যাঁ অথবা না।" if is_bn else "Would you like to add any notes? Yes or no."
            return {"session_id": session_id, "response": reply, "quick_replies": ["হ্যাঁ", "না"] if is_bn else ["Yes", "No"]}

        # Step 5: Ask Notes Optional Decision
        elif step == "ask_notes_opt":
            if is_affirmative(msg):
                wf["step"] = "enter_notes"
                await session_manager.set_pending_workflow(session_id, wf)
                reply = "নোটটি লিখুন:" if is_bn else "Please enter the notes:"
                return {"session_id": session_id, "response": reply, "quick_replies": ["Skip"] if not is_bn else ["বাদ দিন"]}
            elif is_negative(msg):
                data["notes"] = None
                wf["step"] = "preview"
                wf["data"] = data
                await session_manager.set_pending_workflow(session_id, wf)
                return await self._generate_customer_preview(session_id, data, is_bn, user)
            else:
                reply = "অনুগ্রহ করে 'হ্যাঁ' অথবা 'না' বলুন:" if is_bn else "Please reply with Yes or No:"
                return {"session_id": session_id, "response": reply, "quick_replies": ["হ্যাঁ", "না"] if is_bn else ["Yes", "No"]}

        # Step 5b: Enter Notes Value
        elif step == "enter_notes":
            if is_negative(msg) or msg.lower() in ["skip", "বাদ"]:
                data["notes"] = None
            else:
                data["notes"] = msg.strip()

            wf["step"] = "preview"
            wf["data"] = data
            await session_manager.set_pending_workflow(session_id, wf)
            return await self._generate_customer_preview(session_id, data, is_bn, user)

        return {"session_id": session_id, "response": "In preview state. Please confirm or edit.", "quick_replies": ["Confirm and Create", "Edit Details", "Cancel"]}

    async def _generate_customer_preview(
        self, session_id: str, data: dict[str, Any], is_bn: bool, user: User
    ) -> dict[str, Any]:
        tool_name = "create_customer"
        tool_args = {
            "name": data.get("name"),
            "phone": data.get("phone"),
            "email": data.get("email"),
            "address": data.get("address"),
            "notes": data.get("notes"),
        }
        tool_def = tool_registry.get(tool_name)
        title, summary, details = tool_def.preview_generator(tool_args)

        action = await session_manager.create_pending_action(
            session_id=session_id,
            user_id=user.id,
            tool_name=tool_name,
            arguments=tool_args,
            preview_title=title,
            preview_summary=summary,
            preview_details=details,
        )

        email_disp = data.get("email") or ("প্রদান করা হয়নি" if is_bn else "Not provided")
        addr_disp = data.get("address") or ("প্রদান করা হয়নি" if is_bn else "Not provided")
        notes_disp = data.get("notes") or ("প্রদান করা হয়নি" if is_bn else "Not provided")

        if is_bn:
            preview_text = (
                f"### কাস্টমার প্রিভিউ (Customer Preview)\n\n"
                f"• **নাম:** {data.get('name')}\n"
                f"• **ফোন নম্বর:** {data.get('phone')}\n"
                f"• **ইমেইল:** {email_disp}\n"
                f"• **ঠিকানা:** {addr_disp}\n"
                f"• **নোট:** {notes_disp}\n\n"
                f"তথ্যগুলো যাচাই করে নিচে দেয়া অ্যাকশন বেছে নিন:"
            )
            quick_replies = ["Confirm and Create", "Edit Details", "Cancel"]
        else:
            preview_text = (
                f"### Customer Preview\n\n"
                f"• **Name:** {data.get('name')}\n"
                f"• **Phone:** {data.get('phone')}\n"
                f"• **Email:** {email_disp}\n"
                f"• **Address:** {addr_disp}\n"
                f"• **Notes:** {notes_disp}\n\n"
                f"Please review the details below. Choose an action to proceed:"
            )
            quick_replies = ["Confirm and Create", "Edit Details", "Cancel"]

        return {
            "session_id": session_id,
            "response": preview_text,
            "action_required": True,
            "pending_action": {
                "action_token": action.action_token,
                "title": action.preview_title,
                "summary": action.preview_summary,
                "details": action.preview_details,
                "expires_at": action.expires_at.isoformat(),
            },
            "quick_replies": quick_replies,
        }

    # =========================================================================
    # 2. PRODUCT CREATION WORKFLOW (name, sku, category, price, stock, reorder)
    # =========================================================================
    async def start_product_workflow(self, session_id: str, is_bn: bool, initial_name: str | None = None) -> dict[str, Any]:
        wf = {
            "action": "create_product",
            "lang": "bn" if is_bn else "en",
            "step": "ask_sku" if initial_name else "ask_name",
            "data": {"name": initial_name} if initial_name else {},
        }
        await session_manager.set_pending_workflow(session_id, wf)

        if initial_name:
            reply = (
                f"নতুন পণ্যের নাম **'{initial_name}'** সংরক্ষিত হয়েছে। এবার পণ্যটির একটি ইউনিক **SKU** কোড লিখুন (যেমন: MOUSE-W-01):"
                if is_bn
                else f"Product name set to **'{initial_name}'**. Please enter a unique **SKU** code (e.g. MOUSE-W-01):"
            )
        else:
            reply = (
                "আমি নতুন প্রোডাক্ট যোগ করতে সাহায্য করতে পারি। পণ্যের নাম (Product Name) কী?"
                if is_bn
                else "I can help you add a new product. What is the product name?"
            )
        return {"response": reply, "quick_replies": ["Cancel"] if not is_bn else ["বাতিল"]}

    async def _step_create_product(
        self, session_id: str, msg: str, wf: dict[str, Any], is_bn: bool, db: AsyncSession, user: User
    ) -> dict[str, Any]:
        step = wf.get("step")
        data = wf.get("data", {})

        # Step 1: Product Name
        if step == "ask_name":
            clean_name = msg.strip(".\"' ")
            if len(clean_name) < 2:
                reply = "অনুগ্রহ করে সঠিক পণ্যের নাম লিখুন (কমপক্ষে ২ অক্ষর)।" if is_bn else "Please enter a valid product name (at least 2 characters)."
                return {"session_id": session_id, "response": reply, "quick_replies": ["Cancel"] if not is_bn else ["বাতিল"]}
            data["name"] = clean_name
            wf["step"] = "ask_sku"
            wf["data"] = data
            await session_manager.set_pending_workflow(session_id, wf)
            reply = f"ধন্যবাদ। এবার **'{clean_name}'**-এর জন্য একটি ইউনিক **SKU** কোড লিখুন (যেমন: ELEC-001):" if is_bn else f"Thank you. What is the unique SKU for **'{clean_name}'**?"
            return {"session_id": session_id, "response": reply, "quick_replies": ["Cancel"] if not is_bn else ["বাতিল"]}

        # Step 2: SKU Validation (Uniqueness check in DB)
        elif step == "ask_sku":
            clean_sku = msg.strip().upper()
            if len(clean_sku) < 2:
                reply = "SKU কোড কমপক্ষে ২ অক্ষরের হতে হবে।" if is_bn else "SKU code must be at least 2 characters."
                return {"session_id": session_id, "response": reply, "quick_replies": ["Cancel"] if not is_bn else ["বাতিল"]}

            res = await db.execute(select(Product).where(Product.sku == clean_sku, Product.is_deleted == False))
            existing = res.scalar_one_or_none()
            if existing:
                reply = (
                    f"সতর্কতা: **'{clean_sku}'** SKU-টি ইতিমধ্যে **'{existing.name}'** পণ্যে ব্যবহার করা হয়েছে! অনুগ্রহ করে একটি ভিন্ন ইউনিক SKU দিন:"
                    if is_bn
                    else f"SKU **'{clean_sku}'** already exists for product **'{existing.name}'**! Please enter a unique SKU:"
                )
                return {"session_id": session_id, "response": reply, "quick_replies": ["Cancel"] if not is_bn else ["বাতিল"]}

            data["sku"] = clean_sku
            wf["step"] = "ask_category"
            wf["data"] = data
            await session_manager.set_pending_workflow(session_id, wf)
            reply = (
                f"পণ্যের ক্যাটাগরি (Category) কী হবে? (যেমন: Electronics, Accessories, অথবা সরাসরি এন্টার করতে 'General' বলতে পারেন)"
                if is_bn
                else "What category does this product belong to? (e.g. Electronics, Accessories, or reply 'General'):"
            )
            return {"session_id": session_id, "response": reply, "quick_replies": ["General", "Electronics", "Accessories"]}

        # Step 3: Category
        elif step == "ask_category":
            cat = msg.strip() or "General"
            data["category"] = cat
            wf["step"] = "ask_price"
            wf["data"] = data
            await session_manager.set_pending_workflow(session_id, wf)
            reply = f"পণ্যটির বিক্রয়মূল্য (Selling Price) কত টাকা?" if is_bn else "What is the selling price for this product (in ৳)?"
            return {"session_id": session_id, "response": reply, "quick_replies": ["Cancel"] if not is_bn else ["বাতিল"]}

        # Step 4: Price (> 0)
        elif step == "ask_price":
            price_match = re.search(r"(\d+(?:\.\d+)?)", msg)
            if not price_match or float(price_match.group(1)) <= 0:
                reply = "অনুগ্রহ করে একটি সঠিক মূল্য লিখুন (০-এর বেশি, যেমন: 250 বা 1200.50):" if is_bn else "Please enter a valid price greater than 0 (e.g. 250 or 1200.50):"
                return {"session_id": session_id, "response": reply, "quick_replies": ["Cancel"] if not is_bn else ["বাতিল"]}
            data["price"] = float(price_match.group(1))
            wf["step"] = "ask_stock"
            wf["data"] = data
            await session_manager.set_pending_workflow(session_id, wf)
            reply = "প্রারম্ভিক স্টক (Initial Stock Quantity) কত? (ডিফল্ট 0):" if is_bn else "What is the initial stock quantity? (default 0):"
            return {"session_id": session_id, "response": reply, "quick_replies": ["0", "10", "50", "100"]}

        # Step 5: Initial Stock (>= 0)
        elif step == "ask_stock":
            stock_match = re.search(r"(\d+)", msg)
            stock_qty = int(stock_match.group(1)) if stock_match else 0
            data["stock_quantity"] = stock_qty
            wf["step"] = "ask_reorder"
            wf["data"] = data
            await session_manager.set_pending_workflow(session_id, wf)
            reply = "রি-অর্ডার সতর্কতা সীমা (Reorder Level) কত রাখবেন? (ডিফল্ট 5):" if is_bn else "What is the reorder alert threshold level? (default 5):"
            return {"session_id": session_id, "response": reply, "quick_replies": ["5", "10", "15"]}

        # Step 6: Reorder Level (>= 0) & Preview
        elif step == "ask_reorder":
            reorder_match = re.search(r"(\d+)", msg)
            reorder_qty = int(reorder_match.group(1)) if reorder_match else 5
            data["reorder_level"] = reorder_qty
            wf["step"] = "preview"
            wf["data"] = data
            await session_manager.set_pending_workflow(session_id, wf)
            return await self._generate_product_preview(session_id, data, is_bn, user)

        return {"session_id": session_id, "response": "In preview state.", "quick_replies": ["Confirm and Create", "Edit Details", "Cancel"]}

    async def _generate_product_preview(
        self, session_id: str, data: dict[str, Any], is_bn: bool, user: User
    ) -> dict[str, Any]:
        tool_name = "create_product"
        tool_args = {
            "name": data.get("name"),
            "sku": data.get("sku"),
            "category": data.get("category", "General"),
            "price": float(data.get("price", 0.0)),
            "stock_quantity": int(data.get("stock_quantity", 0)),
            "reorder_level": int(data.get("reorder_level", 5)),
        }
        tool_def = tool_registry.get(tool_name)
        title, summary, details = tool_def.preview_generator(tool_args)

        action = await session_manager.create_pending_action(
            session_id=session_id,
            user_id=user.id,
            tool_name=tool_name,
            arguments=tool_args,
            preview_title=title,
            preview_summary=summary,
            preview_details=details,
        )

        if is_bn:
            preview_text = (
                f"### পণ্য প্রিভিউ (Product Preview)\n\n"
                f"• **পণ্যের নাম:** {data.get('name')}\n"
                f"• **SKU কোড:** {data.get('sku')}\n"
                f"• **ক্যাটাগরি:** {data.get('category')}\n"
                f"• **বিক্রয়মূল্য:** ৳{data.get('price'):,.2f}\n"
                f"• **প্রারম্ভিক স্টক:** {data.get('stock_quantity')}টি\n"
                f"• **সতর্কসীমা (Reorder Level):** {data.get('reorder_level')}টি\n\n"
                f"তথ্যগুলো যাচাই করে নিচের অপশন থেকে নির্বাচন করুন:"
            )
        else:
            preview_text = (
                f"### Product Preview\n\n"
                f"• **Product Name:** {data.get('name')}\n"
                f"• **SKU:** {data.get('sku')}\n"
                f"• **Category:** {data.get('category')}\n"
                f"• **Price:** ৳{data.get('price'):,.2f}\n"
                f"• **Initial Stock:** {data.get('stock_quantity')} unit(s)\n"
                f"• **Reorder Level:** {data.get('reorder_level')} unit(s)\n\n"
                f"Please review the details below. Choose an action to proceed:"
            )

        return {
            "session_id": session_id,
            "response": preview_text,
            "action_required": True,
            "pending_action": {
                "action_token": action.action_token,
                "title": action.preview_title,
                "summary": action.preview_summary,
                "details": action.preview_details,
                "expires_at": action.expires_at.isoformat(),
            },
            "quick_replies": ["Confirm and Create", "Edit Details", "Cancel"],
        }

    # =========================================================================
    # 3. ORDER CREATION WORKFLOW (Customer selection, Product & Stock check, line items)
    # =========================================================================
    async def start_order_workflow(self, session_id: str, is_bn: bool) -> dict[str, Any]:
        wf = {
            "action": "create_order",
            "lang": "bn" if is_bn else "en",
            "step": "ask_customer",
            "data": {"items": []},
        }
        await session_manager.set_pending_workflow(session_id, wf)
        reply = (
            "নতুন অর্ডার তৈরির প্রক্রিয়া শুরু করা হয়েছে। কোন কাস্টমার অর্ডারটি করছেন? (কাস্টমারের নাম বা ফোন নম্বর বলুন):"
            if is_bn
            else "Starting new order creation. Which customer is placing this order? (Please provide customer name or phone number):"
        )
        return {"response": reply, "quick_replies": ["Cancel"] if not is_bn else ["বাতিল"]}

    async def _step_create_order(
        self, session_id: str, msg: str, wf: dict[str, Any], is_bn: bool, db: AsyncSession, user: User
    ) -> dict[str, Any]:
        step = wf.get("step")
        data = wf.get("data", {})

        # Step 1: Customer Selection
        if step == "ask_customer":
            q = msg.strip()
            res = await db.execute(
                select(Customer).where(
                    Customer.is_deleted == False,
                    or_(Customer.name.ilike(f"%{q}%"), Customer.phone.ilike(f"%{q}%"))
                )
            )
            matches = res.scalars().all()
            if not matches:
                reply = (
                    f"**'{q}'** নামে কোনো কাস্টমার পাওয়া যায়নি। অনুগ্রহ করে অন্য নাম/ফোন দিয়ে চেষ্টা করুন, অথবা 'cancel' বলুন:"
                    if is_bn
                    else f"No customer found matching **'{q}'**. Please try another name or phone, or say 'cancel':"
                )
                return {"session_id": session_id, "response": reply, "quick_replies": ["Cancel"] if not is_bn else ["বাতিল"]}

            if len(matches) > 1:
                wf["customer_candidates"] = [{"id": c.id, "name": c.name, "phone": c.phone} for c in matches[:4]]
                wf["step"] = "select_customer_candidate"
                await session_manager.set_pending_workflow(session_id, wf)
                lines = [f"{i}. **{c.name}** (ফোন: {c.phone})" for i, c in enumerate(matches[:4], 1)]
                reply = (
                    f"একাধিক কাস্টমার পাওয়া গেছে। আপনি কোনজনকে নির্বাচন করতে চান? (নম্বর বা নাম বলুন):\n\n" + "\n".join(lines)
                    if is_bn
                    else "Multiple matching customers found. Which one would you like to select?\n\n" + "\n".join(lines)
                )
                return {"session_id": session_id, "response": reply, "quick_replies": [f"{i}. {c.name}" for i, c in enumerate(matches[:4], 1)]}

            c = matches[0]
            data["customer_id"] = c.id
            data["customer_name"] = c.name
            data["customer_phone"] = c.phone
            wf["step"] = "ask_product"
            wf["data"] = data
            await session_manager.set_pending_workflow(session_id, wf)
            reply = (
                f"কাস্টমার **'{c.name}'** ({c.phone}) নির্বাচিত হয়েছেন।\n\nএবার অর্ডারের প্রথম পণ্যটির নাম বা SKU বলুন:"
                if is_bn
                else f"Selected customer: **'{c.name}'** ({c.phone}).\n\nWhat is the first product to add? (Enter product name or SKU):"
            )
            return {"session_id": session_id, "response": reply, "quick_replies": ["Cancel"] if not is_bn else ["বাতিল"]}

        # Step 1b: Disambiguate customer
        elif step == "select_customer_candidate":
            cands = wf.get("customer_candidates", [])
            selected = None
            m_num = re.search(r"^(\d+)", msg)
            if m_num:
                idx = int(m_num.group(1)) - 1
                if 0 <= idx < len(cands):
                    selected = cands[idx]
            if not selected:
                for c in cands:
                    if c["name"].lower() in msg.lower():
                        selected = c
                        break
            if not selected:
                reply = "অনুগ্রহ করে তালিকার নম্বর বা সঠিক নাম নির্বাচন করুন:" if is_bn else "Please choose from the candidate list:"
                return {"session_id": session_id, "response": reply, "quick_replies": [f"{i}. {c['name']}" for i, c in enumerate(cands, 1)]}

            data["customer_id"] = selected["id"]
            data["customer_name"] = selected["name"]
            data["customer_phone"] = selected["phone"]
            wf["step"] = "ask_product"
            wf["data"] = data
            await session_manager.set_pending_workflow(session_id, wf)
            reply = (
                f"কাস্টমার **'{selected['name']}'** নির্বাচিত হয়েছেন। এবার পণ্যের নাম বা SKU বলুন:"
                if is_bn
                else f"Selected customer **'{selected['name']}'**. Please enter the product name or SKU to add:"
            )
            return {"session_id": session_id, "response": reply, "quick_replies": ["Cancel"] if not is_bn else ["বাতিল"]}

        # Step 2: Product Search & Selection
        elif step == "ask_product":
            p_q = msg.strip()
            res = await db.execute(
                select(Product).where(
                    Product.is_deleted == False,
                    or_(Product.name.ilike(f"%{p_q}%"), Product.sku.ilike(f"%{p_q}%"))
                )
            )
            p_matches = res.scalars().all()
            if not p_matches:
                reply = (
                    f"**'{p_q}'** পণ্যটি পাওয়া যায়নি। অনুগ্রহ করে সঠিক নাম বা SKU দিয়ে চেষ্টা করুন:"
                    if is_bn
                    else f"No product found matching **'{p_q}'**. Please enter a valid product name or SKU:"
                )
                return {"session_id": session_id, "response": reply, "quick_replies": ["Cancel"] if not is_bn else ["বাতিল"]}

            if len(p_matches) > 1:
                wf["product_candidates"] = [{"id": p.id, "name": p.name, "sku": p.sku, "price": float(p.price), "stock": p.stock_quantity} for p in p_matches[:4]]
                wf["step"] = "select_product_candidate"
                await session_manager.set_pending_workflow(session_id, wf)
                lines = [f"{i}. **{p.name}** (SKU: {p.sku}, স্টক: {p.stock_quantity}টি, মূল্য: ৳{float(p.price):,.2f})" for i, p in enumerate(p_matches[:4], 1)]
                reply = (
                    "একাধিক পণ্য পাওয়া গেছে। আপনি কোনটি যুক্ত করতে চান?:\n\n" + "\n".join(lines)
                    if is_bn
                    else "Multiple products found. Which one would you like to add?:\n\n" + "\n".join(lines)
                )
                return {"session_id": session_id, "response": reply, "quick_replies": [f"{i}. {p.name}" for i, p in enumerate(p_matches[:4], 1)]}

            prod = p_matches[0]
            if prod.stock_quantity <= 0:
                reply = (
                    f"দুঃখিত, **'{prod.name}'** পণ্যটি বর্তমানে স্টক আউট (মজুদ: 0)। অন্য কোনো পণ্য যোগ করতে পারেন:"
                    if is_bn
                    else f"Sorry, **'{prod.name}'** is currently out of stock (Stock: 0). Please select another product:"
                )
                return {"session_id": session_id, "response": reply, "quick_replies": ["Cancel"] if not is_bn else ["বাতিল"]}

            wf["current_item"] = {
                "product_id": prod.id,
                "product_name": prod.name,
                "sku": prod.sku,
                "unit_price": float(prod.price),
                "available_stock": prod.stock_quantity,
            }
            wf["step"] = "ask_quantity"
            await session_manager.set_pending_workflow(session_id, wf)
            reply = (
                f"**'{prod.name}'** (বর্তমান স্টক: {prod.stock_quantity}টি, প্রতি ইউনিট ৳{float(prod.price):,.2f})। কত পিস অর্ডার করবেন?"
                if is_bn
                else f"**'{prod.name}'** (Available stock: {prod.stock_quantity}, Price: ৳{float(prod.price):,.2f}). What quantity do you want to order?"
            )
            return {"session_id": session_id, "response": reply, "quick_replies": ["1", "2", "5", "10"]}

        # Step 2b: Disambiguate product
        elif step == "select_product_candidate":
            cands = wf.get("product_candidates", [])
            selected = None
            m_num = re.search(r"^(\d+)", msg)
            if m_num:
                idx = int(m_num.group(1)) - 1
                if 0 <= idx < len(cands):
                    selected = cands[idx]
            if not selected:
                for p in cands:
                    if p["name"].lower() in msg.lower() or p["sku"].lower() in msg.lower():
                        selected = p
                        break
            if not selected:
                reply = "অনুগ্রহ করে তালিকার নম্বর বা সঠিক পণ্যের নাম বেছে নিন:" if is_bn else "Please choose a product from the list:"
                return {"session_id": session_id, "response": reply, "quick_replies": [f"{i}. {p['name']}" for i, p in enumerate(cands, 1)]}

            if selected["stock"] <= 0:
                reply = (
                    f"দুঃখিত, **'{selected['name']}'** বর্তমানে স্টক আউট (মজুদ: 0)। অন্য কোনো পণ্য নির্বাচন করুন:"
                    if is_bn
                    else f"Sorry, **'{selected['name']}'** is out of stock (Stock: 0). Please select another product:"
                )
                return {"session_id": session_id, "response": reply, "quick_replies": ["Cancel"] if not is_bn else ["বাতিল"]}

            wf["current_item"] = {
                "product_id": selected["id"],
                "product_name": selected["name"],
                "sku": selected["sku"],
                "unit_price": selected["price"],
                "available_stock": selected["stock"],
            }
            wf["step"] = "ask_quantity"
            await session_manager.set_pending_workflow(session_id, wf)
            reply = (
                f"**'{selected['name']}'** (বর্তমান স্টক: {selected['stock']}টি, মূল্য: ৳{selected['price']:,.2f})। কত পিস অর্ডার করবেন?"
                if is_bn
                else f"**'{selected['name']}'** (Available stock: {selected['stock']}, Price: ৳{selected['price']:,.2f}). What quantity do you want to order?"
            )
            return {"session_id": session_id, "response": reply, "quick_replies": ["1", "2", "5", "10"]}

        # Step 3: Quantity Validation against Stock
        elif step == "ask_quantity":
            q_match = re.search(r"(\d+)", msg)
            if not q_match or int(q_match.group(1)) <= 0:
                reply = "অনুগ্রহ করে কমপক্ষে ১ বা তার বেশি পরিমাণ লিখুন:" if is_bn else "Please enter a valid quantity of 1 or more:"
                return {"session_id": session_id, "response": reply, "quick_replies": ["1", "2", "5"]}

            qty = int(q_match.group(1))
            cur_item = wf.get("current_item", {})
            avail = cur_item.get("available_stock", 0)
            if qty > avail:
                reply = (
                    f"অপর্যাপ্ত স্টক! **'{cur_item.get('product_name')}'**-এর বর্তমান স্টক মাত্র **{avail}টি**। অনুগ্রহ করে {avail} বা তার কম পরিমাণ লিখুন:"
                    if is_bn
                    else f"Insufficient stock! Only **{avail} unit(s)** available for **'{cur_item.get('product_name')}'**. Please enter {avail} or less:"
                )
                return {"session_id": session_id, "response": reply, "quick_replies": [str(min(avail, n)) for n in [1, 2, avail]]}

            cur_item["quantity"] = qty
            cur_item["line_total"] = round(qty * cur_item["unit_price"], 2)
            data.setdefault("items", []).append(cur_item)
            wf["current_item"] = None
            wf["data"] = data
            wf["step"] = "ask_more_items"
            await session_manager.set_pending_workflow(session_id, wf)
            reply = (
                f"**'{cur_item['product_name']}'** x {qty} = ৳{cur_item['line_total']:,.2f} যুক্ত হয়েছে।\n\nআপনি কি এই অর্ডারে আরও পণ্য যোগ করতে চান? হ্যাঁ অথবা না।"
                if is_bn
                else f"Added **'{cur_item['product_name']}'** x {qty} = ৳{cur_item['line_total']:,.2f}.\n\nWould you like to add another product to this order? Yes or no."
            )
            return {"session_id": session_id, "response": reply, "quick_replies": ["হ্যাঁ", "না"] if is_bn else ["Yes", "No"]}

        # Step 4: Add More Items Decision
        elif step == "ask_more_items":
            if is_affirmative(msg):
                wf["step"] = "ask_product"
                await session_manager.set_pending_workflow(session_id, wf)
                reply = "পরবর্তী পণ্যের নাম বা SKU বলুন:" if is_bn else "Please enter the next product name or SKU:"
                return {"session_id": session_id, "response": reply, "quick_replies": ["Cancel"] if not is_bn else ["বাতিল"]}
            else:
                wf["step"] = "ask_notes_opt"
                await session_manager.set_pending_workflow(session_id, wf)
                reply = "অর্ডারটিতে কোনো নোট (Notes) যোগ করতে চান? হ্যাঁ অথবা না।" if is_bn else "Would you like to add order notes? Yes or no."
                return {"session_id": session_id, "response": reply, "quick_replies": ["হ্যাঁ", "না"] if is_bn else ["Yes", "No"]}

        # Step 5: Optional Notes
        elif step == "ask_notes_opt":
            if is_affirmative(msg):
                wf["step"] = "enter_notes"
                await session_manager.set_pending_workflow(session_id, wf)
                reply = "নোটটি লিখুন:" if is_bn else "Please enter the order notes:"
                return {"session_id": session_id, "response": reply, "quick_replies": ["Skip"] if not is_bn else ["বাদ দিন"]}
            else:
                data["notes"] = None
                wf["step"] = "preview"
                wf["data"] = data
                await session_manager.set_pending_workflow(session_id, wf)
                return await self._generate_order_preview(session_id, data, is_bn, user)

        elif step == "enter_notes":
            if is_negative(msg) or msg.lower() in ["skip", "বাদ"]:
                data["notes"] = None
            else:
                data["notes"] = msg.strip()

            wf["step"] = "preview"
            wf["data"] = data
            await session_manager.set_pending_workflow(session_id, wf)
            return await self._generate_order_preview(session_id, data, is_bn, user)

        return {"session_id": session_id, "response": "In preview state.", "quick_replies": ["Confirm Order", "Edit Order", "Cancel"]}

    async def _generate_order_preview(
        self, session_id: str, data: dict[str, Any], is_bn: bool, user: User
    ) -> dict[str, Any]:
        items = data.get("items", [])
        total_amount = sum(item.get("line_total", 0.0) for item in items)
        data["total_amount"] = total_amount

        tool_name = "create_order"
        tool_args = {
            "customer_id": data.get("customer_id"),
            "items": [{"product_id": it["product_id"], "quantity": it["quantity"]} for it in items],
            "order_status": data.get("order_status", "Pending"),
            "payment_status": data.get("payment_status", "Unpaid"),
            "notes": data.get("notes"),
        }
        tool_def = tool_registry.get(tool_name)
        title, summary, details = tool_def.preview_generator(tool_args)

        action = await session_manager.create_pending_action(
            session_id=session_id,
            user_id=user.id,
            tool_name=tool_name,
            arguments=tool_args,
            preview_title=title,
            preview_summary=summary,
            preview_details=details,
        )

        item_lines = [
            f"• **{it['product_name']}** (SKU: {it['sku']}) — {it['quantity']}টি x ৳{it['unit_price']:,.2f} = **৳{it['line_total']:,.2f}**"
            for it in items
        ]
        joined_items = "\n".join(item_lines)

        if is_bn:
            preview_text = (
                f"### অর্ডার প্রিভিউ (Order Preview)\n\n"
                f"• **কাস্টমার:** {data.get('customer_name')} ({data.get('customer_phone')})\n"
                f"• **অর্ডার স্ট্যাটাস:** {data.get('order_status', 'Pending')}\n"
                f"• **পেমেন্ট স্ট্যাটাস:** {data.get('payment_status', 'Unpaid')}\n"
                f"• **নোট:** {data.get('notes') or 'প্রদান করা হয়নি'}\n\n"
                f"**অর্ডার আইটেমসমূহ:**\n{joined_items}\n\n"
                f"• **সর্বমোট মূল্য (Total Amount):** **৳{total_amount:,.2f}**\n\n"
                f"অর্ডারটি চূড়ান্ত করতে নিচে দেয়া অ্যাকশন বেছে নিন:"
            )
        else:
            preview_text = (
                f"### Order Preview\n\n"
                f"• **Customer:** {data.get('customer_name')} ({data.get('customer_phone')})\n"
                f"• **Order Status:** {data.get('order_status', 'Pending')}\n"
                f"• **Payment Status:** {data.get('payment_status', 'Unpaid')}\n"
                f"• **Notes:** {data.get('notes') or 'Not provided'}\n\n"
                f"**Items:**\n{joined_items}\n\n"
                f"• **Total Amount:** **৳{total_amount:,.2f}**\n\n"
                f"Please review the order details and choose an action to proceed:"
            )

        return {
            "session_id": session_id,
            "response": preview_text,
            "action_required": True,
            "pending_action": {
                "action_token": action.action_token,
                "title": action.preview_title,
                "summary": action.preview_summary,
                "details": action.preview_details,
                "expires_at": action.expires_at.isoformat(),
            },
            "quick_replies": ["Confirm Order", "Edit Order", "Cancel"],
        }

    # =========================================================================
    # 4. STOCK MOVEMENT WORKFLOW (Product, Type: IN/OUT/ADJUSTMENT, Qty, Reason)
    # =========================================================================
    async def start_stock_movement_workflow(self, session_id: str, is_bn: bool) -> dict[str, Any]:
        wf = {
            "action": "record_stock_movement",
            "lang": "bn" if is_bn else "en",
            "step": "ask_product",
            "data": {},
        }
        await session_manager.set_pending_workflow(session_id, wf)
        reply = (
            "স্টক মুভমেন্ট রেকর্ড করার প্রক্রিয়া শুরু হয়েছে। কোন পণ্যের স্টক পরিবর্তন করতে চান? (পণ্যের নাম বা SKU বলুন):"
            if is_bn
            else "Starting inventory stock movement. Which product would you like to update? (Enter product name or SKU):"
        )
        return {"response": reply, "quick_replies": ["Cancel"] if not is_bn else ["বাতিল"]}

    async def _step_stock_movement(
        self, session_id: str, msg: str, wf: dict[str, Any], is_bn: bool, db: AsyncSession, user: User
    ) -> dict[str, Any]:
        step = wf.get("step")
        data = wf.get("data", {})

        # Step 1: Product Selection
        if step == "ask_product":
            q = msg.strip()
            res = await db.execute(
                select(Product).where(
                    Product.is_deleted == False,
                    or_(Product.name.ilike(f"%{q}%"), Product.sku.ilike(f"%{q}%"))
                )
            )
            matches = res.scalars().all()
            if not matches:
                reply = (
                    f"**'{q}'** পণ্যটি পাওয়া যায়নি। সঠিক নাম বা SKU লিখুন:"
                    if is_bn
                    else f"No product found matching **'{q}'**. Please enter a valid name or SKU:"
                )
                return {"session_id": session_id, "response": reply, "quick_replies": ["Cancel"] if not is_bn else ["বাতিল"]}

            prod = matches[0]
            data["product_id"] = prod.id
            data["product_name"] = prod.name
            data["sku"] = prod.sku
            data["current_stock"] = prod.stock_quantity
            wf["step"] = "ask_movement_type"
            wf["data"] = data
            await session_manager.set_pending_workflow(session_id, wf)
            reply = (
                f"পণ্য: **'{prod.name}'** (বর্তমান মজুদ: {prod.stock_quantity}টি)।\nমুভমেন্টের ধরন কী হবে?\n• **IN** (স্টক ইন / পণ্য গ্রহণ)\n• **OUT** (স্টক আউট / বিক্রয় বা অপসারণ)\n• **ADJUSTMENT** (স্টক সমন্বয়)"
                if is_bn
                else f"Product: **'{prod.name}'** (Current stock: {prod.stock_quantity}). What type of movement?\n• **IN** (Stock received)\n• **OUT** (Stock removed)\n• **ADJUSTMENT** (Stock corrected)"
            )
            return {"session_id": session_id, "response": reply, "quick_replies": ["IN", "OUT", "ADJUSTMENT"]}

        # Step 2: Movement Type
        elif step == "ask_movement_type":
            m_type = msg.strip().upper()
            if "IN" in m_type or "ইন" in m_type:
                m_type = "IN"
            elif "OUT" in m_type or "আউট" in m_type:
                m_type = "OUT"
            elif "ADJUST" in m_type or "সমন্বয়" in m_type:
                m_type = "ADJUSTMENT"
            else:
                reply = "অনুগ্রহ করে IN, OUT, অথবা ADJUSTMENT বেছে নিন:" if is_bn else "Please choose IN, OUT, or ADJUSTMENT:"
                return {"session_id": session_id, "response": reply, "quick_replies": ["IN", "OUT", "ADJUSTMENT"]}

            data["movement_type"] = m_type
            wf["step"] = "ask_quantity"
            wf["data"] = data
            await session_manager.set_pending_workflow(session_id, wf)
            reply = f"মুভমেন্টের পরিমাণ (Quantity) কত পিস?" if is_bn else "What is the movement quantity?"
            return {"session_id": session_id, "response": reply, "quick_replies": ["1", "5", "10", "20"]}

        # Step 3: Quantity Validation
        elif step == "ask_quantity":
            q_match = re.search(r"(\d+)", msg)
            if not q_match or int(q_match.group(1)) <= 0:
                reply = "পরিমাণ কমপক্ষে ১ বা তার বেশি হতে হবে:" if is_bn else "Quantity must be 1 or greater:"
                return {"session_id": session_id, "response": reply, "quick_replies": ["1", "5", "10"]}

            qty = int(q_match.group(1))
            cur_stock = data.get("current_stock", 0)
            m_type = data.get("movement_type")

            if m_type == "OUT" and qty > cur_stock:
                reply = (
                    f"অপর্যাপ্ত স্টক! **'{data.get('product_name')}'**-এর বর্তমান স্টক মাত্র **{cur_stock}টি**। আপনি {qty}টি স্টক আউট করতে পারবেন না। {cur_stock} বা তার কম লিখুন:"
                    if is_bn
                    else f"Insufficient stock! Available stock is **{cur_stock} unit(s)**. Cannot remove {qty}. Please enter {cur_stock} or less:"
                )
                return {"session_id": session_id, "response": reply, "quick_replies": [str(cur_stock)]}

            data["quantity"] = qty
            wf["step"] = "ask_reason_opt"
            wf["data"] = data
            await session_manager.set_pending_workflow(session_id, wf)
            reply = "এই স্টক পরিবর্তনের কোনো কারণ (Reason) উল্লেখ করতে চান? হ্যাঁ অথবা না।" if is_bn else "Would you like to provide a reason for this movement? Yes or no."
            return {"session_id": session_id, "response": reply, "quick_replies": ["হ্যাঁ", "না"] if is_bn else ["Yes", "No"]}

        # Step 4: Reason Optional
        elif step == "ask_reason_opt":
            if is_affirmative(msg):
                wf["step"] = "enter_reason"
                await session_manager.set_pending_workflow(session_id, wf)
                reply = "কারণটি লিখুন (যেমন: নতুন চালান, ক্ষতিপূরণ, ইত্যাদি):" if is_bn else "Please enter the reason (e.g. New delivery, Damaged items):"
                return {"session_id": session_id, "response": reply, "quick_replies": ["Skip"] if not is_bn else ["বাদ দিন"]}
            else:
                data["reason"] = None
                wf["step"] = "preview"
                wf["data"] = data
                await session_manager.set_pending_workflow(session_id, wf)
                return await self._generate_stock_movement_preview(session_id, data, is_bn, user)

        elif step == "enter_reason":
            if is_negative(msg) or msg.lower() in ["skip", "বাদ"]:
                data["reason"] = None
            else:
                data["reason"] = msg.strip()

            wf["step"] = "preview"
            wf["data"] = data
            await session_manager.set_pending_workflow(session_id, wf)
            return await self._generate_stock_movement_preview(session_id, data, is_bn, user)

        return {"session_id": session_id, "response": "In preview state.", "quick_replies": ["Confirm Movement", "Edit Details", "Cancel"]}

    async def _generate_stock_movement_preview(
        self, session_id: str, data: dict[str, Any], is_bn: bool, user: User
    ) -> dict[str, Any]:
        tool_name = "record_stock_movement"
        tool_args = {
            "product_id": data.get("product_id"),
            "movement_type": data.get("movement_type"),
            "quantity": data.get("quantity"),
            "reason": data.get("reason"),
        }
        tool_def = tool_registry.get(tool_name)
        title, summary, details = tool_def.preview_generator(tool_args)

        action = await session_manager.create_pending_action(
            session_id=session_id,
            user_id=user.id,
            tool_name=tool_name,
            arguments=tool_args,
            preview_title=title,
            preview_summary=summary,
            preview_details=details,
        )

        cur = data.get("current_stock", 0)
        m_type = data.get("movement_type")
        qty = data.get("quantity", 0)
        new_stock = cur + qty if m_type == "IN" else (cur - qty if m_type == "OUT" else qty)

        if is_bn:
            preview_text = (
                f"### স্টক মুভমেন্ট প্রিভিউ (Stock Movement Preview)\n\n"
                f"• **পণ্য:** {data.get('product_name')} (SKU: {data.get('sku')})\n"
                f"• **মুভমেন্টের ধরন:** {m_type}\n"
                f"• **পরিমাণ:** {qty}টি\n"
                f"• **স্টক পরিবর্তন:** {cur}টি ➔ **{new_stock}টি**\n"
                f"• **কারণ:** {data.get('reason') or 'প্রদান করা হয়নি'}\n\n"
                f"নিশ্চিত করতে নিচে নির্বাচন করুন:"
            )
        else:
            preview_text = (
                f"### Stock Movement Preview\n\n"
                f"• **Product:** {data.get('product_name')} (SKU: {data.get('sku')})\n"
                f"• **Movement Type:** {m_type}\n"
                f"• **Quantity:** {qty}\n"
                f"• **Stock Adjustment:** {cur} ➔ **{new_stock}**\n"
                f"• **Reason:** {data.get('reason') or 'Not provided'}\n\n"
                f"Please review and confirm to execute:"
            )

        return {
            "session_id": session_id,
            "response": preview_text,
            "action_required": True,
            "pending_action": {
                "action_token": action.action_token,
                "title": action.preview_title,
                "summary": action.preview_summary,
                "details": action.preview_details,
                "expires_at": action.expires_at.isoformat(),
            },
            "quick_replies": ["Confirm Movement", "Edit Details", "Cancel"],
        }

    # =========================================================================
    # 5. ORDER STATUS UPDATE WORKFLOW (Order selection, Status update)
    # =========================================================================
    async def start_order_status_workflow(self, session_id: str, is_bn: bool) -> dict[str, Any]:
        wf = {
            "action": "update_order_status",
            "lang": "bn" if is_bn else "en",
            "step": "ask_order",
            "data": {},
        }
        await session_manager.set_pending_workflow(session_id, wf)
        reply = (
            "অর্ডারের স্ট্যাটাস পরিবর্তন প্রক্রিয়া শুরু হয়েছে। কোন অর্ডারের স্ট্যাটাস আপডেট করতে চান? (অর্ডার নম্বর যেমন: ORD-20261023-D972 বা অর্ডার আইডি বলুন):"
            if is_bn
            else "Starting order status update. Which order do you want to modify? (Enter order number e.g. ORD-20261023-D972 or order ID):"
        )
        return {"response": reply, "quick_replies": ["Cancel"] if not is_bn else ["বাতিল"]}

    async def _step_update_order_status(
        self, session_id: str, msg: str, wf: dict[str, Any], is_bn: bool, db: AsyncSession, user: User
    ) -> dict[str, Any]:
        step = wf.get("step")
        data = wf.get("data", {})

        # Step 1: Order Lookup
        if step == "ask_order":
            clean_ord = msg.strip().replace("#", "")
            stmt = select(Order).where(Order.order_number.ilike(f"%{clean_ord}%"))
            m_num = re.search(r"^\d+$", clean_ord)
            if m_num:
                stmt = select(Order).where(or_(Order.id == int(clean_ord), Order.order_number.ilike(f"%{clean_ord}%")))

            res = await db.execute(stmt)
            order = res.scalar_one_or_none()
            if not order:
                reply = (
                    f"**'{clean_ord}'** অর্ডারটি পাওয়া যায়নি। অনুগ্রহ করে সঠিক অর্ডার নম্বর বা আইডি লিখুন:"
                    if is_bn
                    else f"Order **'{clean_ord}'** not found. Please provide a valid order number or ID:"
                )
                return {"session_id": session_id, "response": reply, "quick_replies": ["Cancel"] if not is_bn else ["বাতিল"]}

            data["order_id"] = order.id
            data["order_number"] = order.order_number
            data["current_order_status"] = order.order_status
            data["current_payment_status"] = order.payment_status
            wf["step"] = "ask_new_status"
            wf["data"] = data
            await session_manager.set_pending_workflow(session_id, wf)
            reply = (
                f"অর্ডার **#{order.order_number}** (বর্তমান স্ট্যাটাস: {order.order_status}, পেমেন্ট: {order.payment_status})।\n\nনতুন ডেলিভারি স্ট্যাটাস কী হবে?\n• **Pending**\n• **Processing**\n• **Shipped**\n• **Delivered**\n• **Cancelled**"
                if is_bn
                else f"Order **#{order.order_number}** (Current Status: {order.order_status}, Payment: {order.payment_status}).\n\nWhat should the new order status be?\n• **Pending**\n• **Processing**\n• **Shipped**\n• **Delivered**\n• **Cancelled**"
            )
            return {"session_id": session_id, "response": reply, "quick_replies": ["Pending", "Processing", "Shipped", "Delivered", "Cancelled"]}

        # Step 2: Order Status
        elif step == "ask_new_status":
            valid_statuses = ["Pending", "Processing", "Shipped", "Delivered", "Cancelled"]
            chosen = None
            for s in valid_statuses:
                if s.lower() in msg.lower():
                    chosen = s
                    break
            if not chosen and msg.strip() in valid_statuses:
                chosen = msg.strip()

            if not chosen:
                reply = "অনুগ্রহ করে একটি সঠিক স্ট্যাটাস বেছে নিন (Pending, Processing, Shipped, Delivered, Cancelled):" if is_bn else "Please choose a valid status (Pending, Processing, Shipped, Delivered, Cancelled):"
                return {"session_id": session_id, "response": reply, "quick_replies": valid_statuses}

            data["new_order_status"] = chosen
            wf["step"] = "ask_payment_status"
            wf["data"] = data
            await session_manager.set_pending_workflow(session_id, wf)
            reply = (
                f"নতুন অর্ডার স্ট্যাটাস: **{chosen}**। পেমেন্ট স্ট্যাটাস কী হবে?\n• **Unpaid**\n• **Partial**\n• **Paid**"
                if is_bn
                else f"New order status: **{chosen}**. What should the payment status be?\n• **Unpaid**\n• **Partial**\n• **Paid**"
            )
            return {"session_id": session_id, "response": reply, "quick_replies": ["Unpaid", "Partial", "Paid"]}

        # Step 3: Payment Status & Preview
        elif step == "ask_payment_status":
            valid_payments = ["Unpaid", "Partial", "Paid"]
            chosen_pay = None
            for p in valid_payments:
                if p.lower() in msg.lower():
                    chosen_pay = p
                    break
            if not chosen_pay:
                chosen_pay = data.get("current_payment_status", "Unpaid")

            data["new_payment_status"] = chosen_pay
            wf["step"] = "preview"
            wf["data"] = data
            await session_manager.set_pending_workflow(session_id, wf)
            return await self._generate_order_status_preview(session_id, data, is_bn, user)

        return {"session_id": session_id, "response": "In preview state.", "quick_replies": ["Confirm Update", "Edit Details", "Cancel"]}

    async def _generate_order_status_preview(
        self, session_id: str, data: dict[str, Any], is_bn: bool, user: User
    ) -> dict[str, Any]:
        tool_name = "update_order_status"
        tool_args = {
            "order_id": data.get("order_id"),
            "order_status": data.get("new_order_status"),
            "payment_status": data.get("new_payment_status"),
        }
        tool_def = tool_registry.get(tool_name)
        title, summary, details = tool_def.preview_generator(tool_args)

        action = await session_manager.create_pending_action(
            session_id=session_id,
            user_id=user.id,
            tool_name=tool_name,
            arguments=tool_args,
            preview_title=title,
            preview_summary=summary,
            preview_details=details,
        )

        if is_bn:
            preview_text = (
                f"### অর্ডার স্ট্যাটাস প্রিভিউ (Order Status Preview)\n\n"
                f"• **অর্ডার নম্বর:** #{data.get('order_number')}\n"
                f"• **ডেলিভারি স্ট্যাটাস:** {data.get('current_order_status')} ➔ **{data.get('new_order_status')}**\n"
                f"• **পেমেন্ট স্ট্যাটাস:** {data.get('current_payment_status')} ➔ **{data.get('new_payment_status')}**\n\n"
                f"স্ট্যাটাস পরিবর্তনের জন্য নিশ্চিত করুন:"
            )
        else:
            preview_text = (
                f"### Order Status Update Preview\n\n"
                f"• **Order #:** {data.get('order_number')}\n"
                f"• **Order Status:** {data.get('current_order_status')} ➔ **{data.get('new_order_status')}**\n"
                f"• **Payment Status:** {data.get('current_payment_status')} ➔ **{data.get('new_payment_status')}**\n\n"
                f"Please confirm to apply changes:"
            )

        return {
            "session_id": session_id,
            "response": preview_text,
            "action_required": True,
            "pending_action": {
                "action_token": action.action_token,
                "title": action.preview_title,
                "summary": action.preview_summary,
                "details": action.preview_details,
                "expires_at": action.expires_at.isoformat(),
            },
            "quick_replies": ["Confirm Update", "Edit Details", "Cancel"],
        }

    # =========================================================================
    # 6. EDIT DETAILS WORKFLOW (Field-level editing preserving all other data)
    # =========================================================================
    def _build_edit_field_choice_reply(self, wf: dict[str, Any], is_bn: bool) -> dict[str, Any]:
        action = wf.get("action")
        if action == "create_customer":
            fields = ["Name", "Phone", "Email", "Address", "Notes"]
            bn_fields = ["নাম", "ফোন নম্বর", "ইমেইল", "ঠিকানা", "নোট"]
        elif action == "create_product":
            fields = ["Name", "SKU", "Category", "Price", "Stock", "Reorder Level"]
            bn_fields = ["নাম", "SKU", "ক্যাটাগরি", "মূল্য", "স্টক", "সতর্কসীমা"]
        elif action == "record_stock_movement":
            fields = ["Movement Type", "Quantity", "Reason"]
            bn_fields = ["মুভমেন্টের ধরন", "পরিমাণ", "কারণ"]
        elif action == "update_order_status":
            fields = ["Order Status", "Payment Status"]
            bn_fields = ["অর্ডার স্ট্যাটাস", "পেমেন্ট স্ট্যাটাস"]
        else:
            fields = ["Notes"]
            bn_fields = ["নোট"]

        quick_replies = bn_fields if is_bn else fields
        reply = (
            "আপনি কোন তথ্যটি পরিবর্তন বা সংশোধন করতে চান? নিচে থেকে নির্বাচন করুন:"
            if is_bn
            else "Which detail would you like to edit? Select below:"
        )
        return {
            "session_id": wf.get("session_id", ""),
            "response": reply,
            "action_required": False,
            "pending_action": None,
            "quick_replies": quick_replies,
        }

    async def _handle_choose_edit_field(
        self, session_id: str, msg: str, wf: dict[str, Any], is_bn: bool, db: AsyncSession, user: User
    ) -> dict[str, Any]:
        msg_clean = msg.strip().lower()
        field_to_edit = None

        if any(w in msg_clean for w in ["name", "নাম"]):
            field_to_edit = "name"
        elif any(w in msg_clean for w in ["phone", "ফোন", "মোবাইল"]):
            field_to_edit = "phone"
        elif any(w in msg_clean for w in ["email", "ইমেইল"]):
            field_to_edit = "email"
        elif any(w in msg_clean for w in ["address", "ঠিকানা"]):
            field_to_edit = "address"
        elif any(w in msg_clean for w in ["notes", "নোট"]):
            field_to_edit = "notes"
        elif any(w in msg_clean for w in ["sku"]):
            field_to_edit = "sku"
        elif any(w in msg_clean for w in ["category", "ক্যাটাগরি"]):
            field_to_edit = "category"
        elif any(w in msg_clean for w in ["price", "দাম", "মূল্য"]):
            field_to_edit = "price"
        elif any(w in msg_clean for w in ["stock", "মজুদ"]):
            field_to_edit = "stock_quantity"
        elif any(w in msg_clean for w in ["reorder", "সতর্কসীমা"]):
            field_to_edit = "reorder_level"
        elif any(w in msg_clean for w in ["type", "ধরন"]):
            field_to_edit = "movement_type"
        elif any(w in msg_clean for w in ["quantity", "পরিমাণ"]):
            field_to_edit = "quantity"
        elif any(w in msg_clean for w in ["order status", "স্ট্যাটাস"]):
            field_to_edit = "new_order_status"
        elif any(w in msg_clean for w in ["payment", "পেমেন্ট"]):
            field_to_edit = "new_payment_status"

        if not field_to_edit:
            reply = "ফিল্ডটি বুঝতে পারিনি। অনুগ্রহ করে সঠিক ফিল্ড বেছে নিন:" if is_bn else "Unrecognized field. Please choose an editable field:"
            return {"session_id": session_id, "response": reply}

        wf["editing_field"] = field_to_edit
        wf["step"] = "enter_edit_value"
        await session_manager.set_pending_workflow(session_id, wf)

        reply = (
            f"অনুগ্রহ করে নতুন **'{field_to_edit.capitalize()}'**-এর মান লিখুন:"
            if is_bn
            else f"Please enter the new value for **'{field_to_edit.capitalize()}'**:"
        )
        return {"session_id": session_id, "response": reply}

    async def _handle_enter_edit_value(
        self, session_id: str, msg: str, wf: dict[str, Any], is_bn: bool, db: AsyncSession, user: User
    ) -> dict[str, Any]:
        field = wf.get("editing_field")
        data = wf.get("data", {})
        action = wf.get("action")

        # Validation per field
        if field == "name":
            if len(msg.strip()) < 2:
                reply = "নাম কমপক্ষে ২ অক্ষর হতে হবে:" if is_bn else "Name must be at least 2 characters:"
                return {"session_id": session_id, "response": reply}
            data["name"] = msg.strip()

        elif field == "phone":
            phone_val = validate_phone_number(msg)
            if not phone_val:
                reply = "সঠিক ফোন নম্বর লিখুন:" if is_bn else "Please enter a valid phone number:"
                return {"session_id": session_id, "response": reply}
            data["phone"] = phone_val

        elif field == "email":
            if msg.lower() in ["skip", "বাদ", "none"]:
                data["email"] = None
            else:
                email_val = validate_email_address(msg)
                if not email_val:
                    reply = "সঠিক ইমেইল ঠিকানা লিখুন (যেমন: user@example.com) অথবা 'skip' বলুন:" if is_bn else "Please enter a valid email address or say 'skip':"
                    return {"session_id": session_id, "response": reply}
                data["email"] = email_val

        elif field in ["address", "notes", "reason"]:
            data[field] = msg.strip() if msg.lower() not in ["none", "বাদ", "skip"] else None

        elif field == "sku":
            clean_sku = msg.strip().upper()
            res = await db.execute(select(Product).where(Product.sku == clean_sku, Product.is_deleted == False))
            existing = res.scalar_one_or_none()
            if existing:
                reply = f"এই SKU ({clean_sku}) ইতিমধ্যে ব্যবহৃত! অন্য SKU দিন:" if is_bn else f"SKU '{clean_sku}' already in use! Please enter another SKU:"
                return {"session_id": session_id, "response": reply}
            data["sku"] = clean_sku

        elif field == "price":
            m_price = re.search(r"(\d+(?:\.\d+)?)", msg)
            if not m_price or float(m_price.group(1)) <= 0:
                reply = "মূল্য ০-এর বেশি হতে হবে:" if is_bn else "Price must be > 0:"
                return {"session_id": session_id, "response": reply}
            data["price"] = float(m_price.group(1))

        elif field in ["stock_quantity", "reorder_level", "quantity"]:
            m_num = re.search(r"(\d+)", msg)
            if not m_num:
                reply = "সঠিক সংখ্যা লিখুন:" if is_bn else "Please enter a valid numeric value:"
                return {"session_id": session_id, "response": reply}
            data[field] = int(m_num.group(1))

        # Clear editing field and return to preview
        wf["editing_field"] = None
        wf["step"] = "preview"
        wf["data"] = data
        await session_manager.set_pending_workflow(session_id, wf)

        # Regenerate preview
        if action == "create_customer":
            return await self._generate_customer_preview(session_id, data, is_bn, user)
        elif action == "create_product":
            return await self._generate_product_preview(session_id, data, is_bn, user)
        elif action == "create_order":
            return await self._generate_order_preview(session_id, data, is_bn, user)
        elif action == "record_stock_movement":
            return await self._generate_stock_movement_preview(session_id, data, is_bn, user)
        elif action == "update_order_status":
            return await self._generate_order_status_preview(session_id, data, is_bn, user)

        return {"session_id": session_id, "response": "Updated successfully."}


conversational_workflow_engine = ConversationalWorkflowEngine()
