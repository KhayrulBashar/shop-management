from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.user import User

# OpenAPI Security Schemes for Swagger UI (/docs) Authorize button
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/auth/token",
    auto_error=False,
    description="Authorize using admin email and password via OAuth2 password flow",
)
http_bearer = HTTPBearer(
    auto_error=False,
    description="Authorize by directly pasting your JWT access token (Bearer <token>)",
)


def extract_token_from_request(
    request: Request,
    bearer_token: HTTPAuthorizationCredentials | None = None,
    oauth_token: str | None = None,
) -> str | None:
    # 1. Direct credentials from OpenAPI security schemes (Swagger UI or Authorization header)
    if bearer_token and bearer_token.credentials:
        return bearer_token.credentials.strip()
    if oauth_token:
        return oauth_token.strip()

    # 2. Authorization header fallback
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header.replace("Bearer ", "", 1).strip()

    # 3. HttpOnly cookie fallback for browser frontend sessions
    token = request.cookies.get("access_token")
    if token:
        if token.startswith("Bearer "):
            return token.replace("Bearer ", "", 1).strip()
        return token.strip()

    return None


async def get_current_user_optional(
    request: Request,
    db: AsyncSession = Depends(get_db),
    bearer_token: HTTPAuthorizationCredentials | None = Depends(http_bearer),
    oauth_token: str | None = Depends(oauth2_scheme),
) -> User | None:
    token = extract_token_from_request(request, bearer_token=bearer_token, oauth_token=oauth_token)
    if not token:
        return None

    payload = decode_access_token(token)
    if not payload or not payload.get("sub"):
        return None

    user_id = payload.get("sub")
    try:
        user_id_int = int(user_id)
    except (ValueError, TypeError):
        return None

    stmt = select(User).where(User.id == user_id_int)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    bearer_token: HTTPAuthorizationCredentials | None = Depends(http_bearer),
    oauth_token: str | None = Depends(oauth2_scheme),
) -> User:
    user = await get_current_user_optional(
        request,
        db=db,
        bearer_token=bearer_token,
        oauth_token=oauth_token,
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or not authenticated. Please log in.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def get_current_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrative privileges required.",
        )
    return current_user
