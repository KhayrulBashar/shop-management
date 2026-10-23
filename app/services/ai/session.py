import asyncio
from datetime import datetime, timedelta, timezone
import secrets
from typing import Any
from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str  # "user", "assistant", "system", "tool"
    content: str
    tool_name: str | None = None
    tool_call_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PendingAction(BaseModel):
    action_token: str
    session_id: str
    user_id: int
    tool_name: str
    arguments: dict[str, Any]
    preview_title: str
    preview_summary: str
    preview_details: dict[str, Any]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime


class SessionManager:
    """
    In-memory thread-safe conversation session and pending-action manager.
    Enforces TTL expiration, maximum history limits, and single-use confirmation tokens.
    """

    def __init__(self, ttl_minutes: int = 10, max_messages_per_session: int = 40):
        self.ttl_minutes = ttl_minutes
        self.max_messages_per_session = max_messages_per_session
        self._sessions: dict[str, list[ChatMessage]] = {}
        self._session_users: dict[str, int] = {}
        self._session_last_active: dict[str, datetime] = {}
        self._pending_actions: dict[str, PendingAction] = {}
        self._session_contexts: dict[str, dict[str, Any]] = {}
        self._pending_workflows: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def get_or_create_session(self, session_id: str | None, user_id: int) -> str:
        async with self._lock:
            if not session_id:
                new_id = f"sess_{secrets.token_hex(8)}"
                self._sessions[new_id] = []
                self._session_users[new_id] = user_id
                self._session_last_active[new_id] = datetime.now(timezone.utc)
                return new_id

            if session_id not in self._sessions:
                self._sessions[session_id] = []
                self._session_users[session_id] = user_id
                self._session_last_active[session_id] = datetime.now(timezone.utc)
                return session_id

            # Verify session ownership
            if self._session_users.get(session_id) != user_id:
                # Security isolation: if user mismatch, create fresh session
                new_id = f"sess_{secrets.token_hex(8)}"
                self._sessions[new_id] = []
                self._session_users[new_id] = user_id
                self._session_last_active[new_id] = datetime.now(timezone.utc)
                return new_id

            self._session_last_active[session_id] = datetime.now(timezone.utc)
            return session_id

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        tool_name: str | None = None,
        tool_call_id: str | None = None,
    ):
        async with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = []
            
            msg = ChatMessage(
                role=role,
                content=content,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
            )
            self._sessions[session_id].append(msg)

            # Trim history to max limit to prevent unbounded memory growth
            if len(self._sessions[session_id]) > self.max_messages_per_session:
                self._sessions[session_id] = self._sessions[session_id][-self.max_messages_per_session:]

            self._session_last_active[session_id] = datetime.now(timezone.utc)

    async def get_history(self, session_id: str, user_id: int) -> list[dict[str, Any]]:
        async with self._lock:
            if session_id not in self._sessions or self._session_users.get(session_id) != user_id:
                return []
            return [
                {
                    "role": m.role,
                    "content": m.content,
                    "tool_name": m.tool_name,
                    "created_at": m.created_at.isoformat(),
                }
                for m in self._sessions[session_id]
            ]

    async def clear_history(self, session_id: str, user_id: int):
        async with self._lock:
            if self._session_users.get(session_id) == user_id:
                self._sessions[session_id] = []
                self._session_contexts.pop(session_id, None)
                self._pending_workflows.pop(session_id, None)

    async def get_session_context(self, session_id: str) -> dict[str, Any]:
        async with self._lock:
            return dict(self._session_contexts.get(session_id, {}))

    async def update_session_context(self, session_id: str, updates: dict[str, Any]):
        async with self._lock:
            ctx = self._session_contexts.setdefault(session_id, {})
            ctx.update(updates)

    async def get_pending_workflow(self, session_id: str) -> dict[str, Any] | None:
        async with self._lock:
            wf = self._pending_workflows.get(session_id)
            if not wf:
                return None
            expires = wf.get("expires_at")
            if expires and datetime.now(timezone.utc) > expires:
                self._pending_workflows.pop(session_id, None)
                return None
            return dict(wf)

    async def set_pending_workflow(self, session_id: str, workflow: dict[str, Any]):
        async with self._lock:
            if "expires_at" not in workflow:
                workflow["expires_at"] = datetime.now(timezone.utc) + timedelta(minutes=self.ttl_minutes)
            self._pending_workflows[session_id] = workflow

    async def clear_pending_workflow(self, session_id: str):
        async with self._lock:
            self._pending_workflows.pop(session_id, None)

    async def create_pending_action(
        self,
        session_id: str,
        user_id: int,
        tool_name: str,
        arguments: dict[str, Any],
        preview_title: str,
        preview_summary: str,
        preview_details: dict[str, Any],
    ) -> PendingAction:
        async with self._lock:
            action_token = f"act_{secrets.token_urlsafe(16)}"
            now = datetime.now(timezone.utc)
            action = PendingAction(
                action_token=action_token,
                session_id=session_id,
                user_id=user_id,
                tool_name=tool_name,
                arguments=arguments,
                preview_title=preview_title,
                preview_summary=preview_summary,
                preview_details=preview_details,
                created_at=now,
                expires_at=now + timedelta(minutes=self.ttl_minutes),
            )
            self._pending_actions[action_token] = action
            return action

    async def get_pending_action(self, action_token: str, user_id: int) -> PendingAction | None:
        async with self._lock:
            action = self._pending_actions.get(action_token)
            if not action:
                return None
            if action.user_id != user_id:
                return None
            if datetime.now(timezone.utc) > action.expires_at:
                self._pending_actions.pop(action_token, None)
                return None
            return action

    async def consume_pending_action(self, action_token: str, user_id: int) -> PendingAction | None:
        """
        Atomically fetch and remove the pending action to guarantee single-use execution (prevents replay attacks).
        """
        async with self._lock:
            action = self._pending_actions.get(action_token)
            if not action:
                return None
            if action.user_id != user_id:
                return None
            if datetime.now(timezone.utc) > action.expires_at:
                self._pending_actions.pop(action_token, None)
                return None
            # Invalidate immediately
            return self._pending_actions.pop(action_token)

    async def cancel_pending_action(self, action_token: str, user_id: int) -> bool:
        async with self._lock:
            action = self._pending_actions.get(action_token)
            if not action or action.user_id != user_id:
                return False
            self._pending_actions.pop(action_token, None)
            return True


# Global singleton instance
session_manager = SessionManager()
