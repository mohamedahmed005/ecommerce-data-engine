-- ============================================================
-- Transaction tables: orders, order_items, order_payments, order_reviews
-- Bad rows are FLAGGED, not deleted. Decisions are made downstream.
-- ============================================================

DROP TABLE IF EXISTS staging.orders CASCADE;
CREATE TABLE staging.orders AS
WITH items AS (
    SELECT order_id, count(*) AS item_count,
           sum(price::numeric + freight_value::numeric) AS items_total
    FROM raw.order_items GROUP BY order_id
), pays AS (
    SELECT order_id, count(*) AS payment_count,
           sum(payment_value::numeric) AS payments_total
    FROM raw.order_payments GROUP BY order_id
), base AS (
    SELECT order_id, customer_id, order_status,
           order_purchase_timestamp::timestamp          AS purchase_ts,
           order_approved_at::timestamp                 AS approved_ts,
           order_delivered_carrier_date::timestamp      AS carrier_ts,
           order_delivered_customer_date::timestamp     AS delivered_ts,
           order_estimated_delivery_date::timestamp     AS estimated_delivery_ts
    FROM raw.orders
)
SELECT
    b.*,
    COALESCE(i.item_count, 0)    AS item_count,
    i.items_total,
    COALESCE(p.payment_count, 0) AS payment_count,
    p.payments_total,
    (i.order_id IS NOT NULL)     AS has_items,
    (p.order_id IS NOT NULL)     AS has_payment,
    COALESCE(b.order_status = 'delivered' AND b.delivered_ts IS NULL, false)      AS flag_delivered_no_date,
    COALESCE(b.order_status <> 'delivered' AND b.delivered_ts IS NOT NULL, false) AS flag_delivery_date_not_delivered,
    COALESCE(b.carrier_ts < b.purchase_ts, false)                                 AS flag_carrier_before_purchase,
    COALESCE(b.delivered_ts < b.carrier_ts, false)                                AS flag_delivered_before_carrier,
    COALESCE(abs(i.items_total - p.payments_total) > 1.00, false)                 AS flag_payment_mismatch
FROM base b
LEFT JOIN items i USING (order_id)
LEFT JOIN pays  p USING (order_id);

ALTER TABLE staging.orders ADD PRIMARY KEY (order_id);
ALTER TABLE staging.orders ADD COLUMN has_date_anomaly boolean GENERATED ALWAYS AS (
    flag_delivered_no_date OR flag_delivery_date_not_delivered
    OR flag_carrier_before_purchase OR flag_delivered_before_carrier) STORED;
-- Business rule (confirm with the team): an order counts as a sale only if it has items
-- and was not canceled / unavailable.
ALTER TABLE staging.orders ADD COLUMN is_valid_sale boolean GENERATED ALWAYS AS (
    has_items AND order_status NOT IN ('canceled', 'unavailable')) STORED;
CREATE INDEX ON staging.orders (customer_id);

DROP TABLE IF EXISTS staging.order_items CASCADE;
CREATE TABLE staging.order_items AS
SELECT
    order_id,
    order_item_id::int                    AS order_item_id,
    product_id,
    seller_id,
    shipping_limit_date::timestamp        AS shipping_limit_ts,
    price::numeric(10,2)                  AS price,
    freight_value::numeric(10,2)          AS freight_value,
    -- the original Olist data ends in 2018; limits in 2019+ are outliers
    -- but synthetic demo orders (2018-2026) are expected to have later dates
    (shipping_limit_date::timestamp >= '2019-01-01'
     AND COALESCE(_source_file, '') <> 'synthetic_demo') AS flag_shipping_limit_outlier
FROM raw.order_items;
ALTER TABLE staging.order_items ADD PRIMARY KEY (order_id, order_item_id);
CREATE INDEX ON staging.order_items (product_id);
CREATE INDEX ON staging.order_items (seller_id);

DROP TABLE IF EXISTS staging.order_payments CASCADE;
CREATE TABLE staging.order_payments AS
SELECT
    order_id,
    payment_sequential::int                         AS payment_sequential,
    payment_type,
    GREATEST(payment_installments::int, 1)          AS installments,   -- 0 -> 1
    (payment_installments::int = 0)                 AS flag_installments_fixed,
    payment_value::numeric(10,2)                    AS payment_value,
    (payment_type = 'not_defined')                  AS flag_type_not_defined
FROM raw.order_payments;
ALTER TABLE staging.order_payments ADD PRIMARY KEY (order_id, payment_sequential);

-- review_id repeats across orders in the source, so the key is (review_id, order_id).
-- Exact duplicates on that pair are collapsed (latest answer wins).
DROP TABLE IF EXISTS staging.order_reviews CASCADE;
CREATE TABLE staging.order_reviews AS
WITH dedup AS (
    SELECT *, row_number() OVER (
        PARTITION BY review_id, order_id ORDER BY review_answer_timestamp DESC) AS rn
    FROM raw.order_reviews
), typed AS (
    SELECT review_id, order_id,
           review_score::smallint                         AS review_score,
           NULLIF(trim(review_comment_title), '')         AS comment_title,
           NULLIF(trim(review_comment_message), '')       AS comment_message,
           review_creation_date::timestamp                AS created_ts,
           review_answer_timestamp::timestamp             AS answered_ts
    FROM dedup WHERE rn = 1
)
SELECT t.*,
       (row_number() OVER (PARTITION BY t.order_id ORDER BY t.answered_ts DESC, t.review_id) = 1) AS is_latest_for_order,
       COALESCE(t.created_ts < o.purchase_ts, false) AS flag_review_before_purchase
FROM typed t
LEFT JOIN staging.orders o USING (order_id);
ALTER TABLE staging.order_reviews ADD PRIMARY KEY (review_id, order_id);