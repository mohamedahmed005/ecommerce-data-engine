# 07. AI Analytics Assistant

## Architectural Philosophy: Deterministic SQL-Grounded Routing

Rather than passing raw user text to a generative LLM to write arbitrary SQL at runtime—which introduces SQL injection risk, schema hallucinations, inconsistent metric definitions, and external API latency—`api/routers/chat.py` implements a **governed, bilingual intent-routing architecture**:

1. **100% Numerical Accuracy:** Every metric returned to the user originates directly from pre-audited SQL queries in `sql/warehouse/05_analytical_queries.sql`, `get_executive_kpis()`, or `get_trending_in_stock()`.
2. **Zero SQL Injection Surface:** User input is never interpolated into SQL statements; category filters are matched against the live distinct values of `warehouse.dim_product.category_name_en` and passed via parameterized queries (`%s`).
3. **Bilingual Support (English & Arabic):** Keyword classifiers natively understand both English and Arabic business terminology, paired with automatic RTL/LTR rendering in `chat.html`.
4. **Scope-Aware Analytics:** Respects the `include_synthetic` toggle, dynamically switching between full-timeline queries (Section B) and original Olist benchmark queries (Section A).

---

## Request Execution Lifecycle

```text
User Prompt (EN / AR) + include_synthetic
        │
        ▼
  POST /api/chat (api/routers/chat.py)
        │
        ├── Normalize text: msg = req.message.lower().strip()
        ├── Load governed SQL catalog: load_analytical_queries()
        │
        ▼
  Priority Intent Classifier (11 Branches)
        ├── [1] Product Recommendations ──► Match category in dim_product ──► get_trending_in_stock(limit=6)
        ├── [2] Inventory Analytics     ──► Dispatch Q18 / Q19 / Q20 / Q21
        ├── [3] Delivery & Shipping     ──► Dispatch Q12 (if review) / Q11 / Q2
        ├── [4] Reviews & Ratings       ──► Dispatch Q13 / Q3
        ├── [5] Payment Methods         ──► Dispatch Q14 / Q4
        ├── [6] Product Categories      ──► Dispatch Q8
        ├── [7] Top Sellers             ──► Dispatch Q10
        ├── [8] Geographic States       ──► Dispatch Q15 / Q5
        ├── [9] Customer Retention      ──► Dispatch Q16
        ├── [10] Sales Trends & AOV     ──► Dispatch Q7 (last 24 rows) / Q1
        └── [Default] Executive Summary ──► get_executive_kpis(include_synthetic)
        │
        ▼
  Structured JSON Response { intent, title, answer, query_id, data, recommendations }
```

---

## Bilingual Intent Routing Matrix

Intents are evaluated strictly in the priority order implemented in `api/routers/chat.py`:

| Priority | Intent Name | English Trigger Keywords | Arabic Trigger Keywords | Backend Data Source |
|---:|---|---|---|---|
| 1 | `product_recommendation` | `recommend`, `suggest`, `trending` | `رشح`, `اقترح`, `توصية`, `منتجات` | `get_trending_in_stock(category, limit=6)` |
| 2 | `inventory_analytics` | `stock`, `inventory`, `reorder` *(sub-intents: `cover`/`coverage`, `health`/`monthly`, `best`/`top`)* | `مخزون`, `نواقص`, `رصيد` *(sub-intents: `تغطية`, `شهري`, `أفضل`)* | Q20 (coverage), Q19 (health), Q21 (best vs stock), default Q18 (low stock) |
| 3 | `delivery_analytics` | `delivery`, `delay`, `late`, `shipping` *(+ `review` for delay impact)* | `توصيل`, `تأخير`, `شحن` *(+ `تقييم`)* | Q12 (delay vs reviews), Q11 (full) or Q2 (Olist only) |
| 4 | `review_analytics` | `review`, `rating`, `score`, `star` | `تقييم`, `مراجعات` | Q13 (full) or Q3 (Olist only) |
| 5 | `payment_analytics` | `payment`, `credit`, `boleto`, `voucher`, `installment` | `دفع`, `مدفوعات` | Q14 (full) or Q4 (Olist only) |
| 6 | `category_analytics` | `category`, `categories` | `فئات`, `اقسام`, `أقسام` | Q8 (Top 10 categories) |
| 7 | `seller_analytics` | `seller`, `merchant` | `بائعين`, `تجار` | Q10 (Top 10 sellers) |
| 8 | `state_analytics` | `state`, `region`, `geography` | `ولاية`, `مناطق`, `محافظات` | Q15 (full) or Q5 (Olist only) |
| 9 | `customer_analytics` | `repeat`, `retention`, `spending` | `عملاء`, `تكرار` | Q16 (Customer spending & repeat orders) |
| 10 | `monthly_sales` | `growth`, `aov`, `month`, `trend` | `نمو`, `شهري`, `مبيعات` | Q7 (full, trailing 24 months) or Q1 (Olist only) |
| 11 | `executive_summary` | *(Default fallback)* | *(Default fallback)* | `get_executive_kpis(include_synthetic)` |

### Dynamic Category Matching for Recommendations
When the `product_recommendation` intent matches, the router queries `SELECT DISTINCT category_name_en FROM warehouse.dim_product WHERE category_name_en IS NOT NULL` and checks whether either the exact snake_case category (`health_beauty`) or its space-separated form (`health beauty`) appears in the message. If matched, recommendations are scoped to that category; otherwise, top in-stock trending products across all categories are returned.

---

## Frontend Experience (`chat.html` + `enhance.js`)

The chat interface at `/chat` pairs structured data visualization with conversational ergonomics:
- **Rich Output Rendering:** Displays Markdown-formatted answers, sortable tabular results for SQL reports (`data`), and structured product cards with pricing and stock indicators (`recommendations`).
- **Bilingual Ergonomics:** Automatic RTL/LTR text direction detection for Arabic and English messages.
- **Power-User Enhancements (`enhance.js`):**
  - Command history navigation via `↑` and `↓` arrow keys.
  - Quick focus shortcut via `/` key.
  - Per-message timestamps, one-click copy buttons, and scroll-to-bottom button.
  - Mobile-friendly quick-prompt chips.
  - Local browser chat history persistence across reloads and full transcript export to `.txt`.

---

## Example Queries

**English Prompts:**
- `"What is the total revenue and order count?"` → `executive_summary`
- `"Show top 10 categories by revenue"` → `category_analytics` (Query 8)
- `"Which products are low on stock and need reorder?"` → `inventory_analytics` (Query 18)
- `"How do delivery delays affect customer reviews?"` → `delivery_analytics` (Query 12)
- `"Recommend trending products in health_beauty"` → `product_recommendation` (filtered to `health_beauty`)
- `"Show monthly AOV and sales growth trend"` → `monthly_sales` (Query 7)

**Arabic Prompts:**
- `"عرض نواقص المخزون المطلوب إعادة طلبها"` → `inventory_analytics` (Query 18)
- `"ما هي أفضل الفئات من حيث المبيعات؟"` → `category_analytics` (Query 8)
- `"رشح منتجات متوفرة في health_beauty"` → `product_recommendation`
- `"تحليل طرق الدفع والتقسيط"` → `payment_analytics` (Query 14)

---

## Extending the Assistant

To add a new analytical capability:
1. Add a new numbered query (`-- 22. Query Title`) to `sql/warehouse/05_analytical_queries.sql` (automatically discovered by `api/db.py:load_analytical_queries()`).
2. Add an `if any(k in msg for k in [...]):` branch in `api/routers/chat.py` with both English and Arabic keywords dispatching `queries[22]`.
3. Verify the route via Swagger UI (`/docs`) or `/chat`.
