from contextlib import asynccontextmanager
import logging
from pathlib import Path
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import api_router
from app.core.config import settings
from app.core.database import Base, check_db_connection, engine, get_db
from app.core.deps import get_current_user_optional
from app.models.user import User
import app.models  # Ensures all models are registered on Base.metadata

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("shop_management")

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Test database connection
    try:
        await check_db_connection()
        logger.info("=================================================================")
        logger.info("  [PostgreSQL] Connection established successfully: %s", settings.ASYNC_DATABASE_URL.split('@')[-1])
        logger.info("=================================================================")
    except Exception as exc:
        logger.error("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        logger.error("  [PostgreSQL Error] Unable to connect to the database!")
        logger.error("  Error Details: %s", exc)
        logger.error("  Please check your DATABASE_URL in the .env file.")
        logger.error("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        raise exc

    # 2. Automatically verify and create tables
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("  [Database Schema] Tables verified and created successfully.")
    except Exception as exc:
        logger.error("  [Database Schema Error] Failed to create tables: %s", exc)
        raise exc

    yield

    # Shutdown
    await engine.dispose()
    logger.info("  [System] Database engine closed cleanly.")


app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Modern Production-Quality Shop Management System",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files & Jinja2 Templates
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# Include master API router
app.include_router(api_router)


# ---------------------------------------------------------------------------
# Frontend Page Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def root(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """
    Root entrypoint:
    - If no admin exists in DB -> redirect to /register
    - If logged in -> redirect to /dashboard
    - Otherwise -> redirect to /login
    """
    res = await db.execute(select(func.count(User.id)))
    user_count = res.scalar_one() or 0

    if user_count == 0:
        return RedirectResponse(url="/register", status_code=status.HTTP_302_FOUND)

    if current_user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)

    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)


@app.get("/register", response_class=HTMLResponse, include_in_schema=False)
async def register_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """
    Administrator Registration Page.
    Only accessible when no admin exists in the database.
    """
    res = await db.execute(select(func.count(User.id)))
    user_count = res.scalar_one() or 0

    if current_user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)

    has_admin = user_count > 0

    return templates.TemplateResponse(
        request=request,
        name="register.html",
        context={
            "app_name": settings.PROJECT_NAME,
            "has_admin": has_admin,
        },
    )


@app.get("/login", response_class=HTMLResponse, include_in_schema=False)
async def login_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """User Login Page."""
    if current_user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)

    res = await db.execute(select(func.count(User.id)))
    user_count = res.scalar_one() or 0
    has_admin = user_count > 0

    # If no administrator exists yet, redirect to setup /register
    if not has_admin:
        return RedirectResponse(url="/register", status_code=status.HTTP_302_FOUND)

    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "app_name": settings.PROJECT_NAME,
            "has_admin": has_admin,
        },
    )


@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
async def dashboard_page(
    request: Request,
    current_user: User | None = Depends(get_current_user_optional),
):
    """
    Main Protected Dashboard Page.
    Contains permanent Sidebar with 5 core features:
    1. Products
    2. Customers
    3. Orders
    4. Inventory (Stock Movements)
    5. Low Stock
    """
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "app_name": settings.PROJECT_NAME,
            "user": current_user,
        },
    )


@app.get("/api/health", tags=["System"])
async def health_check():
    """Health check endpoint confirming API and DB status."""
    return {
        "status": "healthy",
        "app": settings.PROJECT_NAME,
        "database": "connected",
        "engine": "PostgreSQL (asyncpg)",
    }
