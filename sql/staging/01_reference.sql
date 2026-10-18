-- ============================================================
-- Reference tables: category translation + geolocation
-- ============================================================

-- 71 official translations + 2 categories missing from the source file
DROP TABLE IF EXISTS staging.category_translation CASCADE;
CREATE TABLE staging.category_translation AS
SELECT product_category_name, product_category_name_english AS category_name_en
FROM raw.product_category_translation
UNION ALL
SELECT * FROM (VALUES
    ('pc_gamer', 'pc_gamer'),
    ('portateis_cozinha_e_preparadores_de_alimentos', 'portable_kitchen_food_preparers')
) AS manual(product_category_name, category_name_en);
ALTER TABLE staging.category_translation ADD PRIMARY KEY (product_category_name);

-- One row per zip prefix: points outside Brazil removed, coordinates averaged,
-- most frequent city/state kept (names normalised: lowercase, no accents).
DROP TABLE IF EXISTS staging.geolocation CASCADE;
CREATE TABLE staging.geolocation AS
SELECT
    zip_code_prefix,
    avg(lat)::numeric(10,6)  AS lat,
    avg(lng)::numeric(10,6)  AS lng,
    mode() WITHIN GROUP (ORDER BY city)  AS city,
    mode() WITHIN GROUP (ORDER BY state) AS state,
    count(*)                 AS source_points
FROM (
    SELECT geolocation_zip_code_prefix              AS zip_code_prefix,
           geolocation_lat::numeric                 AS lat,
           geolocation_lng::numeric                 AS lng,
           lower(unaccent(trim(geolocation_city)))  AS city,
           upper(trim(geolocation_state))           AS state
    FROM raw.geolocation
    WHERE geolocation_lat::numeric BETWEEN -34 AND 6
      AND geolocation_lng::numeric BETWEEN -74 AND -34
) t
GROUP BY zip_code_prefix;
ALTER TABLE staging.geolocation ADD PRIMARY KEY (zip_code_prefix);