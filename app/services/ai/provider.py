from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
import json
import logging
import re
import secrets
from typing import Any
import httpx
from pydantic import BaseModel, Field

from app.core.config import settings

logger = logging.getLogger("shop_management.ai")


def is_bengali_input(text: str) -> bool:
    if not text:
        return False
    if re.search(r"[\u0980-\u09FF]", text):
        return True
    banglish = {"bolo", "koto", "ache", "koi", "er", "dekhao", "chai", "korbo", "korse", "notun", "taka", "bikri", "kaj", "ashbe"}
    words = set(re.findall(r"[a-zA-Z]+", text.lower()))
    return len(words.intersection(banglish)) >= 1


class ToolCall(BaseModel):
    id: str = Field(default_factory=lambda: f"call_{secrets.token_hex(6)}")
    name: str
    arguments: dict[str, Any]


class AIProviderResponse(BaseModel):
    text: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    provider_name: str
    is_fallback: bool = False
    error: str | None = None


class AIProvider(ABC):
    """Abstract Base Class for AI Model Providers."""

    @abstractmethod
    async def generate_response(
        self,
        messages: list[dict[str, Any]],
        tools_schema: list[dict[str, Any]],
        system_prompt: str,
    ) -> AIProviderResponse:
        pass


class GeminiProvider(AIProvider):
    """
    Google Gemini Provider using direct REST API over httpx.
    Supports function calling and multi-turn tool result summarization.
    """
    _cooldown_until: datetime | None = None

    def __init__(self, api_key: str, model_name: str = "gemini-3.8-flash"):
        self.api_key = api_key.strip()
        # Automatically upgrade deprecated model names
        if not model_name or "1.5" in model_name or "2.5-flash" == model_name:
            model_name = "gemini-3.8-flash"
        self.model_name = model_name

    async def generate_response(
        self,
        messages: list[dict[str, Any]],
        tools_schema: list[dict[str, Any]],
        system_prompt: str,
        session_context: dict[str, Any] | None = None,
    ) -> AIProviderResponse:
        # Check if currently in rate limit cooldown
        if GeminiProvider._cooldown_until and datetime.now(timezone.utc) < GeminiProvider._cooldown_until:
            return AIProviderResponse(
                provider_name=f"gemini ({self.model_name})",
                error="Gemini 429 rate-limit cooldown active",
            )
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent?key={self.api_key}"

        contents = []
        for m in messages:
            role = "user" if m.get("role") in ["user", "human"] else "model"
            content_str = m.get("content", "").strip()
            if content_str:
                contents.append({
                    "role": role,
                    "parts": [{"text": content_str}],
                })

        if not contents:
            return AIProviderResponse(text="Hello! How can I assist with your shop today?", provider_name="gemini")

        req_body: dict[str, Any] = {"contents": contents}

        if system_prompt:
            req_body["system_instruction"] = {
                "parts": [{"text": system_prompt}]
            }

        if tools_schema:
            req_body["tools"] = [{
                "function_declarations": tools_schema
            }]

        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                res = await client.post(url, json=req_body)

                # Auto-fallback to gemini-flash-latest if model 404s
                if res.status_code == 404 and self.model_name != "gemini-flash-latest":
                    retry_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent?key={self.api_key}"
                    res = await client.post(retry_url, json=req_body)

                if res.status_code != 200:
                    if res.status_code == 429:
                        GeminiProvider._cooldown_until = datetime.now(timezone.utc) + timedelta(seconds=60)
                    logger.warning(f"Gemini API returned status {res.status_code}: {res.text}")
                    return AIProviderResponse(
                        provider_name=f"gemini ({self.model_name})",
                        error=f"Gemini API Status {res.status_code}",
                        is_fallback=True,
                    )

                data = res.json()
                candidates = data.get("candidates", [])
                if not candidates:
                    return AIProviderResponse(
                        provider_name=f"gemini ({self.model_name})",
                        text="I did not receive a response from Gemini.",
                    )

                parts = candidates[0].get("content", {}).get("parts", [])
                reply_text = ""
                tool_calls = []

                for part in parts:
                    if "functionCall" in part:
                        fc = part["functionCall"]
                        tool_calls.append(
                            ToolCall(
                                id=fc.get("id", f"call_{secrets.token_hex(4)}"),
                                name=fc.get("name", ""),
                                arguments=fc.get("args", {}),
                            )
                        )
                    if "text" in part:
                        reply_text += part["text"]

                return AIProviderResponse(
                    text=reply_text.strip() if reply_text else None,
                    tool_calls=tool_calls,
                    provider_name=f"gemini ({self.model_name})",
                )
        except Exception as exc:
            logger.error(f"Gemini API call failed: {exc}", exc_info=True)
            return AIProviderResponse(
                provider_name="gemini",
                error=str(exc),
                is_fallback=True,
            )

    async def summarize_tool_result(
        self,
        messages: list[dict[str, Any]],
        tool_name: str,
        tool_result: dict[str, Any],
        system_prompt: str,
    ) -> str | None:
        if GeminiProvider._cooldown_until and datetime.now(timezone.utc) < GeminiProvider._cooldown_until:
            return None

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent?key={self.api_key}"

        contents = []
        for m in messages:
            role = "user" if m.get("role") in ["user", "human"] else "model"
            content_str = m.get("content", "").strip()
            if content_str:
                contents.append({
                    "role": role,
                    "parts": [{"text": content_str}],
                })

        contents.append({
            "role": "model",
            "parts": [{"functionCall": {"name": tool_name, "args": {}}}],
        })

        contents.append({
            "role": "user",
            "parts": [{
                "functionResponse": {
                    "name": tool_name,
                    "response": {"output": tool_result}
                }
            }],
        })

        req_body: dict[str, Any] = {"contents": contents}
        if system_prompt:
            req_body["system_instruction"] = {
                "parts": [{"text": system_prompt}]
            }

        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                res = await client.post(url, json=req_body)
                if res.status_code == 429:
                    GeminiProvider._cooldown_until = datetime.now(timezone.utc) + timedelta(seconds=60)
                    return None
                if res.status_code == 200:
                    data = res.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        texts = [p.get("text", "") for p in parts if "text" in p]
                        if texts:
                            return "".join(texts).strip()
        except Exception as exc:
            logger.warning(f"Failed to summarize tool result with Gemini: {exc}")
        return None


class FallbackRuleBasedProvider(AIProvider):
    """
    Intelligent zero-dependency heuristic intent parser.
    Understands Bengali, Banglish, and English with deep context awareness and entity resolution.
    """

    async def generate_response(
        self,
        messages: list[dict[str, Any]],
        tools_schema: list[dict[str, Any]],
        system_prompt: str,
        session_context: dict[str, Any] | None = None,
    ) -> AIProviderResponse:
        ctx = session_context or {}
        latest = messages[-1].get("content", "").strip() if messages else ""
        text_lower = latest.lower()
        t_clean = re.sub(r"[\?\.\!,\:\;\'\"`\(\)]+", " ", text_lower).strip()
        t_clean = re.sub(r"\s+", " ", t_clean)
        is_bn = is_bengali_input(latest)

        # 1. Customer existence check:
        # e.g. "Rahim Ahmed নামে কোনো customer আছে?", "Rahim নামে customer আছে?", "is there a customer named Rahim", "do we have customer named X"
        exist_m = (
            re.search(r"([a-zA-Z0-9\u0980-\u09FF\s\.\-_]+?)\s+নামে\s+(?:কোনো\s+|কোন\s+)?(?:কাস্টমার|customer|গ্রাহক)\s+আছে", latest, re.I)
            or re.search(r"(?:is there (?:a\s+)?customer (?:named\s+)?|check customer named|find customer named)\s+([a-zA-Z0-9\u0980-\u09FF\s\.\-_]+)", latest, re.I)
        )
        if exist_m:
            name_to_check = exist_m.group(1).strip()
            name_to_check = re.sub(r"^(কি|আমাদের|দোকানে|is\s+there)\s+", "", name_to_check, flags=re.I).strip()
            if name_to_check:
                return AIProviderResponse(
                    text=f"Checking if customer '{name_to_check}' exists in database.",
                    tool_calls=[ToolCall(name="get_customer_existence", arguments={"query": name_to_check})],
                    provider_name="fallback_rules",
                    is_fallback=True,
                )

        # 2a. Top Customers Ranking:
        # e.g. "Show the top five customers by total order value", "শীর্ষ কাস্টমার", "show top customers", "customer who ordered the most"
        if any(w in t_clean for w in ["top customer", "top five customer", "top 5 customer", "best customer", "শীর্ষ কাস্টমার", "শীর্ষ ৫ জন", "সবচেয়ে বেশি অর্ডার", "ordered the most"]):
            return AIProviderResponse(
                text="Finding top customers ranked by cumulative order value.",
                tool_calls=[ToolCall(name="get_top_customers", arguments={"limit": 5})],
                provider_name="fallback_rules",
                is_fallback=True,
            )

        # 2b. Sales Comparison between Dates:
        # e.g. "গতকালের sales-এর সঙ্গে আজকের sales compare করো", "compare today and yesterday sales", "sales compare", "আজকের সাথে গতকালের সেলস তুলনা"
        if (any(w in t_clean for w in ["compare", "তুলনা"]) and any(w in t_clean for w in ["sales", "সেলস", "বিক্রি"])) or ("গতকালের" in t_clean and "আজকের" in t_clean and any(w in t_clean for w in ["sales", "সেলস", "বিক্রি", "compare"])):
            return AIProviderResponse(
                text="Comparing sales revenue between today and yesterday.",
                tool_calls=[ToolCall(name="compare_sales_dates", arguments={"date_1": "today", "date_2": "yesterday"})],
                provider_name="fallback_rules",
                is_fallback=True,
            )

        # 2c. Highest / Top Sales Date Query:
        # e.g. "কোনদিন সবচেয়ে বেশি sales হয়েছে?", "কোন দিন সবচেয়ে বেশি সেল হয়েছে", "সবচেয়ে বেশি বিক্রি কোন দিন", "highest sales date", "which day had the most sales"
        if any(w in t_clean for w in ["সবচেয়ে বেশি sales", "সবচেয়ে বেশি সেল", "সবচেয়ে বেশি বিক্রি", "সবচেয়ে বেশি বিক্রয়", "highest sales", "most sales", "best sales day", "best sales date"]) and any(w in t_clean for w in ["কোনদিন", "কোন দিন", "দিন", "তারিখ", "day", "date", "when"]):
            return AIProviderResponse(
                text="Finding the historical date with highest total sales revenue.",
                tool_calls=[ToolCall(name="get_top_sales_date", arguments={"period": "all_time"})],
                provider_name="fallback_rules",
                is_fallback=True,
            )

        # 2d. Top Selling Products Query:
        # e.g. "Which product sold the most this month?", "সবচেয়ে বেশি বিক্রি হওয়া প্রোডাক্ট", "top selling product", "best selling product"
        if any(w in t_clean for w in ["sold the most", "top selling", "best selling", "সবচেয়ে বেশি বিক্রি", "বেশি বিক্রি হওয়া", "সবচেয়ে বেশি সেল"]) and any(w in t_clean for w in ["product", "item", "প্রোডাক্ট", "পণ্য"]):
            period = "this_month" if any(w in t_clean for w in ["this month", "এই মাস", "এই মাসে", "month"]) else "all_time"
            return AIProviderResponse(
                text="Finding top selling products ranked by volume and revenue.",
                tool_calls=[ToolCall(name="get_top_selling_products", arguments={"period": period, "limit": 5})],
                provider_name="fallback_rules",
                is_fallback=True,
            )

        # 2e. Customer Order Totals:
        # e.g. "Rahim Ahmed মোট কত টাকার order করেছে?", "সে মোট কত টাকার order করেছে?", "তার মোট অর্ডার কত?"
        totals_m = re.search(r"([a-zA-Z0-9\u0980-\u09FF\s\.\-_]+?)\s*(?:-এর|এর|\'s)?\s+মোট\s+কত\s+টাকার\s+(?:order|অর্ডার)", latest, re.I)
        is_order_total_query = totals_m or (any(w in t_clean for w in ["টাকার order", "টাকার অর্ডার", "কত টাকার অর্ডার", "কত টাকার order", "total order value", "order total", "কত টাকার কেনাকাটা"]) and not any(w in t_clean for w in ["top", "শীর্ষ", "সবচেয়ে বেশি", "most"]))
        if is_order_total_query:
            target = totals_m.group(1).strip() if totals_m else ""
            target = re.sub(r"^(তিনি|সে|তার|his|her|he)\s+", "", target, flags=re.I).strip()
            if (not target or target in ["সে", "তার", "তিনি", "he", "she", "his", "her"]) and ctx.get("last_customer_id"):
                return AIProviderResponse(
                    text="Retrieving total order amount for previously referenced customer.",
                    tool_calls=[ToolCall(name="get_customer_order_totals", arguments={"customer_id": ctx["last_customer_id"], "customer_name": ctx.get("last_customer_name")})],
                    provider_name="fallback_rules",
                    is_fallback=True,
                )
            elif target and target not in ["সে", "তার", "he", "she"]:
                return AIProviderResponse(
                    text=f"Calculating total order amount for customer '{target}'.",
                    tool_calls=[ToolCall(name="get_customer_order_totals", arguments={"customer_name": target})],
                    provider_name="fallback_rules",
                    is_fallback=True,
                )
            else:
                clarify_msg = (
                    "আপনি কোন কাস্টমারের মোট অর্ডারের হিসাব জানতে চান? অনুগ্রহ করে কাস্টমারের নাম বা আইডি বলুন।"
                    if is_bn
                    else "Which customer's order totals would you like me to calculate? Please specify the customer name or ID."
                )
                return AIProviderResponse(text=clarify_msg, provider_name="fallback_rules", is_fallback=True)

        # 3. Customer Count queries:
        # e.g. "Total customer?", "Total customer", "Total customers?", "Customer count", "এখানে কতজন কাস্টমার আছে?", "এখন মোট customer কয়টা?", "How many customers do we have?", "Total customer count bolo", "কাস্টমার সংখ্যা কত", "মোট কাস্টমার"
        cust_count_terms = [
            "total customer", "total customers", "customer count", "customers count", "how many customer", "how many customers",
            "number of customer", "number of customers", "all customer count", "all customers count", "count customer", "count customers",
            "মোট কাস্টমার", "মোট গ্রাহক", "মোট কাস্টমার কত", "মোট গ্রাহক কত", "কাস্টমার সংখ্যা", "গ্রাহক সংখ্যা",
            "কতজন কাস্টমার", "কত গ্রাহক", "কাস্টমার কত", "কাস্টমার কয়টা", "কাস্টমার কয়টা", "কয়জন কাস্টমার",
            "কয়জন কাস্টমার", "কাস্টমার কয়জন", "কত কাস্টমার", "কাস্টমারদের সংখ্যা", "কাস্টমার আছে কত"
        ]
        is_cust_count = (
            any(w in t_clean for w in cust_count_terms)
            or (
                any(w in t_clean for w in ["total", "count", "কতজন", "কয়জন", "কয়জন", "কত", "how many", "মোট", "সংখ্যা"])
                and any(w in t_clean for w in ["customer", "customers", "কাস্টমার", "গ্রাহক"])
                and not any(w in t_clean for w in ["টাকা", "order", "অর্ডার", "টাকার", "spent", "value", "কেনাকাটা"])
            )
        )
        if is_cust_count:
            return AIProviderResponse(
                text="Checking active customer directory and count.",
                tool_calls=[ToolCall(name="get_dashboard_stats", arguments={})],
                provider_name="fallback_rules",
                is_fallback=True,
            )

        # 4. Customer List / Shorthand "Customer?" / "কাস্টমার?" queries:
        # e.g. "কাস্টমার", "কাস্টমার?", "customer", "customer?", "customers", "customers?", "গ্রাহক", "গ্রাহক?", "customer list", "কাস্টমার লিস্ট দেখাও"
        if (
            t_clean in [
                "customer", "customers", "কাস্টমার", "গ্রাহক",
                "customer list", "customers list", "কাস্টমার লিস্ট", "কাস্টমার তালিকা",
                "গ্রাহক তালিকা", "সব কাস্টমার", "active customers", "list customers",
                "কাস্টমারদের তালিকা", "কাস্টমারদের লিস্ট", "গ্রাহকদের তালিকা"
            ]
            or any(w in t_clean for w in [
                "customer list", "customers list", "কাস্টমার লিস্ট", "কাস্টমার তালিকা",
                "গ্রাহক তালিকা", "সব কাস্টমার", "active customers", "list customers",
                "কাস্টমার দেখাও", "গ্রাহক দেখাও", "কাস্টমারদের তালিকা"
            ])
        ):
            return AIProviderResponse(
                text="Fetching your shop's customer directory.",
                tool_calls=[ToolCall(name="search_customers", arguments={"query": ""})],
                provider_name="fallback_rules",
                is_fallback=True,
            )

        # 5. Customer search by specific name:
        cust_search_match = re.search(r"(?:search customer|find customer|customer|কাস্টমার|গ্রাহক)\s+([a-zA-Z0-9\u0980-\u09FF\s]+)", latest, re.I)
        if cust_search_match and not any(w in t_clean for w in ["add", "create", "new", "যোগ", "এড", "তৈরি", "কত", "সংখ্যা", "আছে", "কয়টা", "কয়টা", "লিস্ট", "তালিকা", "total", "count"]):
            term = cust_search_match.group(1).strip()
            term = re.sub(r"(লিস্ট|তালিকা|দেখাও|list|all|show)", "", term, flags=re.I).strip()
            if len(term) >= 2 and term.lower() not in ["list", "all", "show", "count", "total"]:
                return AIProviderResponse(
                    text=f"Searching customer directory for '{term}'.",
                    tool_calls=[ToolCall(name="search_customers", arguments={"query": term})],
                    provider_name="fallback_rules",
                    is_fallback=True,
                )

        # 6. Product Count queries:
        # e.g. "Total product?", "Total product", "product count", "মোট প্রোডাক্ট", "পণ্য সংখ্যা", "পণ্য কয়টা"
        prod_count_terms = [
            "total product", "total products", "product count", "products count", "how many product", "how many products",
            "number of product", "number of products", "all product count", "all products count", "count product", "count products",
            "মোট প্রোডাক্ট", "মোট পণ্য", "মোট আইটেম", "মোট মাল", "প্রোডাক্ট সংখ্যা", "পণ্য সংখ্যা", "আইটেম সংখ্যা",
            "কতগুলো প্রোডাক্ট", "কতটা প্রোডাক্ট", "প্রোডাক্ট কত", "পণ্য কত", "প্রোডাক্ট কয়টা", "প্রোডাক্ট কয়টা", "পণ্য কয়টা", "পণ্য কয়টা",
            "প্রোডাক্ট আছে কত", "পণ্য আছে কত", "কত প্রোডাক্ট", "কত পণ্য"
        ]
        is_prod_count = (
            any(w in t_clean for w in prod_count_terms)
            or (
                any(w in t_clean for w in ["total", "count", "কতগুলো", "কতটা", "কয়টা", "কয়টা", "কত", "how many", "মোট", "সংখ্যা"])
                and any(w in t_clean for w in ["product", "products", "item", "items", "প্রোডাক্ট", "পণ্য", "আইটেম", "মাল"])
                and not any(w in t_clean for w in ["sell", "sold", "বিক্রি", "সেলস", "sales", "টাকা", "order", "অর্ডার"])
            )
        )
        if is_prod_count:
            return AIProviderResponse(
                text="Checking active product catalog inventory count.",
                tool_calls=[ToolCall(name="get_dashboard_stats", arguments={})],
                provider_name="fallback_rules",
                is_fallback=True,
            )

        # 7. Product List / Shorthand "Product?" / "প্রোডাক্ট?" queries:
        # e.g. "Product?", "product", "products", "প্রোডাক্ট?", "প্রোডাক্ট", "পণ্য?", "পণ্য", "product list"
        if (
            t_clean in [
                "product", "products", "item", "items", "প্রোডাক্ট", "পণ্য", "আইটেম", "মাল",
                "product list", "products list", "প্রোডাক্ট লিস্ট", "প্রোডাক্ট তালিকা", "পণ্য তালিকা",
                "সব প্রোডাক্ট", "সব পণ্য", "list products", "products catalog", "ক্যাটালগ", "catalog", "মালের তালিকা"
            ]
            or any(w in t_clean for w in [
                "product list", "products list", "প্রোডাক্ট লিস্ট", "প্রোডাক্ট তালিকা", "পণ্য তালিকা",
                "সব প্রোডাক্ট", "সব পণ্য", "list products", "পণ্য দেখাও", "প্রোডাক্ট দেখাও", "ক্যাটালগ দেখাও"
            ])
        ):
            return AIProviderResponse(
                text="Fetching your shop's product catalog.",
                tool_calls=[ToolCall(name="search_products", arguments={"query": ""})],
                provider_name="fallback_rules",
                is_fallback=True,
            )

        # 8. Order Count queries:
        # e.g. "Total order?", "Total order", "order count", "orders count", "মোট অর্ডার", "অর্ডার সংখ্যা"
        order_count_terms = [
            "total order", "total orders", "order count", "orders count", "how many order", "how many orders",
            "number of order", "number of orders", "all order count", "all orders count", "count order", "count orders",
            "মোট অর্ডার", "অর্ডার সংখ্যা", "কতগুলো অর্ডার", "অর্ডার কত", "অর্ডার কয়টা", "অর্ডার কয়টা", "কত অর্ডার", "অর্ডার আছে কত"
        ]
        is_order_count = (
            any(w in t_clean for w in order_count_terms)
            or (
                any(w in t_clean for w in ["total", "count", "কতগুলো", "কতটা", "কয়টা", "কয়টা", "কত", "how many", "মোট", "সংখ্যা"])
                and any(w in t_clean for w in ["order", "orders", "অর্ডার"])
                and not any(w in t_clean for w in ["টাকা", "টাকার", "spent", "value", "কেনাকাটা", "টাকার অর্ডার", "টাকার order"])
            )
        )
        if is_order_count:
            return AIProviderResponse(
                text="Checking shop order statistics and totals.",
                tool_calls=[ToolCall(name="get_dashboard_stats", arguments={})],
                provider_name="fallback_rules",
                is_fallback=True,
            )

        # 9. Order List / Shorthand "Order?" / "অর্ডার?" queries:
        # e.g. "Order?", "order", "orders", "অর্ডার?", "অর্ডার", "recent orders", "অর্ডারের তালিকা"
        if (
            t_clean in [
                "order", "orders", "অর্ডার", "অর্ডারগুলো", "recent orders", "order list",
                "orders list", "অর্ডার লিস্ট", "অর্ডার তালিকা", "অর্ডারের তালিকা", "সব অর্ডার", "list orders"
            ]
            or any(w in t_clean for w in [
                "recent orders", "order list", "orders list", "অর্ডার লিস্ট", "অর্ডার তালিকা",
                "অর্ডারের তালিকা", "সব অর্ডার", "list orders", "অর্ডার দেখাও", "অর্ডারগুলো দেখাও", "সাম্প্রতিক অর্ডার"
            ])
        ):
            return AIProviderResponse(
                text="Retrieving recent sales orders list.",
                tool_calls=[ToolCall(name="list_orders", arguments={})],
                provider_name="fallback_rules",
                is_fallback=True,
            )

        # 10. Date-based Sales Reporting:
        # e.g. "গতকাল কত টাকার sales হয়েছে?", "আজকে কত টাকার sales হয়েছে?", "October 15-এ কত টাকার sales হয়েছিল?"
        if any(w in t_clean for w in ["গতকাল", "yesterday"]):
            if any(w in t_clean for w in ["sales", "সেলস", "বিক্রি", "টাকা", "টাকার"]):
                return AIProviderResponse(
                    text="Retrieving verified sales for yesterday.",
                    tool_calls=[ToolCall(name="get_sales_by_date", arguments={"date_str": "yesterday"})],
                    provider_name="fallback_rules",
                    is_fallback=True,
                )
            elif any(w in t_clean for w in ["কত ছিল", "কত", "was"]) and ctx.get("last_product_name"):
                return AIProviderResponse(
                    text=f"Checking yesterday's sales for '{ctx['last_product_name']}'.",
                    tool_calls=[ToolCall(name="get_product_sales", arguments={"product_name": ctx["last_product_name"], "date_str": "yesterday"})],
                    provider_name="fallback_rules",
                    is_fallback=True,
                )
            else:
                return AIProviderResponse(
                    text="Retrieving sales metrics for yesterday.",
                    tool_calls=[ToolCall(name="get_sales_by_date", arguments={"date_str": "yesterday"})],
                    provider_name="fallback_rules",
                    is_fallback=True,
                )

        if any(w in t_clean for w in ["আজকে কত", "আজকের sales", "আজকের সেলস", "আজকের বিক্রি", "today sales", "today's sales"]):
            return AIProviderResponse(
                text="Retrieving verified sales for today.",
                tool_calls=[ToolCall(name="get_sales_by_date", arguments={"date_str": "today"})],
                provider_name="fallback_rules",
                is_fallback=True,
            )

        # Specific calendar date sales: e.g. "October 15-এ কত টাকার sales হয়েছিল?", "sales on 2026-10-13"
        date_sales_m = re.search(r"([a-zA-Z]+ \d{1,2}|\d{4}-\d{2}-\d{2}|\d{1,2} [a-zA-Z]+|\d{1,2}\s*তারিখ).*?(?:sales|সেলস|বিক্রি|বিক্রয়)", t_clean, re.I)
        if date_sales_m:
            raw_d = date_sales_m.group(1).replace("তারিখ", "").strip()
            return AIProviderResponse(
                text=f"Retrieving verified sales for date '{raw_d}'.",
                tool_calls=[ToolCall(name="get_sales_by_date", arguments={"date_str": raw_d})],
                provider_name="fallback_rules",
                is_fallback=True,
            )

        # 11. Product Sales:
        # e.g. "আজকে Rice কতটা sell হয়েছে?", "আজকে এই product কতটা sell হয়েছে?", "how much rice was sold today"
        prod_sales_m = (
            re.search(r"(?:আজকে\s+|today\s+)?([a-zA-Z0-9\u0980-\u09FF\s\-_]+?)\s+(?:কতটা|কত|how much)?\s*(?:sell|বিক্রি|বিক্রয়)\s+(?:হয়েছে|হয়েছে|was sold)?", latest, re.I)
            or re.search(r"sales of ([a-zA-Z0-9\u0980-\u09FF\s\-_]+?)(?:\s+today|\s+yesterday|$)", latest, re.I)
        )
        if prod_sales_m and any(w in t_clean for w in ["sell", "বিক্রি", "বিক্রয়", "sold"]):
            pname = prod_sales_m.group(1).strip()
            pname = re.sub(r"^(আজকে|today|the|this|ওই|এই)\s+", "", pname, flags=re.I).strip()
            if pname in ["এই product", "ওটার", "it", "this product", "product", "পণ্য"]:
                pname = ctx.get("last_product_name", "")
            if pname:
                return AIProviderResponse(
                    text=f"Checking sales quantity and revenue for product '{pname}'.",
                    tool_calls=[ToolCall(name="get_product_sales", arguments={"product_name": pname, "date_str": "today"})],
                    provider_name="fallback_rules",
                    is_fallback=True,
                )
            else:
                clarify_msg = (
                    "আপনি কোন প্রোডাক্ট বা অর্ডারের সেলস দেখতে চান? প্রোডাক্টের নাম বা SKU উল্লেখ করুন।"
                    if is_bn
                    else "Which product or order would you like me to check? Please specify the product name or SKU."
                )
                return AIProviderResponse(text=clarify_msg, provider_name="fallback_rules", is_fallback=True)

        # Ambiguous reference: "ওটার sales দেখাও"
        if ("ওটার" in t_clean or "this product" in t_clean) and any(w in t_clean for w in ["sales", "বিক্রি", "সেলস"]):
            if ctx.get("last_product_name"):
                return AIProviderResponse(
                    text=f"Checking sales for '{ctx['last_product_name']}'.",
                    tool_calls=[ToolCall(name="get_product_sales", arguments={"product_name": ctx["last_product_name"], "date_str": "today"})],
                    provider_name="fallback_rules",
                    is_fallback=True,
                )
            clarify_msg = (
                "আপনি কোন প্রোডাক্ট বা অর্ডারের সেলস দেখতে চান? প্রোডাক্টের নাম বা SKU উল্লেখ করুন।"
                if is_bn
                else "Which product or order would you like me to check? Please specify the product name or SKU."
            )
            return AIProviderResponse(text=clarify_msg, provider_name="fallback_rules", is_fallback=True)

        # 12. Product Stock Check:
        # e.g. "লজিটেক মাউস এর স্টক কত", "check stock of keyboard", "মাউসের স্টক কত", "what is the stock of mouse"
        stock_query_match = (
            re.search(r"([a-zA-Z0-9\u0980-\u09FF\s\-_]+)\s+(?:এর\s+)?(?:স্টক|মজুদ|stock)\s+(?:কত|চেক|check)?", latest, re.I)
            or re.search(r"(?:stock of|check stock|স্টক কত)\s+([a-zA-Z0-9\u0980-\u09FF\s\-_]+)", latest, re.I)
        )
        if stock_query_match and not any(w in t_clean for w in ["কম স্টক", "low stock", "কাস্টমার", "customer", "রেভিনিউ", "sales"]):
            raw_target = stock_query_match.group(1).strip()
            clean_term = re.sub(r"^(কি|কত|এই|ওই|আমার|the|a|an)\s+", "", raw_target, flags=re.I).strip()
            if clean_term and len(clean_term) >= 2:
                return AIProviderResponse(
                    text=f"Checking stock and price for '{clean_term}'.",
                    tool_calls=[ToolCall(name="search_products", arguments={"query": clean_term})],
                    provider_name="fallback_rules",
                    is_fallback=True,
                )

        # 13. Low Stock Alert queries:
        # e.g. "low stock?", "low stock", "কম স্টক?", "কম স্টক", "stock alert", "ঘাটতি"
        if (
            t_clean in ["low stock", "low-stock", "কম স্টক", "স্টক কম", "stock alert", "স্টক অ্যালার্ট", "reorder", "ঘাটতি"]
            or any(w in t_clean for w in ["low stock", "low-stock", "কম স্টক", "স্টক কম", "stock alert", "স্টক অ্যালার্ট", "reorder", "ঘাটতি"])
        ):
            return AIProviderResponse(
                text="Checking products currently at or below their reorder safety thresholds.",
                tool_calls=[ToolCall(name="get_low_stock_products", arguments={})],
                provider_name="fallback_rules",
                is_fallback=True,
            )

        # 14. General Stock Shorthand ("Stock?", "স্টক?"):
        # e.g. "stock?", "stock", "স্টক?", "স্টক", "মজুদ?", "মজুদ", "stock status"
        if t_clean in ["stock", "stocks", "স্টক", "মজুদ", "stock status", "স্টকের অবস্থা", "স্টক রিপোর্ট"]:
            return AIProviderResponse(
                text="Checking shop stock inventory and safety reorder status.",
                tool_calls=[ToolCall(name="get_low_stock_products", arguments={})],
                provider_name="fallback_rules",
                is_fallback=True,
            )

        # 15. Inventory Movements ("Inventory?", "ইনভেন্টরি?"):
        # e.g. "inventory?", "inventory", "ইনভেন্টরি?", "ইনভেন্টরি", "stock history", "movements"
        if (
            t_clean in ["inventory", "movements", "stock history", "ইনভেন্টরি", "স্টক মুভমেন্ট", "মুভমেন্ট"]
            or any(w in t_clean for w in ["inventory", "movements", "stock history", "ইনভেন্টরি", "স্টক মুভমেন্ট", "স্টক হিস্ট্রি", "ইনভেন্টরি লগ"])
        ):
            return AIProviderResponse(
                text="Retrieving recent inventory stock movement audit logs.",
                tool_calls=[ToolCall(name="list_inventory_movements", arguments={})],
                provider_name="fallback_rules",
                is_fallback=True,
            )

        # 16. Sales / Revenue / Dashboard Overview queries:
        # e.g. "Sales?", "sales", "revenue?", "revenue", "রেভিনিউ?", "বিক্রি?", "dashboard?", "ড্যাশবোর্ড?"
        sales_revenue_dashboard_terms = [
            "sales", "revenue", "income", "profit", "total sales", "total revenue", "dashboard", "overview", "stats",
            "সেলস", "বিক্রি", "বিক্রয়", "রেভিনিউ", "ইনকাম", "লাভ", "ড্যাশবোর্ড", "হিসাব", "পরিসংখ্যান",
            "মোট সেলস", "মোট বিক্রি", "মোট বিক্রয়", "মোট রেভিনিউ", "দোকানের হিসাব", "আজকের হিসাব"
        ]
        if (
            t_clean in sales_revenue_dashboard_terms
            or any(w in t_clean for w in ["dashboard", "revenue", "রেভিনিউ", "বিক্রয়", "overview", "stats", "হিসাব", "লাভ", "ইনকাম", "পরিসংখ্যান"])
            or (any(w in t_clean for w in ["sales", "সেলস", "বিক্রি"]) and not any(w in t_clean for w in ["yesterday", "গতকাল", "today", "আজ", "তারিখ", "compare", "তুলনা", "product", "পণ্য"]))
        ):
            return AIProviderResponse(
                text="Fetching real-time business statistics and revenue overview.",
                tool_calls=[ToolCall(name="get_dashboard_stats", arguments={})],
                provider_name="fallback_rules",
                is_fallback=True,
            )

        # 17. General Product search:
        prod_search_match = re.search(r"(?:search|find|show|প্রোডাক্ট|পণ্য|মালের স্টক)\s+(?:product\s+|পণ্য\s+|item\s+)?([a-zA-Z0-9\u0980-\u09FF\-_]+)", latest, re.I)
        if prod_search_match and not any(w in t_clean for w in ["customer", "কাস্টমার", "order", "orders", "অর্ডার", "inventory", "movement", "কত", "সংখ্যা", "আছে"]):
            term = prod_search_match.group(1).strip()
            return AIProviderResponse(
                text=f"Searching product catalog for '{term}'.",
                tool_calls=[ToolCall(name="search_products", arguments={"query": term})],
                provider_name="fallback_rules",
                is_fallback=True,
            )

        # 18. Out of Scope Check:
        if any(w in t_clean for w in ["আবহাওয়া", 'আবহাওয়া', "বৃষ্টি", "weather", "president", "প্রধানমন্ত্রী", "cricket", "ক্রিকেট", "football", "ফুটবল", "movie", "গান", "রান্না", "recipe", "tutorial"]):
            out_of_scope_text = (
                "এই AI সহকারীটি আপনার Shop Management System-এর কাস্টমার, প্রোডাক্ট, অর্ডার, সেলস রিপোর্ট এবং ইনভেন্টরি সম্পর্কিত তথ্য দিয়ে সাহায্য করার জন্য প্রস্তুত। এই সিস্টেমের বাইরের কোনো তথ্যের ক্ষেত্রে সহায়তা করা এর আওতাভুক্ত নয়।"
                if is_bn
                else "This assistant currently supports the features available in your Shop Management System, including customer management, product information, orders, sales reporting, and inventory. That particular service is not currently available in this application."
            )
            return AIProviderResponse(text=out_of_scope_text, provider_name="fallback_rules", is_fallback=True)

        # 19. Conversational Greeting or Help:
        if any(w in t_clean for w in ["hi", "hello", "help", "সালাম", "কেমন আছো", "capabilities"]):
            greeting = (
                "হ্যালো! আমি আপনার শপ ম্যানেজমেন্টের AI সহকারী।\n\n"
                "আমি আপনাকে নিম্নলিখিত বিষয়ে সাহায্য করতে পারি:\n"
                "• **ড্যাশবোর্ড ও সেলস:** 'আজকের বিক্রি কত' বা 'গতকাল কত টাকার sales হয়েছে?'\n"
                "• **কাস্টমার:** 'এখানে কতজন কাস্টমার আছে' বা 'Rahim Ahmed নামে কাস্টমার আছে?'\n"
                "• **অর্ডার হিস্ট্রি:** 'সে মোট কত টাকার order করেছে?' বা 'সাম্প্রতিক অর্ডার দেখাও'\n"
                "• **প্রোডাক্ট ও স্টক:** 'মাউসের স্টক কত?' বা 'আজকে Rice কতটা sell হয়েছে?'\n"
                "• **নতুন এন্ট্রি:** 'আমি একটা নতুন কাস্টমার এড করতে চাই'\n\n"
                "আপনি যেকোনো তথ্য বাংলায় বা ইংরেজিতে জিজ্ঞাসা করতে পারেন।"
                if is_bn
                else "Hello! I am your AI Shop Management Assistant.\n\n"
                "I can help you manage your shop operations via text or voice in English and Bengali:\n"
                "• **Analytics:** 'Show today's total sales' or 'গতকাল কত টাকার sales হয়েছে?'\n"
                "• **Customers:** 'How many customers?' or 'Is there a customer named Rahim Ahmed?'\n"
                "• **Orders:** 'How much did he order in total?' or 'List recent orders'\n"
                "• **Catalog & Sales:** 'Check stock of Mouse' or 'How much Rice was sold today?'\n"
                "• **Create Records:** 'I want to add a new customer'\n\n"
                "How can I assist your business today?"
            )
            return AIProviderResponse(text=greeting, provider_name="fallback_rules", is_fallback=True)

        # 20. Intelligent Clarification instead of canned message:
        clarify_reply = (
            f"আপনার অনুরোধটি বুঝতে পারিনি: \"{latest}\"।\n"
            "আপনি কি কাস্টমার, প্রোডাক্ট, সেলস রিপোর্ট, অর্ডার বা স্টক সম্পর্কিত কোনো তথ্য জানতে চান? অনুগ্রহ করে নির্দিষ্ট করে বলুন।"
            if is_bn
            else f"I could not determine the exact operation for: \"{latest}\".\n"
            "Would you like information on customers, products, sales reports, orders, or stock levels? Please clarify your request."
        )
        return AIProviderResponse(text=clarify_reply, provider_name="fallback_rules", is_fallback=True)


def get_ai_provider() -> AIProvider:
    """
    Factory function returning the configured AI provider with graceful fallback.
    """
    provider_type = (settings.AI_PROVIDER or "gemini").lower().strip()

    if provider_type == "gemini" and settings.GEMINI_API_KEY:
        return GeminiProvider(
            api_key=settings.GEMINI_API_KEY,
            model_name=getattr(settings, "GEMINI_MODEL", "gemini-3.8-flash"),
        )
    elif provider_type == "local" and getattr(settings, "LOCAL_AI_BASE_URL", None):
        return LocalOpenAIProvider(
            base_url=settings.LOCAL_AI_BASE_URL,
            model_name=getattr(settings, "LOCAL_AI_MODEL", "llama3"),
        )

    # Default to robust rule-based fallback if no external provider configured
    return FallbackRuleBasedProvider()
