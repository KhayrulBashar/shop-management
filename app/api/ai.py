from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.services.ai import ai_orchestrator, session_manager, tool_registry

router = APIRouter(prefix="/ai", tags=["AI Assistant"])


class AIChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000, description="User question or command in English or Bengali")
    session_id: str | None = Field(None, description="Optional active session identifier")


class AIConfirmRequest(BaseModel):
    action_token: str = Field(..., min_length=5, description="Token corresponding to pending operation")


class AICancelRequest(BaseModel):
    action_token: str = Field(..., min_length=5, description="Token to cancel")


@router.post("/chat")
async def chat_with_assistant(
    payload: AIChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Process conversational text or transcribed voice query:
    - Interprets Bengali, Banglish, or English intent.
    - Executes read-only queries directly.
    - Generates structured pending preview for write/mutation operations.
    """
    clean_message = payload.message.strip()
    if not clean_message:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Message cannot be empty.",
        )

    result = await ai_orchestrator.process_chat(
        user_message=clean_message,
        session_id=payload.session_id,
        user=current_user,
        db=db,
    )
    return result


@router.post("/confirm")
async def confirm_action(
    payload: AIConfirmRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Execute a pending mutation after explicit user approval.
    Token is single-use and bound to the authenticated user.
    """
    execution_result = await ai_orchestrator.execute_confirmation(
        action_token=payload.action_token,
        user=current_user,
        db=db,
    )
    if not execution_result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=execution_result.get("message", "Confirmation failed."),
        )
    return execution_result


@router.post("/cancel")
async def cancel_action(
    payload: AICancelRequest,
    current_user: User = Depends(get_current_user),
):
    """Cancel a pending operation."""
    res = await ai_orchestrator.cancel_confirmation(
        action_token=payload.action_token,
        user=current_user,
    )
    return res


@router.get("/history")
async def get_chat_history(
    session_id: str = Query(..., description="Active session ID"),
    current_user: User = Depends(get_current_user),
):
    """Retrieve message history for active user session."""
    history = await session_manager.get_history(session_id, current_user.id)
    return {"session_id": session_id, "messages": history}


@router.delete("/history")
async def clear_chat_history(
    session_id: str = Query(..., description="Session ID to clear"),
    current_user: User = Depends(get_current_user),
):
    """Clear conversation history for the specified session."""
    await session_manager.clear_history(session_id, current_user.id)
    return {"success": True, "message": "Chat history cleared."}


@router.get("/capabilities")
async def get_ai_capabilities(
    current_user: User = Depends(get_current_user),
):
    """
    Retrieve all registered tools, descriptions, parameter schemas, and mutation status.
    """
    tools = tool_registry.get_all()
    return {
        "count": len(tools),
        "tools": [
            {
                "name": t.name,
                "description": t.description,
                "is_mutation": t.is_mutation,
                "parameters": [
                    {
                        "name": p.name,
                        "type": p.type,
                        "description": p.description,
                        "required": p.required,
                        "enum": p.enum,
                    }
                    for p in t.parameters
                ],
            }
            for t in tools
        ],
    }
