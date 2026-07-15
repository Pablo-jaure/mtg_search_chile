# MTG Search Chile — Project Resume & Architecture

## 1. Project Overview

**MTG Search Chile** is a web-based price comparison and shopping tool for Magic: The Gathering cards across 23+ Chilean stores. Users paste a list of card names, the system scrapes all configured stores in parallel, and displays results grouped by card or by store with the cheapest available options, real-time stock verification, and direct links to add products to cart (Shopify & WooCommerce).

### Tech Stack

| Layer          | Technology                                      |
|----------------|-------------------------------------------------|
| **Frontend**   | Flask HTML templates + Bootstrap (server-rendered) |
| **Backend**    | Python 3.10+, Flask                             |
| **Scraper**    | httpx (async), BeautifulSoup4, Shopify JSON API |
| **Database**   | Supabase (PostgreSQL + Auth)                    |
| **External API** | Scryfall (card metadata, images, USD prices)    |
| **Deployment** | Render (Gunicorn + gthread)                     |
| **CI/CD**      | GitHub Actions                                  |

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                    Browser (User)                    │
├─────────────────────────────────────────────────────┤
│                  Flask App (app.py)                  │
│   ┌─────────┐  ┌──────────────┐  ┌──────────────┐  │
│   │ Routes  │  │ Auth/Session │  │ Template     │  │
│   │ (MVC)   │  │ (CSRF, JWT)  │  │ Rendering    │  │
│   └────┬────┘  └──────────────┘  └──────────────┘  │
│        │                                            │
│   ┌────▼────────────────────────────┐               │
│   │  Scraping Engine (async httpx)  │               │
│   │  - 23 stores, 4 concurrent     │               │
│   │  - Shopify API + HTML fallback  │               │
│   │  - WooCommerce HTML parsing     │               │
│   │  - Jumpseller parsing           │               │
│   │  - Scry marketplace parsing     │               │
│   └────┬────────────────────────────┘               │
│        │                                            │
├────────┼────────────────────────────────────────────┤
│        ▼                                            │
│  ┌──────────┐  ┌────────────┐  ┌─────────────────┐ │
│  │ Supabase │  │ Scryfall   │  │ Tiendas Chile    │ │
│  │ (DB+Auth)│  │ (card data)│  │ (23 sitios reales)│ │
│  └──────────┘  └────────────┘  └─────────────────┘ │
└─────────────────────────────────────────────────────┘
```

### Data Flow

1. **User inputs** a list of cards (plain text, supports Arena/MTGO/Moxfield formats)
2. **Flask** parses the list and triggers `asyncio.run(cotizar_web())`
3. **Scraping engine** creates 4 concurrent semaphores → one HTTP request per (card × store) pair → up to `23 × N` requests
4. **Each scraper** (Shopify JSON / WooCommerce HTML / Jumpseller / Scry) extracts matching products, prices, and links
5. **Stock verification** (async): for each found product, hits its detail page to confirm real availability and get actual lowest price + variant IDs
6. **Scryfall** fetches card images and USD prices in parallel
7. **Results** are aggregated by card and by store → `crear_resumen_tiendas()` builds cart-enabled summaries
8. **Supabase** persists the search run (if user is authenticated)
9. **Template** renders the full result page with per-card tables, per-store summaries, cart links, and diagnostics

---

## 3. File Structure

```
/
├── app.py                          # Flask application (routes, auth, views, cart logic)
├── mtg_cotizador.py                # Core scraping engine (23 store configs, parsers, async logic)
├── supabase_store.py               # Supabase client (CRUD for users, searches, wishlists, carts, admin)
├── render.yaml                     # Render deployment config
├── requirements.txt                # Production dependencies
├── requirements-dev.txt            # Dev/test dependencies
├── iniciar_web.bat                 # Windows quick-start script
├── .env                            # Environment variables (FLASK_SECRET_KEY, SUPABASE_*)
├── .gitignore                      # Git ignore rules
├── README.md                       # Quick-start instructions
├── PLAN_WOOCOMMERCE_CARRITO.md     # WooCommerce cart integration planning
│
├── templates/                      # Flask Jinja2 templates
│   ├── base.html                   # Layout (Bootstrap, navbar, footer)
│   ├── index.html                  # Home page: input form + search results
│   ├── auth_callback.html          # OAuth callback handler
│   ├── account.html                # User profile/account page
│   ├── favorite_stores.html        # Favorite stores management
│   ├── search_history.html         # Past search runs
│   ├── search_detail.html          # Detail view of a past search
│   ├── cart_history.html           # Cart event history
│   ├── admin.html                  # Admin dashboard (users, audit, metrics)
│   └── wishlist.html               # Wishlist with price alerts
│
├── tests/
│   ├── test_app.py                 # Flask route tests
│   └── test_supabase_store.py      # Supabase store unit tests
│
└── supabase/                       # Supabase project files
    ├── config.toml                 # Supabase CLI config
    ├── migrations/                 # Database migrations
    ├── functions/                  # Edge Functions (price tracker)
    ├── cron/                       # Cron job configs
    └── tests/                      # Supabase tests
```

---

## 4. Core Modules

### 4.1 Flask Application (`app.py`)

**Key components:**

- **Session/Auth**: CSRF tokens per session, Google OAuth via Supabase, `sb_access_token` cookie.
- **Middleware**: `load_request_user()` runs before every request → validates session cookie.
- **Decorators**: `login_required` and `admin_required` for protected routes.
- **Routes**:
  - `GET /` → home page with input form
  - `POST /` → parse list, run scraper, render results
  - `/auth/*` → OAuth callback, session creation, logout
  - `/account/*` → profile, favorites, deletion request
  - `/wishlist/*` → CRUD for tracked cards + price alerts
  - `/history/*` → past searches and cart events
  - `/admin/*` → admin panel (user management, metrics, audit logs)
  - `/internal/price-tracker/check` → HMAC-protected endpoint for scheduled price checks
  - `/api/cart-events` → log user clicks on "go to cart"

**Cart integration logic** (`crear_resumen_tiendas()`):
- For each store with results, selects the cheapest variant per card
- Builds Shopify cart URLs (`/cart/variant1:1,variant2:1,...`)
- Builds WooCommerce cart URLs (`/?add-to-cart=X&quantity=1`)
- Tracks platform type (`shopify`, `woocommerce`) for UI rendering

### 4.2 Scraping Engine (`mtg_cotizador.py`)

**23 stores** configured across 4 platform types:

| Type              | Count | Method                                      |
|-------------------|-------|---------------------------------------------|
| **Shopify**       | 7     | `/search/suggest.json` + `/product.js` fallback → auto HTML fallback for Cloudflare |
| **WooCommerce**   | 15    | HTML parse → detail page verification for stock & prices |
| **Jumpseller**    | 1     | HTML parse → detail page verification       |
| **Scry Marketplace** | 1  | HTML parse (Next.js SSR)                    |

**Key functions:**

| Function | Purpose |
|---|---|
| `parsear_lista_bulk()` | Parses raw text into deduplicated card names (Arena/MTGO/Moxfield formats) |
| `es_match()` | Fuzzy card name matching between searched and found product title |
| `parse_precio()` | Converts CLP price strings (with/without dots/commas) to integers |
| `buscar_en_tienda()` | Main async scraper: dispatches to the right parser based on store type |
| `actualizar_precios_shopify()` | Shopify-only: hits each product's `.js` endpoint for real stock/price data |
| `verificar_fichas_html()` | WooCommerce/Jumpseller: visits each product detail page to verify stock + extract variant IDs |
| `cotizar_en_paralelo()` | Streamlit interface version of the parallel scraper |
| `cotizar_web()` | Flask-adapted version (returns results dicts directly) |
| `obtener_info_scryfall()` | Fetches card image, canonical name, and USD price from Scryfall |

**Concurrency model:**
- `httpx.AsyncClient` with `max_keepalive_connections=40, max_connections=100`
- `asyncio.Semaphore(4)` limits concurrent requests to the same card/store
- All store × card requests fire simultaneously via `asyncio.gather()`

### 4.3 Supabase Store (`supabase_store.py`)

A thin client wrapping the Supabase REST API (`/rest/v1/*` and `/auth/v1/*`).

**Tables used:**

| Table | Purpose |
|---|---|
| `profiles` | User profiles (display_name, role, status, last_seen_at) |
| `stores` | Chilenas store catalog (id, slug, name, platform) |
| `favorite_stores` | User-store favorite mapping |
| `wishlist_items` | User wishlist with price alert config |
| `search_runs` | Log of each search execution |
| `search_cards` | Cards within a search run |
| `search_results` | Store offers per searched card |
| `cart_events` | Log of user cart clicks |
| `admin_user_summary` | Materialized view for admin panel |
| `admin_audit_log` | Admin action audit trail |
| `price_alert_deliveries` | Delivery logs for price alert notifications |

**RPC functions:**
- `configure_wishlist_price_alert` → upsert price alert config
- `claim_price_tracker_nonce` → idempotent nonce claim for internal price tracker

**Auth:** Uses Supabase's built-in Google OAuth + JWT tokens. The store authenticates via Bearer tokens for per-user requests, and service-role key for admin operations.

---

## 5. Key Features

### 5.1 Price Tracker (Internal)
- HMAC-signed endpoint (`/internal/price-tracker/check`) for scheduled price checks
- Idempotency via nonce table (prevents duplicate processing)
- Used by Supabase Edge Functions (cron-based)
- Returns cheapest offer for a given card name

### 5.2 Wishlist with Alerts
- Users can save cards they're looking for
- Optional price alert: when the cheapest offer drops below a target, a notification is triggered
- Price alert deliveries tracked in the database

### 5.3 Cart Integration
- **Shopify**: builds multi-variant cart URL (`/cart/variant1:1,variant2:1`)
- **WooCommerce**: builds individual add-to-cart URLs with optional variation IDs
- User clicks are logged as `cart_events` for analytics

### 5.4 Admin Dashboard
- User management (role/status changes with protection against last-admin removal)
- Audit log viewer
- Usage metrics (database size, tracker stats, per-store usage, per-card popularity, daily activity)

---

## 6. Deployment

### 6.1 Render (`render.yaml`)
- **Service type**: Web service (free tier)
- **Runtime**: Python
- **Workers**: 1 Gunicorn worker, 4 threads (`gthread` class)
- **Timeout**: 180s (request timeout), 30s graceful shutdown
- **Health check**: `GET /health`
- **Auto-deploy**: off (manual deployments)

### 6.2 Environment Variables
```
FLASK_SECRET_KEY=          # Session signing key
SUPABASE_URL=              # Supabase project URL
SUPABASE_PUBLISHABLE_KEY=  # Anon/public key
SUPABASE_SECRET_KEY=       # Service-role key (admin)
FLASK_ENV=                 # production/development
FLASK_DEBUG=               # 1 for debug mode
PRICE_TRACKER_INTERNAL_SECRET= # HMAC secret for price tracker
PORT=                      # Server port (Render sets this automatically)
```

---

## 7. Security

| Measure | Implementation |
|---|---|
| **CSRF Protection** | Per-session token validated via `X-CSRF-Token` header on all POST/PUT/PATCH/DELETE |
| **Session cookies** | `HttpOnly`, `SameSite=Lax`, `Secure` in production |
| **Auth tokens** | Stored in `sb_access_token` cookie (HttpOnly), validated on every request |
| **Admin protection** | Double-check: `admin_required` decorator + Supabase profile `role == "admin"` |
| **Last-admin lock** | Cannot demote/delete the last active admin |
| **HMAC signatures** | Internal endpoints use timestamp + nonce + HMAC-SHA256 |
| **CORS** | Origin validation on auth session endpoint |
| **Rate limits** | Scraper semaphore (4 concurrent) + 100-card max per search |
| **Input validation** | Card names validated via regex parsing; Supabase params use eq. syntax |

---

## 8. Testing

- **`tests/test_app.py`**: Flask route integration tests
- **`tests/test_supabase_store.py`**: Supabase client unit tests
- **GitHub Actions**: Validates PRs and main branch; auto-deploys from main

---

## 9. Future / Planned Improvements (from `PLAN_WOOCOMMERCE_CARRITO.md`)

- Full WooCommerce cart session simulation (not just redirect URLs)
- Multi-store combined cart
- Price history tracking and charts
- Email/push notifications for price alerts (beyond the current database-based system)