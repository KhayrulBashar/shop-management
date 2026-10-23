from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user, get_current_user_optional
from app.core.security import create_access_token, get_password_hash, verify_password
from app.models.user import User
from app.schemas.auth import (
    AuthStatusResponse,
    UserLogin,
    UserRegister,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.get("/status", response_model=AuthStatusResponse)
async def get_auth_status(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Check if the system has an administrator configured and if current user is logged in."""
    res = await db.execute(select(func.count(User.id)))
    user_count = res.scalar_one() or 0
    return AuthStatusResponse(
        has_admin=user_count > 0,
        is_authenticated=current_user is not None,
        user=UserResponse.model_validate(current_user) if current_user else None,
    )


@router.post("/register", response_model=UserResponse)
async def register_first_admin(
    payload: UserRegister,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """
    Initial setup endpoint. Only the first registered user is allowed,
    and automatically becomes the Administrator.
    Once registered, this endpoint is permanently closed.
    """
    count_res = await db.execute(select(func.count(User.id)))
    existing_users = count_res.scalar_one() or 0
    if existing_users > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="System Administrator already exists. Registration is closed. Please log in.",
        )

    # Check email duplicate just in case
    check_email = await db.execute(select(User).where(User.email == payload.email.lower().strip()))
    if check_email.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An account with this email address already exists.",
        )

    admin_user = User(
        full_name=payload.full_name.strip(),
        email=payload.email.lower().strip(),
        hashed_password=get_password_hash(payload.password),
        is_admin=True,
    )
    db.add(admin_user)
    await db.commit()
    await db.refresh(admin_user)

    # Set HttpOnly authentication cookie
    token = create_access_token(subject=admin_user.id)
    response.set_cookie(
        key="access_token",
        value=f"Bearer {token}",
        httponly=True,
        max_age=86400 * 30,  # 30 days
        samesite="lax",
        secure=False,  # Can run on local HTTP
    )

    return admin_user


@router.post("/login")
async def login(
    payload: UserLogin,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Log in with Email and Password, receiving an HttpOnly auth cookie."""
    stmt = select(User).where(User.email == payload.email.lower().strip())
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()

    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    token = create_access_token(subject=user.id)
    response.set_cookie(
        key="access_token",
        value=f"Bearer {token}",
        httponly=True,
        max_age=86400 * 30,
        samesite="lax",
        secure=False,
    )

    return {
        "success": True,
        "message": "Login successful",
        "user": UserResponse.model_validate(user),
    }


@router.post("/logout")
async def logout(response: Response):
    """Log out user by clearing the HttpOnly cookie."""
    response.delete_cookie(key="access_token")
    return {"success": True, "message": "Successfully logged out."}


@router.get("/me", response_model=UserResponse)
async def get_current_user_profile(current_user: User = Depends(get_current_user)):
    """Retrieve currently logged in user profile."""
    return current_user
