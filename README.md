# Shop Management System · Enterprise ERP Web Application

A complete, modern, production-grade **Shop Management System** tailored for small and medium online shops and businesses as an affordable, high-efficiency ERP alternative. Engineered with Python 3.12, FastAPI (Async), SQLAlchemy 2.0 (Async), PostgreSQL (`asyncpg`), Jinja2, Tailwind CSS, Lucide icons, and Chart.js.

---

## 🌟 Architecture & Key Features

### 1. Technology Stack
- **Language**: Python 3.12
- **Backend**: FastAPI (Async), Pydantic v2
- **Database**: PostgreSQL (SQLAlchemy 2.x async + `asyncpg`)
- **Schema Management**: Automatic table verification on startup + Alembic migrations ready
- **Frontend**: Jinja2 Templates + Tailwind CSS (Custom Dark Modern Brand Config) + Vanilla JavaScript (Fetch API)
- **Icons**: Lucide Icons (CDN)
- **Charts**: Chart.js (CDN)
- **Authentication**: JWT (Stored in secure HttpOnly cookie) + bcrypt password hashing
- **Configuration**: `.env` file (Zero hardcoded secrets)
- **Running Command**: `uvicorn app.main:app --reload`

---

### 2. Complete Authentication Flow
1. **First-Run Administrator Setup (`/register`)**:
   - On a fresh installation where no users exist in the database, visiting `/` or `/register` presents the Administrator Registration form (Full Name, Email, Password, Confirm Password).
   - The first registered user automatically becomes the **System Administrator** (`is_admin = True`).
   - Immediately upon registration, the `/register` endpoint is locked to protect instance security, and all public registrations are closed.
2. **Administrator Login (`/login`)**:
   - Secure login with Email and Password.
   - On success, sets an encrypted HttpOnly cookie `access_token` and redirects to `/dashboard`.
3. **Session Protection**:
   - All protected dashboard pages and API endpoints require an active session. Unauthenticated requests are immediately redirected to `/login`.
   - Logout button destroys the cookie and redirects to `/login`.
4. **Database Startup Verification**:
   - The FastAPI lifespan checks PostgreSQL connectivity on startup, printing a clean diagnostic log.

---

### 3. Dashboard Layout
- **Permanent Left Sidebar** featuring the **5 Core Feature Menus**:
  1. 📦 **Products**: Catalog management, pricing, SKU tracking, category filter.
  2. 👥 **Customers**: Client directory, contact numbers, order histories.
  3. 🛒 **Orders**: Customer sales orders with dynamic multi-item line calculator.
  4. 🔄 **Inventory**: Stock movement audit trail (IN, OUT, ADJUSTMENT).
  5. ⚠️ **Low Stock**: Safety threshold monitor with dynamic count badge and quick replenishment.
- **Top Home Section**: 📊 **Overview Analytics** with 5 Stat Cards (Total Products, Total Customers, Total Orders, Total Revenue, Low Stock Count), 7-day revenue trend chart (Chart.js), and recent orders table.
- **Footer**: User Profile card with initials avatar and Logout button.
- **Responsive Navigation**: Full mobile support with hamburger drawer and glassmorphic backdrop.

---

### 4. Five Core Features Details

#### 📦 Feature 1: Product Management
- **Fields**: `name`, `sku` (unique), `category`, `price` (Numeric 12,2), `stock_quantity`, `reorder_level`.
- **Operations**: Create, Read, Update, Delete with live search, category filtering, and pagination.
- **Validations**: Duplicate SKU prevention, negative price/stock protection.
- **Data Integrity**: Products with existing orders cannot be hard-deleted to preserve financial audit history.

#### 👥 Feature 2: Customer Management
- **Fields**: `name`, `phone`, `email`, `address`, `notes`.
- **Operations**: Full CRUD, search by name/phone/email, total order count indicator.
- **Order History Modal**: View all past orders placed by the customer with date, items, line totals, and status.

#### 🛒 Feature 3: Order Management & Automated Stock Sync
- **Order Creation**: Select customer and add multiple items with live price display, quantity validator, and automatic grand total calculation.
- **Order Statuses**: `Pending`, `Processing`, `Shipped`, `Delivered`, `Cancelled`.
- **Payment Statuses**: `Unpaid`, `Partial`, `Paid`.
- **Automated Stock Sync**:
  - Placing an order validates that requested stock $\le$ available stock. If stock is insufficient, a clear user-friendly error is returned.
  - Automatically deducts stock and records a `StockMovement (OUT)` with reason referencing the order number.
  - If an order is **Cancelled**, stock is automatically restored and a `StockMovement (IN)` is recorded.
  - If a Cancelled order is reactivated, stock is verified and deducted again.
- **Official Sales Invoice**: Professional invoice modal with printable styling (`window.print()`).

#### 🔄 Feature 4: Inventory & Stock Movement Tracking
- **Direct Movement Actions**: Form to record `Stock IN`, `Stock OUT`, and `Stock ADJUSTMENT`.
- **Audit History**: Complete log of Date, Product, Type, Quantity, Previous $\to$ New Stock, Audit Reason, and Logged By User.
- **Filters**: Filter by movement type (`IN`, `OUT`, `ADJUSTMENT`) and search by product or reason.
- **Atomic Transactions**: All inventory changes execute inside strict SQLAlchemy async database transactions.

#### ⚠️ Feature 5: Low Stock Monitoring
- **Automatic Listing**: Dynamically filters all products where `stock_quantity <= reorder_level`.
- **Visual Health**: Progress bar comparing current stock to safety reorder threshold.
- **Urgency Badges**: `DANGER: 0 STOCK` for out-of-stock items, `WARNING: LOW` for near-depletion items.
- **One-Click Replenishment**: Direct **"Stock In"** button on each row that opens the Stock In modal pre-filled with that product.

---

### 5. UI/UX Design System (Dark Modern Theme)
Configured using the exact requested color palette:
- `brand-bg`: `#020617` (Deepest Navy)
- `brand-card`: `#0F172A` (Slate Glass Card)
- `brand-cardSub`: `#1E293B` (Sub-container & inputs)
- `brand-border`: `#334155` (Subtle borders)
- `brand-cyan`: `#22D3EE` & `brand-cyanLight`: `#67E8F9` (Accents & Highlights)
- `brand-indigo`: `#6366F1` & `brand-indigoDark`: `#4F46E5` (Primary Buttons)
- `brand-purpleAura`: `#A855F7` (Ambient background blur glow)
- `brand-success`: `#10B981` (Paid, Delivered, Stock In)
- `brand-warning`: `#F59E0B` (Low Stock, Pending, Partial)
- `brand-danger`: `#F43F5E` (Delete, Out of Stock, Cancelled)

---

## 🚀 Step-by-Step Setup & Run Guide

### Step 1: Create PostgreSQL Database
In your PostgreSQL shell (`psql` or pgAdmin), run:
```sql
CREATE DATABASE shop_manage_db;
```

### Step 2: Set up Python Virtual Environment
```powershell
# Open terminal in shop-management/
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### Step 3: Install Required Dependencies
```powershell
pip install -r requirements.txt
```

### Step 4: Configure Environment Variables
Copy `.env.example` to `.env` and enter your PostgreSQL credentials:
```ini
DATABASE_URL=postgresql+asyncpg://postgres:your_password@localhost:5432/shop_manage_db
SYNC_DATABASE_URL=postgresql+psycopg2://your_password@localhost:5432/shop_manage_db
SECRET_KEY=shop-management-super-secret-jwt-key-2026-production
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440
PROJECT_NAME=Shop Management System
API_V1_STR=/api
```

### Step 5: (Optional) Seed Demo Data for Presentation
Run the automated seed script to populate realistic products, customers, and orders:
```powershell
python seed.py
```
> Default Admin credentials created by seed:
> - **Email**: `admin@shop.com`
> - **Password**: `Admin123456`

### Step 6: Start Application
```powershell
uvicorn app.main:app --reload
```
Open your browser and visit: **`http://127.0.0.1:8000`**

---

## 🧪 Automated Testing
Run the automated end-to-end verification suite:
```powershell
python test_app.py
```
Outputs:
- `[PASS] 1. /api/health -> 200 OK`
- `[PASS] 2. /api/auth/status -> has_admin=True`
- `[PASS] 3. /api/auth/login -> 200 OK & HttpOnly access_token cookie set`
- `[PASS] 4. /api/dashboard/stats -> Products, Customers, Orders, Revenue`
- `[PASS] 5. /api/dashboard/low-stock -> Found low stock items`
- `[PASS] 6. /api/products -> Created product & duplicate SKU rejection`
- `[PASS] 7. /api/customers -> Created customer`
- `[PASS] 8. /api/orders -> Automated stock deduction verified`
- `[PASS] 9. Order Cancellation -> Stock restored successfully`
- `[PASS] 10. /api/inventory/movement -> Stock increased via Stock IN`
- `[PASS] 11. HTML Routes -> Dashboard, Login, Register verified`
