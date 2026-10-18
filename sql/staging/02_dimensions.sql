-- ============================================================
-- Dimension-like tables: customers, sellers, products
-- ============================================================

-- NOTE: customer_id is generated per ORDER. The real customer is customer_unique_id.
DROP TABLE IF EXISTS staging.customers CASCADE;
CREATE TABLE staging.customers AS
SELECT
    c.customer_id,
    c.customer_unique_id,
    c.customer_zip_code_prefix                   AS zip_code_prefix,
    lower(unaccent(trim(c.customer_city)))       AS city,
    upper(trim(c.customer_state))                AS state,
    EXISTS (SELECT 1 FROM staging.geolocation g
            WHERE g.zip_code_prefix = c.customer_zip_code_prefix) AS zip_in_geolocation
FROM raw.customers c;
ALTER TABLE staging.customers ADD PRIMARY KEY (customer_id);
CREATE INDEX ON staging.customers (customer_unique_id);

DROP TABLE IF EXISTS staging.sellers CASCADE;
CREATE TABLE staging.sellers AS
SELECT
    s.seller_id,
    s.seller_zip_code_prefix                     AS zip_code_prefix,
    lower(unaccent(trim(s.seller_city)))         AS city,
    upper(trim(s.seller_state))                  AS state,
    -- digits, emails, slashes... in a city name = dirty value (kept, but flagged)
    (lower(trim(s.seller_city)) ~ '[0-9@/,]')    AS flag_city_suspect,
    EXISTS (SELECT 1 FROM staging.geolocation g
            WHERE g.zip_code_prefix = s.seller_zip_code_prefix) AS zip_in_geolocation
FROM raw.sellers s;
ALTER TABLE staging.sellers ADD PRIMARY KEY (seller_id);

DROP TABLE IF EXISTS staging.products CASCADE;
CREATE TABLE staging.products AS
SELECT
    p.product_id,
    COALESCE(p.product_category_name, 'unknown')            AS category_name,
    COALESCE(t.category_name_en, 'unknown')                 AS category_name_en,
    (p.product_category_name IS NULL)                       AS flag_missing_category,
    p.product_name_lenght::numeric::int                     AS name_length,         -- source typo fixed
    p.product_description_lenght::numeric::int              AS description_length,  -- source typo fixed
    p.product_photos_qty::numeric::int                      AS photos_qty,
    NULLIF(p.product_weight_g::numeric, 0)                  AS weight_g,            -- 0 g is not valid
    p.product_length_cm::numeric                            AS length_cm,
    p.product_height_cm::numeric                            AS height_cm,
    p.product_width_cm::numeric                             AS width_cm,
    (p.product_weight_g::numeric = 0)                       AS flag_zero_weight
FROM raw.products p
LEFT JOIN staging.category_translation t USING (product_category_name);
ALTER TABLE staging.products ADD PRIMARY KEY (product_id);