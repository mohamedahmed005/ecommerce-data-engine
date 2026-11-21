# 06. API Documentation

## Overview

The backend is a **FastAPI** application (`api/main.py`, version `1.0.0`) served via Uvicorn with full OpenAPI 3 documentation at `/docs`.

- **Local Base URL:** `http://127.0.0.1:8000`
- **Production Base URL:** `https://ecommerce-api-v2.icycliff-7a2355f7.francecentral.azurecontainerapps.io`
- **CORS:** Enabled (`allow_origins=["*"]`, `allow_methods=["*"]`, `allow_headers=["*"]`).
- **Database Access:** `api/db.py` uses `psycopg2.pool.ThreadedConnectionPool(minconn=2, maxconn=10, connect_timeout=30)` with `RealDictCursor`.
- **Analytics Caching:** `api/routers/analytics.py` caches KPI and dashboard responses in memory for **1 hour (`CACHE_TTL_SECONDS = 3600`)** and pre-warms all years and data scopes via a background daemon thread at startup.

---

## System & Frontend Routes

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Serves `landing.html` (excluded from OpenAPI schema) |
| `GET` | `/dashboard` | Serves `index.html` Executive Dashboard (excluded from OpenAPI schema) |
| `GET` | `/chat` | Serves `chat.html` AI Analytics Assistant (excluded from OpenAPI schema) |
| `GET` | `/enhance.js` | Serves shared progressive UX JavaScript layer |
| `GET` | `/docs` | Interactive Swagger UI API documentation |
| `GET` | `/api/health` | Verifies PostgreSQL connectivity, warehouse readiness, and raw table count |

### `GET /api/health`
**Sample Response (`200 OK`):**
```json
{
  "status": "ok",
  "database": "ecom",
  "warehouse_ready": true,
  "raw_tables_uploaded_count": 9,
  "raw_tables": [
    "customers",
    "geolocation",
    "order_items",
    "order_payments",
    "order_reviews",
    "orders",
    "product_category_translation",
    "products",
    "sellers"
  ]
}
```

---

## Analytics Router (`/api/analytics`)

### `GET /api/analytics/kpis`
Computes executive sales, delivery, review, and inventory KPIs using a **single-pass CTE query** (`valid_items` → `orders_agg` → `rev_agg`) combined with a cached latest-snapshot inventory summary.

**Query Parameters:**
| Parameter | Type | Default | Description |
|---|---|---|---|
| `include_synthetic` | `boolean` | `true` | `true` = Full Timeline (Olist + Synthetic); `false` = Original Olist Only |
| `year` | `integer` | `null` | Optional calendar year filter (e.g., `2018`, `2025`) |

**Sample Response (`200 OK`):**
```json
{
  "include_synthetic": true,
  "scope": "Full Timeline (Olist + Synthetic)",
  "year": null,
  "sales": {
    "total_orders": 478120,
    "total_revenue": 76842190.45,
    "product_revenue": 65910420.10,
    "freight_revenue": 10931770.35,
    "avg_item_value": 124.80,
    "avg_order_value": 160.72
  },
  "delivery": {
    "avg_delivery_days": 12.48,
    "late_order_percentage": 8.12
  },
  "reviews": {
    "avg_review_score": 4.09,
    "total_reviews": 345210
  },
  "inventory": {
    "tracked_products": 32328,
    "products_tracked": 32328,
    "low_stock_products": 4120,
    "out_of_stock_products": 318
  }
}
```

### `GET /api/analytics/dashboard`
Returns all datasets required to populate the multi-panel Executive Dashboard (`index.html`).

**Query Parameters:** Same as `/api/analytics/kpis` (`include_synthetic`, `year`).

**Response Payload Fields:**
| Key | Grain / Limit | Description |
|---|---|---|
| `monthly_sales` | All months in scope | `year`, `month`, `month_name`, `total_orders`, `total_sales` (cached independently per scope) |
| `top_categories` | Top 10 by revenue | `category_name_en`, `total_orders`, `total_sales`, `sales_share_percentage` |
| `low_stock_alerts` | Top 10 most urgent | Latest snapshot SKUs where `is_low_stock = TRUE`, ordered by lowest `closing_stock` and highest `units_sold_last_month` |
| `geo_states` | Top 10 states | `state`, `total_orders`, `total_sales`, `avg_delivery_days`, `late_pct` |
| `payment_methods` | All payment types | `payment_type`, `payment_count`, `total_value`, `avg_installments` |
| `top_sellers` | Top 8 sellers | `seller_id`, `seller_city`, `seller_state`, `total_orders`, `total_sales`, `late_pct` |

---

## Inventory-Aware Recommendations Router (`/api/recommendations`)

Implemented in `api/routers/recommendations.py`, this engine joins `warehouse.fact_sales`, `warehouse.fact_reviews`, `warehouse.dim_product`, and the latest snapshot of `warehouse.fact_inventory` to ensure recommended SKUs are commercially relevant and stocked.

### `GET /api/recommendations/samples`
Returns available product categories, top 20 high-volume products (with live closing stock), and top 20 repeat customers (`>= 2` valid orders) for UI selectors and testing.

### `GET /api/recommendations/product/{product_id}`
Generates hybrid product-to-product recommendations using co-purchase affinity, category match, customer ratings, demand velocity, healthy stock bonus, and price proximity.

**Path & Query Parameters:**
- `product_id` (`string`, required): Natural Olist product ID (`404` if not found in `warehouse.dim_product`).
- `limit` (`integer`, default `8`, range `1–25`).
- `in_stock_only` (`boolean`, default `true`): Filters strictly for `closing_stock > 0`.

**Hybrid Scoring Formula:**
```text
recommendation_score =
    (co_purchase_count * 25.0)
  + (30.0 if same category else 0.0)
  + (avg_review_score * 5.0)
  + min(total_orders / 20.0, 25.0)
  + (10.0 if closing_stock > reorder_level else 0.0)
  - min(|candidate_avg_price - target_avg_price| / 25.0, 15.0)
```
Assigns human-readable `recommendation_reason`: `'Frequently Bought Together'`, `'Top Rated in Same Category'`, or `'Popular Alternative'`.

### `GET /api/recommendations/customer/{customer_unique_id}`
Generates personalized recommendations tailored to a customer's purchase history while excluding items they have already bought.

**Path & Query Parameters:**
- `customer_unique_id` (`string`, required): Natural unique customer ID (`404` if not found).
- `limit` (`integer`, default `8`, range `1–25`).
- `in_stock_only` (`boolean`, default `true`).

**Personalized Scoring Formula:**
```text
recommendation_score =
    (customer_category_purchases * 30.0)
  + (avg_review_score * 6.0)
  + min(total_orders / 15.0, 30.0)
  + (15.0 if closing_stock > reorder_level else 0.0)
```
Returns `customer`, `purchase_history` (last 15 valid items), and ranked `recommendations`.

### `GET /api/recommendations/trending`
Returns high-velocity products with **healthy inventory buffers** (`closing_stock > reorder_level`), ordered by `units_sold` in the latest snapshot and historical `total_orders`.

**Query Parameters:**
- `category` (`string`, optional): Exact `category_name_en` filter (e.g., `health_beauty`).
- `limit` (`integer`, default `10`, range `1–30`).

---

## AI Analytics Assistant Router (`/api/chat`)

### `POST /api/chat`
Routes natural-language English or Arabic business questions to governed SQL reports, trending in-stock product recommendations, or the executive KPI summary.

**Request Body (`ChatRequest`):**
```json
{
  "message": "Show low stock products that need reorder",
  "include_synthetic": true
}
```

**Response Structure (`200 OK`):**
```json
{
  "intent": "inventory_analytics",
  "title": "Low-Stock Products at the Latest Snapshot",
  "answer": "Here is the live warehouse report for **Low-Stock Products at the Latest Snapshot** (20 records returned from `warehouse.fact_inventory`).",
  "query_id": 18,
  "data": [ ... ],
  "recommendations": []
}
```

---

## Frontend-to-API Integration Map

| Frontend Asset | Consumed Endpoints |
|---|---|
| `landing.html` + `enhance.js` | `GET /api/analytics/kpis?include_synthetic=true` |
| `index.html` (`/dashboard`) | `GET /api/analytics/kpis`, `GET /api/analytics/dashboard`, `GET /api/health` |
| `chat.html` (`/chat`) | `POST /api/chat` |
