-- ============================================================
-- Warehouse (Gold) layer - LOAD FACTS  (staging -> warehouse)
-- Run AFTER 03_load_dimensions.sql (which also empties the facts).
-- Rules:
--   * a key that cannot be resolved points to the Unknown member (-1), the row is kept
--   * a date that does not exist (order never delivered...) stays NULL
--   * suspicious rows are flagged, never deleted
--   * is_synthetic = TRUE for rows of synthetic demo orders (raw.orders._source_file
--     = 'synthetic_demo'); the flag is set on all three facts through order_id
-- ============================================================

-- ---------- fact_sales : one row per order item ----------
INSERT INTO warehouse.fact_sales
       (order_id, order_item_id, customer_key, product_key, seller_key,
        purchase_date_key, approved_date_key, carrier_date_key,
        delivered_date_key, estimated_date_key,
        order_status, price, freight_value, delivery_days, delay_days,
        is_valid_item, is_valid_sale, is_delivered, is_synthetic)
SELECT f.order_id, f.order_item_id, f.customer_key, f.product_key, f.seller_key,
       f.purchase_date_key, f.approved_date_key, f.carrier_date_key,
       f.delivered_date_key, f.estimated_date_key,
       f.order_status, f.price, f.freight_value, f.delivery_days, f.delay_days,
       f.is_valid_item,
       (f.is_valid_item AND f.order_status NOT IN ('canceled', 'unavailable')) AS is_valid_sale,
       (f.order_status = 'delivered' AND f.delivered_date_key IS NOT NULL)     AS is_delivered,
       f.is_synthetic
FROM (
    SELECT oi.order_id,
           oi.order_item_id,
           COALESCE(dc.customer_key, -1) AS customer_key,
           COALESCE(dp.product_key,  -1) AS product_key,
           COALESCE(ds.seller_key,   -1) AS seller_key,
           to_char(o.purchase_ts,           'YYYYMMDD')::int AS purchase_date_key,
           to_char(o.approved_ts,           'YYYYMMDD')::int AS approved_date_key,
           to_char(o.carrier_ts,            'YYYYMMDD')::int AS carrier_date_key,
           to_char(o.delivered_ts,          'YYYYMMDD')::int AS delivered_date_key,
           to_char(o.estimated_delivery_ts, 'YYYYMMDD')::int AS estimated_date_key,
           COALESCE(o.order_status, 'unknown') AS order_status,
           oi.price,
           oi.freight_value,
           -- days from purchase to delivery (NULL when not delivered)
           (o.delivered_ts::date - o.purchase_ts::date)            AS delivery_days,
           -- delivered minus estimated: positive = late, negative = early
           (o.delivered_ts::date - o.estimated_delivery_ts::date)  AS delay_days,
           COALESCE(oi.price > 0 AND oi.freight_value >= 0
                    AND dc.customer_key IS NOT NULL
                    AND dp.product_key  IS NOT NULL
                    AND ds.seller_key   IS NOT NULL, false)        AS is_valid_item,
           (syn.order_id IS NOT NULL)                              AS is_synthetic
    FROM staging.order_items oi
    LEFT JOIN staging.orders    o  ON o.order_id    = oi.order_id
    LEFT JOIN staging.customers c  ON c.customer_id = o.customer_id
    LEFT JOIN warehouse.dim_customer dc ON dc.customer_unique_id = c.customer_unique_id
    LEFT JOIN warehouse.dim_product  dp ON dp.product_id         = oi.product_id
    LEFT JOIN warehouse.dim_seller   ds ON ds.seller_id          = oi.seller_id
    LEFT JOIN (SELECT DISTINCT order_id FROM raw.orders
               WHERE _source_file = 'synthetic_demo') syn ON syn.order_id = oi.order_id
) f;

-- ---------- fact_payments : one row per payment of an order ----------
INSERT INTO warehouse.fact_payments
       (order_id, payment_sequential, customer_key, payment_date_key,
        payment_type, payment_installments, payment_value, is_synthetic)
SELECT p.order_id,
       p.payment_sequential,
       COALESCE(dc.customer_key, -1),
       to_char(o.purchase_ts, 'YYYYMMDD')::int,
       p.payment_type,
       p.installments,
       p.payment_value,
       (syn.order_id IS NOT NULL)
FROM staging.order_payments p
LEFT JOIN staging.orders    o  ON o.order_id    = p.order_id
LEFT JOIN staging.customers c  ON c.customer_id = o.customer_id
LEFT JOIN warehouse.dim_customer dc ON dc.customer_unique_id = c.customer_unique_id
LEFT JOIN (SELECT DISTINCT order_id FROM raw.orders
           WHERE _source_file = 'synthetic_demo') syn ON syn.order_id = p.order_id;

-- ---------- fact_reviews : one row per review ----------
INSERT INTO warehouse.fact_reviews
       (review_id, order_id, customer_key, review_date_key, answer_date_key,
        review_score, has_comment, is_synthetic)
SELECT r.review_id,
       r.order_id,
       COALESCE(dc.customer_key, -1),
       to_char(r.created_ts,  'YYYYMMDD')::int,
       to_char(r.answered_ts, 'YYYYMMDD')::int,
       r.review_score,
       (r.comment_message IS NOT NULL) AS has_comment,
       (syn.order_id IS NOT NULL)      AS is_synthetic
FROM staging.order_reviews r
LEFT JOIN staging.orders    o  ON o.order_id    = r.order_id
LEFT JOIN staging.customers c  ON c.customer_id = o.customer_id
LEFT JOIN warehouse.dim_customer dc ON dc.customer_unique_id = c.customer_unique_id
LEFT JOIN (SELECT DISTINCT order_id FROM raw.orders
           WHERE _source_file = 'synthetic_demo') syn ON syn.order_id = r.order_id;

ANALYZE;
