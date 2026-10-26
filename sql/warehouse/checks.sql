-- 1. Total sales (valid sales only)
SELECT ROUND(SUM(price), 2) AS total_sales_valid
FROM warehouse.fact_sales
WHERE is_valid_sale = TRUE;

-- 2. Total sales (all rows)
SELECT ROUND(SUM(price), 2) AS total_sales_all
FROM warehouse.fact_sales;

-- 3. Rows excluded by is_valid_sale
SELECT
    COUNT(*) FILTER (WHERE is_valid_sale = TRUE)  AS valid_rows,
    COUNT(*) FILTER (WHERE is_valid_sale = FALSE) AS invalid_rows,
    COUNT(*) FILTER (WHERE is_valid_sale IS NULL) AS null_rows
FROM warehouse.fact_sales;
