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


-- 8. Top 10 Product Categories by Sales Revenue
-- Share is calculated over all categories before the top 10 are selected.

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


-- 9. Average Order Value and Monthly Sales Growth
-- Order value = sum of item prices per order. Growth is compared with the
-- previous month that has data (the dataset has no orders in November 2016).
-- Growth is shown only when both months have at least 100 orders, because the
-- first and last months of the dataset are tiny and give meaningless percentages.

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


-- 10. Sales by Customer State
-- The state is the address of the customer's most recent order (see dim_customer).

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


-- 11. Customer Spending and Repeat Orders
-- dim_customer has one row per real customer (customer_unique_id),
-- so a customer with several orders is counted once.

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


-- 12. Delivery Performance by Customer State
-- Order level. States with fewer than 100 delivered orders are excluded
-- because their percentages are not reliable.

WITH order_delivery AS (
    SELECT
        order_id,
        MAX(customer_key) AS customer_key,
        MAX(delivery_days) AS delivery_days,
        MAX(delay_days) AS delay_days
    FROM warehouse.fact_sales
    WHERE is_delivered = TRUE
    GROUP BY order_id
)
SELECT
    c.customer_state,
    COUNT(*) AS delivered_orders,
    ROUND(AVG(d.delivery_days), 2) AS avg_delivery_days,
    COUNT(*) FILTER (WHERE d.delay_days > 0) AS late_orders,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE d.delay_days > 0)
        / NULLIF(COUNT(*) FILTER (WHERE d.delay_days IS NOT NULL), 0),
        2
    ) AS late_order_percentage
FROM order_delivery AS d
JOIN warehouse.dim_customer AS c
    ON d.customer_key = c.customer_key
WHERE c.customer_key <> -1
  AND c.customer_state IS NOT NULL
GROUP BY c.customer_state
HAVING COUNT(*) >= 100
ORDER BY late_order_percentage DESC, c.customer_state;


-- 13. Top 10 Sellers by Customer Satisfaction
-- Only sellers with at least 50 delivered orders. Review scores and delays
-- are calculated per order first, so multi-item orders are counted once per seller.

WITH seller_orders AS (
    SELECT
        seller_key,
        order_id,
        SUM(price) AS order_sales,
        MAX(delay_days) AS delay_days
    FROM warehouse.fact_sales
    WHERE is_valid_sale = TRUE
      AND is_delivered = TRUE
      AND seller_key <> -1
    GROUP BY seller_key, order_id
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
    s.seller_id,
    s.seller_state,
    COUNT(*) AS delivered_orders,
    ROUND(SUM(so.order_sales), 2) AS total_sales,
    ROUND(AVG(r.avg_review_score), 2) AS avg_review_score,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE so.delay_days > 0)
        / NULLIF(COUNT(*) FILTER (WHERE so.delay_days IS NOT NULL), 0),
        2
    ) AS late_order_percentage
FROM seller_orders AS so
JOIN warehouse.dim_seller AS s
    ON so.seller_key = s.seller_key
LEFT JOIN order_reviews AS r
    ON so.order_id = r.order_id
GROUP BY s.seller_id, s.seller_state
HAVING COUNT(*) >= 50
ORDER BY avg_review_score DESC NULLS LAST, delivered_orders DESC, s.seller_id
LIMIT 10;


-- 14. Order Status Breakdown by Month
-- Counts orders that have at least one item in fact_sales. Orders without items
-- are not in fact_sales, and almost all 'unavailable' orders have no items, so
-- this view understates unavailable orders (and canceled ones to a lesser extent).

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


-- 15. Credit Card Installments
-- Installments are a credit-card feature, so only credit-card payments are grouped.

WITH installment_groups AS (
    SELECT
        payment_value,
        CASE
            WHEN payment_installments <= 1 THEN 1
            WHEN payment_installments <= 3 THEN 2
            WHEN payment_installments <= 6 THEN 3
            WHEN payment_installments <= 10 THEN 4
            ELSE 5
        END AS group_order,
        CASE
            WHEN payment_installments <= 1 THEN '1 (single payment)'
            WHEN payment_installments <= 3 THEN '2-3 installments'
            WHEN payment_installments <= 6 THEN '4-6 installments'
            WHEN payment_installments <= 10 THEN '7-10 installments'
            ELSE '11+ installments'
        END AS installment_group
    FROM warehouse.fact_payments
    WHERE payment_type = 'credit_card'
      AND payment_installments IS NOT NULL
)
SELECT
    installment_group,
    COUNT(*) AS payment_records,
    ROUND(SUM(payment_value), 2) AS total_payment_value,
    ROUND(AVG(payment_value), 2) AS avg_payment_value,
    ROUND(
        100.0 * COUNT(*)
        / NULLIF(SUM(COUNT(*)) OVER (), 0),
        2
    ) AS record_percentage
FROM installment_groups
GROUP BY group_order, installment_group
ORDER BY group_order;


-- 16. Low-Stock Products at the Latest Snapshot
-- Uses the SYNTHETIC inventory table. Products at or below their reorder level,
-- ranked by sales in the latest month.

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


-- 17. Monthly Inventory Health
-- Uses the SYNTHETIC inventory table. Share of tracked products that are low on
-- stock or out of stock at the end of each month.

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


-- 18. Stock Coverage by Category
-- Uses the SYNTHETIC inventory table. Months of cover = closing stock divided by
-- the units sold in the latest month. The 10 categories with the lowest cover.

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


-- 19. Best-Selling Products vs. Current Stock
-- Uses the SYNTHETIC inventory table. Top 10 products by total units sold, with
-- their latest stock and months of cover (closing stock / average monthly sales).

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
