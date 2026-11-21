# 05. Data Quality Framework

## Quality Philosophy

The platform enforces a **three-tier, non-destructive data quality strategy**:
1. **Profile & Measure Early (`raw`):** Quantify every anomaly present in source CSVs before transformation.
2. **Flag, Never Silently Drop (`staging` & `warehouse`):** Suspicious rows are preserved with explicit boolean indicators so financial aggregates reconcile to the cent against raw inputs.
3. **Automate & Persist Audits (`dq` schema):** Every profiling and validation run writes structured records to PostgreSQL (`dq.*`) and generates human-readable Markdown reports under `docs/`.

---

## Tier 1: Raw Data Profiling (`profiling/profile_raw.py`)

Running `python profiling/profile_raw.py` inspects all 9 `raw.*` tables and populates two audit tables:
- `dq.column_profile`: Per-column `total_rows`, `null_rows`, `null_pct`, `distinct_values`, `min_value`, `max_value` tagged with `run_id` and `run_at`.
- `dq.check_results`: Per-check `category`, `severity` (`high`, `medium`, `low`), `failed_rows`, `total_rows`, `fail_pct`, and `status` (`PASS` / `FAIL`).
- Markdown Output: `docs/profiling_report.md`.

### Key Source Anomalies Discovered (38 Raw Checks: 19 PASS, 19 Documented Anomalies)

| Check Name | Table | Category | Severity | Failed Rows | Remediation in Staging / Warehouse |
|---|---|---|---:|---:|---|
| `delivered_without_delivery_date` | `orders` | Completeness | High | 8 | Flagged `flag_delivered_no_date`; excluded from `is_delivered` |
| `carrier_before_purchase` | `orders` | Consistency | High | 166 | Flagged `flag_carrier_before_purchase` & `has_date_anomaly` |
| `pk_order_reviews_review_id` | `order_reviews` | Uniqueness | Medium | 814 | Composite PK `(review_id, order_id)`; exact duplicates collapsed (latest answer wins) |
| `fk_products_category_translation` | `products` | Integrity | Medium | 13 | Added 2 missing translations manually in `staging.category_translation` |
| `orders_without_items` | `orders` | Integrity | Medium | 775 | Flagged `has_items = FALSE`; excluded from `is_valid_sale` |
| `orders_without_payments` | `orders` | Integrity | Medium | 1 | Flagged `has_payment = FALSE` |
| `products_null_category` | `products` | Completeness | Medium | 610 | Coalesced to `'unknown'` with `flag_missing_category = TRUE` |
| `products_zero_weight` | `products` | Validity | Medium | 4 | Coerced `0` to `NULL` with `flag_zero_weight = TRUE` |
| `payments_zero_installments` | `order_payments` | Validity | Medium | 2 | Normalized to `1` via `GREATEST(installments, 1)` with `flag_installments_fixed` |
| `geolocation_outside_brazil` | `geolocation` | Validity | Medium | 42 | Filtered using Brazil lat/lng bounding box (`-34..6`, `-74..-34`) |
| `delivered_before_carrier` | `orders` | Consistency | Medium | 23 | Flagged `flag_delivered_before_carrier` & `has_date_anomaly` |
| `non_delivered_with_delivery_date` | `orders` | Consistency | Medium | 6 | Flagged `flag_delivery_date_not_delivered` |
| `review_before_purchase` | `order_reviews` | Consistency | Medium | 74 | Flagged `flag_review_before_purchase` |
| `payment_vs_items_mismatch` | `orders` | Consistency | Medium | 249 | Flagged `flag_payment_mismatch` (`abs(items_total - payments_total) > 1.00`) |
| `dup_geolocation_rows` | `geolocation` | Uniqueness | Low | 261,831 | Aggregated to 1 row per `zip_code_prefix` (avg lat/lng, modal city/state) |
| `fk_customers_zip_geolocation` | `customers` | Integrity | Low | 278 | Fallback zip prefixes inserted into `dim_geography` with `NULL` coordinates |
| `reviews_without_comment` | `order_reviews` | Completeness | Low | 58,247 | Tracked via `has_comment` boolean in `fact_reviews` |
| `payments_not_defined_type` | `order_payments` | Validity | Low | 3 | Flagged `flag_type_not_defined = TRUE` |

All 19 core structural checks (primary keys on `customers`, `orders`, `products`, `sellers`, `order_items`, `order_payments`; foreign keys between orders/items/payments/reviews; non-negative prices, freight, payments; valid review scores 1–5; valid order statuses and state codes) **PASSED with 0 failures**.

---

## Tier 2: Staging & ETL Inline Gates

1. **Staging Validation (`staging/run_staging.py`):** Executes **25 checks** immediately after building `staging.*`, proving zero unintended row loss from `raw.*` and confirming exact reproduction of all documented anomaly flag counts (e.g., `8` delivered without date, `166` carrier before purchase, `73` category translations, `0` unmapped non-null English product categories).
2. **ETL Validation (`warehouse/run_etl.py`):** Executes **31 checks** immediately after loading `warehouse.*`, verifying dimension/fact row counts, exact monetary totals (`SUM(price)`, `SUM(freight_value)`, `SUM(payment_value)`), zero unexpected `-1` Unknown references, primary key uniqueness, and logical flag alignment. Exits with status code `1` if any check mismatches.

---

## Tier 3: Independent Gold Warehouse DQ Suite (`warehouse/run_dq_checks.py`)

Runs **69 standalone SQL tests** across 10 quality categories, persists outcomes to `dq.warehouse_check_results`, and publishes `docs/warehouse_dq_report.md`.

### Latest Verified Warehouse DQ Summary

| Category | Checks | Pass | Fail | Warn | What It Validates |
|---|---:|---:|---:|---:|---|
| **Reconciliation** | 10 | 10 | 0 | 0 | Row counts, distinct orders, and exact sums (`price`, `freight_value`, `payment_value`) match `staging` |
| **Uniqueness** | 6 | 6 | 0 | 0 | Zero duplicate PKs or natural keys across facts and dimensions |
| **Referential Integrity** | 13 | 13 | 0 | 0 | Zero orphan foreign keys across all dimension and role-playing date links |
| **Unknown Members** | 3 | 3 | 0 | 0 | Zero fact rows unexpectedly pointing to `-1` Unknown members |
| **Completeness** | 5 | 5 | 0 | 0 | Zero unexpected `NULL` measures, order statuses, purchase dates, or review scores |
| **Validity** | 7 | 7 | 0 | 0 | No negative amounts, review scores outside 1–5, `delivery_days < 0` or `> 365`, known Olist `payment_value = 0` anomaly pinned at exact baseline (`9`), synthetic zero-payments = `0` |
| **Consistency** | 7 | 7 | 0 | 0 | `is_valid_sale`, `is_valid_item`, `is_delivered`, `delivery_days`, `delay_days`, and date ordering align strictly |
| **Olist Reference Results** | 4 | 4 | 0 | 0 | Deterministic original Olist baselines: `112,101` valid sales, `549` invalid sales, `110,189` delivered items, `775` orders without items |
| **Synthetic Demo Data** | 3 | 3 | 0 | 0 | `is_synthetic` consistency across `fact_sales`, `fact_payments`, and `fact_reviews`; zero invalid synthetic keys |
| **Inventory (Synthetic)** | 11 | 11 | 0 | 0 | Non-empty snapshots, PK uniqueness, FK integrity to `dim_product`/`dim_date`, non-negative stock, accounting equation (`opening + received - sold = closing`), month-over-month stock continuity, `units_sold` exact match to `fact_sales`, `reorder_level >= 1`, `is_low_stock` accuracy, stock-out rate `<= 5%` |
| **Total** | **69** | **69** | **0** | **0** | **100% Pass Rate** |

---

## Severity Model & Extending Checks

- **`error` severity:** Any mismatch between `actual` and `expected` marks the check `FAIL` and causes `warehouse/run_dq_checks.py` to exit with code `1` (blocking automated runs).
- **`warn` severity:** Flags known non-blocking anomalies without halting the pipeline.
- **Adding Raw Checks:** Append a tuple `(name, table, category, severity, description, failed_sql, total_sql)` to `CHECKS` in `profiling/profile_raw.py`.
- **Adding Warehouse Checks:** Register a new check via `add(category, name, sql, expected=0, severity="error")` in `warehouse/run_dq_checks.py`.
