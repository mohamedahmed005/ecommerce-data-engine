-- ============================================================
-- Olist E-Commerce Data Warehouse
-- Gold Layer - Analytical Queries
-- Database: PostgreSQL
-- ============================================================


-- 1. Monthly Sales Performance
-- Monthly sales revenue, freight costs, and order count.

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


-- 2. Top 10 Products by Sales Revenue

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


-- 3. Top 10 Sellers by Sales Revenue

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


-- 4. Delivery Performance
-- Aggregate at order level to avoid counting multi-item orders repeatedly.
-- avg_delay_days is the net delay (early deliveries count as negative);
-- avg_delay_days_late_only averages only the late orders.

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
    COUNT(*) FILTER (
        WHERE delay_days > 0
    ) AS late_orders,
    COUNT(*) FILTER (
        WHERE delay_days <= 0
    ) AS on_time_or_early_orders,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE delay_days > 0)
        / NULLIF(COUNT(*) FILTER (WHERE delay_days IS NOT NULL), 0),
        2
    ) AS late_order_percentage
FROM order_delivery;


-- 5. Customer Review Analysis
-- Review score distribution, percentages, and overall average.
-- The overall average is weighted by the number of reviews per score.

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


-- 6. Payment Analysis
-- Compare payment methods by amount and frequency.

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


-- 7. Delivery Delay vs. Customer Reviews
-- Compare average review scores for late and on-time deliveries.

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
