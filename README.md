# AI-Powered Multi-Hotel Food Ordering System

Production-oriented starter for a Telegram food ordering flow with FastAPI business APIs, PostgreSQL, SQLAlchemy models, a Django Admin panel on the same tables, and a React kitchen dashboard with per-hotel WebSockets.

## Architecture

- `backend/fastapi_app`: Telegram webhook, AI extraction, menu matching, order APIs, status updates, WebSocket broadcasts.
- `admin_panel`: Django Admin only. Its unmanaged models point at the same PostgreSQL tables and order actions call FastAPI.
- `frontend/react_app`: Kitchen dashboard grouped by `NEW`, `PREPARING`, and `READY`.
- PostgreSQL is the single data store. SQLAlchemy/Alembic owns the shared schema.

AI is used only to extract candidate food item names. Prices and final menu choices always come from `menu_items`.

## Setup

1. Copy environment files.

```powershell
Copy-Item .env.example .env
Copy-Item frontend\react_app\.env.example frontend\react_app\.env
```

Set the same `DASHBOARD_TOKEN` in both `.env` files.

2. Start PostgreSQL.

On Windows, start Docker Desktop first, then run:

```powershell
docker compose up -d postgres
```

3. Install and run FastAPI.

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
alembic -c alembic.ini upgrade head
python -m fastapi_app.seed
uvicorn fastapi_app.main:app --host 0.0.0.0 --port 8000
```

To load your Excel workbook instead of the built-in demo menu:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m fastapi_app.import_excel_database --path "C:\Users\samar\OneDrive\Desktop\MultiHotel_FoodDB.xlsx"
```

Run the same command with `--dry-run` first if you only want to check the workbook. The importer reads the workbook sheets by their column headers, creates/updates hotels from `Hotel ID` and `Hotel Name`, and creates/updates menu items from the full menu database sheet. Close the workbook in Excel first if Windows reports that the file is locked. Use `--deactivate-missing` when you want menu items removed from the workbook to become unavailable in the app.

If Docker cannot download PostgreSQL, use SQLite for local development:

```powershell
cd "C:\hotel order syaytem"
$env:DATABASE_URL="sqlite:///C:/hotel order syaytem/hotel_orders_dev.db"
$env:DJANGO_DATABASE_URL=$env:DATABASE_URL
$env:AUTO_CREATE_TABLES="1"
$env:PYTHONPATH="backend"
.\.venv\Scripts\python.exe -m fastapi_app.import_excel_database --create-tables --path "C:\Users\samar\OneDrive\Desktop\MultiHotel_FoodDB.xlsx"
```

Use the same `DATABASE_URL` and `DJANGO_DATABASE_URL` values in any terminal where you run FastAPI or Django Admin.

To create a duplicate test database with realistic demo data:

```powershell
cd backend
python -m fastapi_app.create_test_database --drop-existing
```

That creates `hotel_orders_test` and seeds 12 hotels with 72 menu items. To point the app at it temporarily:

```powershell
$env:DATABASE_URL="postgresql+psycopg://hotel:hotel@localhost:5432/hotel_orders_test"
uvicorn fastapi_app.main:app --host 0.0.0.0 --port 8000
```

4. Install and run Django Admin.

```powershell
cd admin_panel
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 0.0.0.0:8001
```

Open `http://localhost:8001/admin/`.

5. Install and run the React dashboard.

```powershell
cd frontend\react_app
npm install
npm run dev
```

Open `http://localhost:5173/`. You can pin a hotel with `?hotel_id=1`.

## Telegram Webhook

Expose FastAPI with a public HTTPS URL, then register the webhook:

```powershell
curl.exe -X POST "https://api.telegram.org/bot$env:TELEGRAM_BOT_TOKEN/setWebhook" `
  -d "url=https://your-domain.com/api/telegram/webhook" `
  -d "secret_token=$env:TELEGRAM_WEBHOOK_SECRET"
```

## Core Endpoints

- `POST /api/telegram/webhook`
- `POST /api/ai/extract`
- `GET /api/menu/search?hotel_id=1&q=dosa`
- `GET /api/menu/match-message?hotel_id=1&message=two dosas`
- `POST /api/orders`
- `PATCH /api/orders/{order_id}/status`
- `GET /api/orders?hotel_id=1`
- `WS /api/ws/hotels/{hotel_id}/orders?token=...`

## Operational Notes

- Use `AI_PROVIDER=openai` with `OPENAI_API_KEY`, or `AI_PROVIDER=gemini` with `GEMINI_API_KEY`.
- Use `AI_PROVIDER=mock` for local testing without network calls.
- Django Admin actions need `FASTAPI_INTERNAL_URL` and `BACKEND_API_KEY` so status changes still trigger WebSockets and Telegram messages.
- For production, run Alembic migrations instead of `AUTO_CREATE_TABLES=1`, use strong secrets, terminate TLS at a reverse proxy, and restrict dashboard/API keys.
