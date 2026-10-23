-- ============================================================
-- Warehouse (Gold) layer - LOAD DIMENSIONS  (staging -> warehouse)
-- Re-runnable: empties every warehouse table, then reloads.
-- Order matters: dim_geography first (customers/sellers point to it).
-- ============================================================

TRUNCATE warehouse.fact_reviews, warehouse.fact_payments, warehouse.fact_sales,
         warehouse.dim_seller, warehouse.dim_customer, warehouse.dim_product,
         warehouse.dim_geography, warehouse.dim_date
RESTART IDENTITY CASCADE;

-- ---------- Unknown members (key = -1) ----------
INSERT INTO warehouse.dim_geography (geography_key, zip_code_prefix, city, state)
OVERRIDING SYSTEM VALUE VALUES (-1, 'unknown', 'unknown', NULL);

INSERT INTO warehouse.dim_customer (customer_key, customer_unique_id, geography_key,
                                    customer_zip_code_prefix, customer_city, customer_state)
OVERRIDING SYSTEM VALUE VALUES (-1, 'unknown', -1, 'unknown', 'unknown', NULL);

INSERT INTO warehouse.dim_product (product_key, product_id, category_name_pt, category_name_en)
OVERRIDING SYSTEM VALUE VALUES (-1, 'unknown', 'unknown', 'unknown');

INSERT INTO warehouse.dim_seller (seller_key, seller_id, geography_key,
                                  seller_zip_code_prefix, seller_city, seller_state)
OVERRIDING SYSTEM VALUE VALUES (-1, 'unknown', -1, 'unknown', 'unknown', NULL);

-- ---------- dim_date : every day from the first to the last date in the data ----------
INSERT INTO warehouse.dim_date
SELECT to_char(g, 'YYYYMMDD')::int,
       g::date,
       extract(year    FROM g)::int,
       extract(quarter FROM g)::int,
       extract(month   FROM g)::int,
       trim(to_char(g, 'Month')),
       extract(day     FROM g)::int,
       extract(isodow  FROM g)::int,
       extract(week    FROM g)::int,
       extract(isodow  FROM g) IN (6, 7)
FROM (
    SELECT min(d)::date AS lo, max(d)::date AS hi
    FROM (
        SELECT purchase_ts AS d FROM staging.orders
        UNION ALL SELECT approved_ts           FROM staging.orders
        UNION ALL SELECT carrier_ts            FROM staging.orders
        UNION ALL SELECT delivered_ts          FROM staging.orders
        UNION ALL SELECT estimated_delivery_ts FROM staging.orders
        UNION ALL SELECT created_ts            FROM staging.order_reviews
        UNION ALL SELECT answered_ts           FROM staging.order_reviews
    ) x
) b,
generate_series(b.lo, b.hi, interval '1 day') AS g;

-- ---------- dim_geography : every zip prefix ----------
-- staging.geolocation + zips that customers/sellers use but geolocation lacks
-- (those get NULL coordinates; city/state come from the most frequent value).
INSERT INTO warehouse.dim_geography (zip_code_prefix, city, state, latitude, longitude)
SELECT zip_code_prefix, city, state, latitude, longitude
FROM (
    SELECT zip_code_prefix, city, state, lat AS latitude, lng AS longitude
    FROM staging.geolocation
    UNION ALL
    SELECT z.zip_code_prefix,
           mode() WITHIN GROUP (ORDER BY z.city),
           mode() WITHIN GROUP (ORDER BY z.state),
           NULL::numeric, NULL::numeric
    FROM (
        SELECT zip_code_prefix, city, state FROM staging.customers WHERE NOT zip_in_geolocation
        UNION ALL
        SELECT zip_code_prefix, city, state FROM staging.sellers   WHERE NOT zip_in_geolocation
    ) z
    GROUP BY z.zip_code_prefix
) all_zips
ORDER BY zip_code_prefix;

-- ---------- dim_customer : one row per customer_unique_id ----------
-- Olist's customer_id changes per order. A real customer may appear with several
-- addresses, so we keep the address from their MOST RECENT order.
INSERT INTO warehouse.dim_customer
       (customer_unique_id, geography_key, customer_zip_code_prefix, customer_city, customer_state)
SELECT c.customer_unique_id,
       COALESCE(g.geography_key, -1),
       c.zip_code_prefix, c.city, c.state
FROM (
    SELECT DISTINCT ON (cu.customer_unique_id)
           cu.customer_unique_id, cu.zip_code_prefix, cu.city, cu.state
    FROM staging.customers cu
    LEFT JOIN staging.orders o ON o.customer_id = cu.customer_id
    ORDER BY cu.customer_unique_id, o.purchase_ts DESC NULLS LAST, cu.customer_id
) c
LEFT JOIN warehouse.dim_geography g ON g.zip_code_prefix = c.zip_code_prefix
ORDER BY c.customer_unique_id;

-- ---------- dim_seller ----------
INSERT INTO warehouse.dim_seller
       (seller_id, geography_key, seller_zip_code_prefix, seller_city, seller_state)
SELECT s.seller_id,
       COALESCE(g.geography_key, -1),
       s.zip_code_prefix, s.city, s.state
FROM staging.sellers s
LEFT JOIN warehouse.dim_geography g ON g.zip_code_prefix = s.zip_code_prefix
ORDER BY s.seller_id;

-- ---------- dim_product ----------
INSERT INTO warehouse.dim_product
       (product_id, category_name_pt, category_name_en, name_length, description_length,
        photos_qty, weight_g, length_cm, height_cm, width_cm)
SELECT product_id, category_name, category_name_en, name_length, description_length,
       photos_qty, weight_g, length_cm, height_cm, width_cm
FROM staging.products
ORDER BY product_id;
