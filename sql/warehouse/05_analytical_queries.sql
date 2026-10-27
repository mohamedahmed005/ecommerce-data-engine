-- ============================================================
-- Olist E-Commerce Data Warehouse
-- Gold Layer - Analytical Queries
-- Database: PostgreSQL
--
-- Structure:
--   Queries 1-5   : Olist reference (is_synthetic = FALSE). Verified results
--                    used by the DQ pipeline; do NOT change their logic.
--   Queries 6-17  : Full-timeline analytics (Olist 2016-2018 + Synthetic
--                    2018-2026). For dashboards and the AI assistant.
--   Queries 18-21 : Inventory analytics (synthetic stock table).
-- ============================================================


-- ============================================================
--  SECTION A: OLIST REFERENCE QUERIES  (original data only)
--  These exist so the DQ pipeline can verify the ETL produces
--  the same known-good numbers every time.
-- ============================================================


-- 1. Reference: Monthly Sales Performance (Olist Only)

SELECT
    d.year,
    d.month,
    d.month_name,
    COUNT(DISTINCT f.order_id) AS total_orders,
    ROUND(SUM(f.price), 2) AS total_sales,
    ROUND(SUM(f.freight_value), 2) AS total_freight
FROM warehouse.fact_sales AS f
JOIN warehouse.dim_date AS d
    ON f.purchase_date_key = d.date_key
WHERE f.is_valid_sale = TRUE
  AND f.is_synthetic = FALSE
GROUP BY d.year, d.month, d.month_name
ORDER BY d.year, d.month;


-- 2. Reference: Delivery Performance (Olist Only)

WITH order_delivery AS (
    SELECT
        order_id,
        MAX(delivery_days) AS delivery_days,
        MAX(delay_days) AS delay_days
    FROM warehouse.fact_sales
    WHERE is_delivered = TRUE
      AND is_synthetic = FALSE
    GROUP BY order_id
)
SELECT
    COUNT(*) AS delivered_orders,
    ROUND(AVG(delivery_days), 2) AS avg_delivery_days,
    ROUND(AVG(delay_days), 2) AS avg_delay_days,
    ROUND(AVG(delay_days) FILTER (WHERE delay_days > 0), 2) AS avg_delay_days_late_only,
    COUNT(*) FILTER (WHERE delay_days > 0) AS late_orders,
    COUNT(*) FILTER (WHERE delay_days <= 0) AS on_time_or_early_orders,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE delay_days > 0)
        / NULLIF(COUNT(*) FILTER (WHERE delay_days IS NOT NULL), 0),
        2
    ) AS late_order_percentage
FROM order_delivery;


-- 3. Reference: Customer Review Analysis (Olist Only)

SELECT
    review_score,
    COUNT(*) AS total_reviews,
    ROUND(
        100.0 * COUNT(*)
        / NULLIF(SUM(COUNT(*)) OVER (), 0),
        2
    ) AS review_percentage,
    ROUND(
        CAST(SUM(review_score * COUNT(*)) OVER () AS numeric)
        / NULLIF(SUM(COUNT(*)) OVER (), 0),
        2
    ) AS overall_avg_score
FROM warehouse.fact_reviews
WHERE review_score IS NOT NULL
  AND is_synthetic = FALSE
GROUP BY review_score
ORDER BY review_score;


-- 4. Reference: Payment Analysis (Olist Only)

SELECT
    payment_type,
    COUNT(*) AS payment_records,
    COUNT(DISTINCT order_id) AS total_orders,
    ROUND(SUM(payment_value), 2) AS total_payment_value,
    ROUND(AVG(payment_value), 2) AS avg_payment_value
FROM warehouse.fact_payments
WHERE payment_type IS NOT NULL
  AND is_synthetic = FALSE
GROUP BY payment_type
ORDER BY total_payment_value DESC;


-- 5. Reference: Sales by Customer State (Olist Only)

SELECT
    c.customer_state,
    COUNT(DISTINCT f.order_id) AS total_orders,
    COUNT(DISTINCT c.customer_key) AS unique_customers,
    ROUND(SUM(f.price), 2) AS total_sales,
    ROUND(
        100.0 * SUM(f.price)
        / NULLIF(SUM(SUM(f.price)) OVER (), 0),
        2
    ) AS sales_share_percentage
FROM warehouse.fact_sales AS f
JOIN warehouse.dim_customer AS c
    ON f.customer_key = c.customer_key
WHERE f.is_valid_sale = TRUE
  AND f.is_synthetic = FALSE
  AND c.customer_key <> -1
  AND c.customer_state IS NOT NULL
GROUP BY c.customer_state
ORDER BY total_sales DESC, c.customer_state;


-- ============================================================
--  SECTION B: FULL-TIMELINE ANALYTICS  (Olist + Synthetic)
--  Continuous data from 2016 through 2026 for dashboards
--  and the AI assistant.
-- ============================================================


-- 6. Monthly Sales Performance (Full Timeline)

SELECT
    d.year,
    d.month,
    d.month_name,
    COUNT(DISTINCT f.order_id) AS total_orders,
    ROUND(SUM(f.price), 2) AS total_sales,
    ROUND(SUM(f.freight_value), 2) AS total_freight
FROM warehouse.fact_sales AS f
JOIN warehouse.dim_date AS d
    ON f.purchase_date_key = d.date_key
WHERE f.is_valid_sale = TRUE
GROUP BY d.year, d.month, d.month_name
ORDER BY d.year, d.month;


-- 7. Average Order Value and Monthly Sales Growth (Full Timeline)

WITH order_sales AS (
    SELECT
        order_id,
        MAX(purchase_date_key) AS purchase_date_key,
        SUM(price) AS order_value
    FROM warehouse.fact_sales
    WHERE is_valid_sale = TRUE
    GROUP BY order_id
),
monthly AS (
    SELECT
        d.year,
        d.month,
        d.month_name,
        COUNT(*) AS total_orders,
        SUM(o.order_value) AS total_sales,
        AVG(o.order_value) AS avg_order_value
    FROM order_sales AS o
    JOIN warehouse.dim_date AS d
        ON o.purchase_date_key = d.date_key
    GROUP BY d.year, d.month, d.month_name
)
SELECT
    year,
    month,
    month_name,
    total_orders,
    ROUND(total_sales, 2) AS total_sales,
    ROUND(avg_order_value, 2) AS avg_order_value,
    CASE
        WHEN total_orders >= 100
         AND LAG(total_orders) OVER (ORDER BY year, month) >= 100
        THEN ROUND(
            100.0 * (total_sales - LAG(total_sales) OVER (ORDER BY year, month))
            / NULLIF(LAG(total_sales) OVER (ORDER BY year, month), 0),
            2
        )
    END AS sales_growth_percentage
FROM monthly
ORDER BY year, month;


-- 8. Top 10 Product Categories by Sales Revenue (Full Timeline)

SELECT
    COALESCE(p.category_name_en, 'Unknown') AS category_name_en,
    COUNT(*) AS items_sold,
    COUNT(DISTINCT f.order_id) AS total_orders,
    ROUND(SUM(f.price), 2) AS total_sales,
    ROUND(
        100.0 * SUM(f.price)
        / NULLIF(SUM(SUM(f.price)) OVER (), 0),
        2
    ) AS sales_share_percentage
FROM warehouse.fact_sales AS f
JOIN warehouse.dim_product AS p
    ON f.product_key = p.product_key
WHERE f.is_valid_sale = TRUE
GROUP BY COALESCE(p.category_name_en, 'Unknown')
ORDER BY total_sales DESC, category_name_en
LIMIT 10;


-- 9. Top 10 Products by Sales Revenue (Full Timeline)

SELECT
    p.product_id,
    p.category_name_en,
    COUNT(*) AS items_sold,
    COUNT(DISTINCT f.order_id) AS total_orders,
    ROUND(SUM(f.price), 2) AS total_sales
FROM warehouse.fact_sales AS f
JOIN warehouse.dim_product AS p
    ON f.product_key = p.product_key
WHERE f.is_valid_sale = TRUE
GROUP BY p.product_id, p.category_name_en
ORDER BY total_sales DESC, p.product_id
LIMIT 10;


-- 10. Top 10 Sellers by Sales Revenue (Full Timeline)

SELECT
    s.seller_id,
    s.seller_city,
    s.seller_state,
    COUNT(*) AS items_sold,
    COUNT(DISTINCT f.order_id) AS total_orders,
    ROUND(SUM(f.price), 2) AS total_sales
FROM warehouse.fact_sales AS f
JOIN warehouse.dim_seller AS s
    ON f.seller_key = s.seller_key
WHERE f.is_valid_sale = TRUE
GROUP BY s.seller_id, s.seller_city, s.seller_state
ORDER BY total_sales DESC, s.seller_id
LIMIT 10;


-- 11. Delivery Performance (Full Timeline)

WITH order_delivery AS (
    SELECT
        order_id,
        MAX(delivery_days) AS delivery_days,
        MAX(delay_days) AS delay_days
    FROM warehouse.fact_sales
    WHERE is_delivered = TRUE
    GROUP BY order_id
)
SELECT
    COUNT(*) AS delivered_orders,
    ROUND(AVG(delivery_days), 2) AS avg_delivery_days,
    ROUND(AVG(delay_days), 2) AS avg_delay_days,
    ROUND(AVG(delay_days) FILTER (WHERE delay_days > 0), 2) AS avg_delay_days_late_only,
    COUNT(*) FILTER (WHERE delay_days > 0) AS late_orders,
    COUNT(*) FILTER (WHERE delay_days <= 0) AS on_time_or_early_orders,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE delay_days > 0)
        / NULLIF(COUNT(*) FILTER (WHERE delay_days IS NOT NULL), 0),
        2
    ) AS late_order_percentage
FROM order_delivery;


-- 12. Delivery Delay vs Customer Reviews (Full Timeline)

WITH order_delivery AS (
    SELECT
        order_id,
        MAX(delay_days) AS delay_days
    FROM warehouse.fact_sales
    WHERE is_delivered = TRUE
    GROUP BY order_id
),
order_reviews AS (
    SELECT
        order_id,
        AVG(review_score) AS avg_review_score
    FROM warehouse.fact_reviews
    WHERE review_score IS NOT NULL
    GROUP BY order_id
)
SELECT
    CASE
        WHEN d.delay_days > 0 THEN 'Late'
        WHEN d.delay_days <= 0 THEN 'On time or early'
        ELSE 'Unknown delay'
    END AS delivery_group,
    COUNT(*) AS reviewed_orders,
    ROUND(AVG(r.avg_review_score), 2) AS avg_review_score
FROM order_delivery AS d
JOIN order_reviews AS r
    ON d.order_id = r.order_id
GROUP BY
    CASE
        WHEN d.delay_days > 0 THEN 'Late'
        WHEN d.delay_days <= 0 THEN 'On time or early'
        ELSE 'Unknown delay'
    END
ORDER BY delivery_group;


-- 13. Customer Review Analysis (Full Timeline)

SELECT
    review_score,
    COUNT(*) AS total_reviews,
    ROUND(
        100.0 * COUNT(*)
        / NULLIF(SUM(COUNT(*)) OVER (), 0),
        2
    ) AS review_percentage,
    ROUND(
        CAST(SUM(review_score * COUNT(*)) OVER () AS numeric)
        / NULLIF(SUM(COUNT(*)) OVER (), 0),
        2
    ) AS overall_avg_score
FROM warehouse.fact_reviews
WHERE review_score IS NOT NULL
GROUP BY review_score
ORDER BY review_score;


-- 14. Payment Analysis (Full Timeline)

SELECT
    payment_type,
    COUNT(*) AS payment_records,
    COUNT(DISTINCT order_id) AS total_orders,
    ROUND(SUM(payment_value), 2) AS total_payment_value,
    ROUND(AVG(payment_value), 2) AS avg_payment_value
FROM warehouse.fact_payments
WHERE payment_type IS NOT NULL
GROUP BY payment_type
ORDER BY total_payment_value DESC;


-- 15. Sales by Customer State (Full Timeline)

SELECT
    c.customer_state,
    COUNT(DISTINCT f.order_id) AS total_orders,
    COUNT(DISTINCT c.customer_key) AS unique_customers,
    ROUND(SUM(f.price), 2) AS total_sales,
    ROUND(
        100.0 * SUM(f.price)
        / NULLIF(SUM(SUM(f.price)) OVER (), 0),
        2
    ) AS sales_share_percentage
FROM warehouse.fact_sales AS f
JOIN warehouse.dim_customer AS c
    ON f.customer_key = c.customer_key
WHERE f.is_valid_sale = TRUE
  AND c.customer_key <> -1
  AND c.customer_state IS NOT NULL
GROUP BY c.customer_state
ORDER BY total_sales DESC, c.customer_state;


-- 16. Customer Spending and Repeat Orders (Full Timeline)

WITH customer_order_sales AS (
    SELECT
        customer_key,
        order_id,
        SUM(price) AS order_sales
    FROM warehouse.fact_sales
    WHERE is_valid_sale = TRUE
      AND customer_key <> -1
    GROUP BY customer_key, order_id
),
customer_summary AS (
    SELECT
        customer_key,
        COUNT(*) AS total_orders,
        SUM(order_sales) AS total_spent
    FROM customer_order_sales
    GROUP BY customer_key
)
SELECT
    COUNT(*) AS customers_with_valid_sales,
    ROUND(AVG(total_spent), 2) AS avg_customer_spending,
    ROUND(AVG(total_orders), 2) AS avg_orders_per_customer,
    COUNT(*) FILTER (
        WHERE total_orders > 1
    ) AS repeat_customers,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE total_orders > 1)
        / NULLIF(COUNT(*), 0),
        2
    ) AS repeat_customer_percentage
FROM customer_summary;


-- 17. Order Status Breakdown by Month (Full Timeline)

WITH orders AS (
    SELECT
        order_id,
        MAX(purchase_date_key) AS purchase_date_key,
        MAX(order_status) AS order_status
    FROM warehouse.fact_sales
    GROUP BY order_id
)
SELECT
    d.year,
    d.month,
    d.month_name,
    COUNT(*) AS total_orders,
    COUNT(*) FILTER (WHERE o.order_status = 'canceled') AS canceled_orders,
    COUNT(*) FILTER (WHERE o.order_status = 'unavailable') AS unavailable_orders,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE o.order_status IN ('canceled', 'unavailable'))
        / NULLIF(COUNT(*), 0),
        2
    ) AS canceled_or_unavailable_percentage
FROM orders AS o
JOIN warehouse.dim_date AS d
    ON o.purchase_date_key = d.date_key
GROUP BY d.year, d.month, d.month_name
ORDER BY d.year, d.month;


-- ============================================================
--  SECTION C: INVENTORY ANALYTICS  (synthetic stock table)
--  fact_inventory is built from real monthly sales data by
--  warehouse/generate_inventory.py.
-- ============================================================


-- 18. Low-Stock Products at the Latest Snapshot

WITH latest AS (
    SELECT MAX(snapshot_date_key) AS snapshot_date_key
    FROM warehouse.fact_inventory
)
SELECT
    p.product_id,
    COALESCE(p.category_name_en, 'Unknown') AS category_name_en,
    i.closing_stock,
    i.reorder_level,
    i.units_sold AS units_sold_last_month
FROM warehouse.fact_inventory AS i
JOIN latest AS l
    ON i.snapshot_date_key = l.snapshot_date_key
JOIN warehouse.dim_product AS p
    ON i.product_key = p.product_key
WHERE i.is_low_stock = TRUE
ORDER BY i.units_sold DESC, p.product_id
LIMIT 10;


-- 19. Monthly Inventory Health

SELECT
    d.year,
    d.month,
    d.month_name,
    COUNT(*) AS products_tracked,
    COUNT(*) FILTER (WHERE i.is_low_stock) AS low_stock_products,
    ROUND(100.0 * COUNT(*) FILTER (WHERE i.is_low_stock) / NULLIF(COUNT(*), 0), 2) AS low_stock_percentage,
    COUNT(*) FILTER (WHERE i.closing_stock = 0) AS stock_out_products,
    SUM(i.units_sold) AS units_sold,
    SUM(i.units_received) AS units_received
FROM warehouse.fact_inventory AS i
JOIN warehouse.dim_date AS d
    ON i.snapshot_date_key = d.date_key
GROUP BY d.year, d.month, d.month_name
ORDER BY d.year, d.month;


-- 20. Stock Coverage by Category

WITH latest AS (
    SELECT MAX(snapshot_date_key) AS snapshot_date_key
    FROM warehouse.fact_inventory
)
SELECT
    COALESCE(p.category_name_en, 'Unknown') AS category_name_en,
    COUNT(*) AS products_tracked,
    SUM(i.closing_stock) AS total_closing_stock,
    SUM(i.units_sold) AS units_sold_last_month,
    ROUND(
        CAST(SUM(i.closing_stock) AS numeric) / NULLIF(SUM(i.units_sold), 0),
        2
    ) AS months_of_cover
FROM warehouse.fact_inventory AS i
JOIN latest AS l
    ON i.snapshot_date_key = l.snapshot_date_key
JOIN warehouse.dim_product AS p
    ON i.product_key = p.product_key
GROUP BY COALESCE(p.category_name_en, 'Unknown')
HAVING SUM(i.units_sold) > 0
ORDER BY months_of_cover ASC, category_name_en
LIMIT 10;


-- 21. Best-Selling Products vs Current Stock

WITH latest AS (
    SELECT MAX(snapshot_date_key) AS snapshot_date_key
    FROM warehouse.fact_inventory
),
product_totals AS (
    SELECT
        product_key,
        SUM(units_sold) AS total_units_sold,
        ROUND(AVG(units_sold), 2) AS avg_monthly_units
    FROM warehouse.fact_inventory
    GROUP BY product_key
)
SELECT
    p.product_id,
    COALESCE(p.category_name_en, 'Unknown') AS category_name_en,
    pt.total_units_sold,
    pt.avg_monthly_units,
    i.closing_stock,
    i.reorder_level,
    ROUND(
        CAST(i.closing_stock AS numeric) / NULLIF(pt.avg_monthly_units, 0),
        2
    ) AS months_of_cover
FROM product_totals AS pt
JOIN latest AS l ON TRUE
JOIN warehouse.fact_inventory AS i
    ON i.product_key = pt.product_key
   AND i.snapshot_date_key = l.snapshot_date_key
JOIN warehouse.dim_product AS p
    ON pt.product_key = p.product_key
ORDER BY pt.total_units_sold DESC, p.product_id
LIMIT 10;
