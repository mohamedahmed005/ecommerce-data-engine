-- ============================================================
-- Warehouse (Gold) layer - FACTS
-- Quality flags are separate columns. Suspicious rows are FLAGGED, never deleted.
-- order_id is a degenerate dimension: fact_payments / fact_reviews link to
-- fact_sales through order_id only (no enforced FK; an order has many items).
-- is_synthetic = TRUE marks rows that come from synthetic demo orders
-- (raw rows with _source_file = 'synthetic_demo'); original Olist rows are FALSE.
-- Run AFTER 01_dimensions.sql.
-- ============================================================

-- ---------- fact_sales : grain = one order item ----------
CREATE TABLE warehouse.fact_sales (
    order_id            varchar(50) NOT NULL,
    order_item_id       integer     NOT NULL,
    customer_key        integer     NOT NULL REFERENCES warehouse.dim_customer (customer_key),
    product_key         integer     NOT NULL REFERENCES warehouse.dim_product  (product_key),
    seller_key          integer     NOT NULL REFERENCES warehouse.dim_seller   (seller_key),
    -- role-playing date dimension (NULL when the event never happened)
    purchase_date_key   integer REFERENCES warehouse.dim_date (date_key),
    approved_date_key   integer REFERENCES warehouse.dim_date (date_key),
    carrier_date_key    integer REFERENCES warehouse.dim_date (date_key),
    delivered_date_key  integer REFERENCES warehouse.dim_date (date_key),
    estimated_date_key  integer REFERENCES warehouse.dim_date (date_key),
    order_status        varchar(20) NOT NULL,
    price               numeric(10,2),
    freight_value       numeric(10,2),
    delivery_days       integer,     -- NULL when no delivered date
    delay_days          integer,     -- delivered - estimated; NULL when no delivered date
    -- quality flags
    is_valid_item       boolean NOT NULL,
    is_valid_sale       boolean NOT NULL,
    is_delivered        boolean NOT NULL,
    is_synthetic        boolean NOT NULL DEFAULT false,
    PRIMARY KEY (order_id, order_item_id)
);
CREATE INDEX ON warehouse.fact_sales (order_id);
CREATE INDEX ON warehouse.fact_sales (customer_key);
CREATE INDEX ON warehouse.fact_sales (product_key);
CREATE INDEX ON warehouse.fact_sales (seller_key);
CREATE INDEX ON warehouse.fact_sales (purchase_date_key);

-- ---------- fact_payments : grain = one payment row of an order ----------
CREATE TABLE warehouse.fact_payments (
    order_id             varchar(50) NOT NULL,
    payment_sequential   integer     NOT NULL,
    customer_key         integer     NOT NULL REFERENCES warehouse.dim_customer (customer_key),
    payment_date_key     integer REFERENCES warehouse.dim_date (date_key),  -- order purchase date
    payment_type         varchar(30),
    payment_installments integer,
    payment_value        numeric(10,2),
    is_synthetic         boolean NOT NULL DEFAULT false,
    PRIMARY KEY (order_id, payment_sequential)
);
CREATE INDEX ON warehouse.fact_payments (customer_key);
CREATE INDEX ON warehouse.fact_payments (payment_date_key);

-- ---------- fact_reviews : grain = one review ----------
CREATE TABLE warehouse.fact_reviews (
    review_id        varchar(50) NOT NULL,
    order_id         varchar(50) NOT NULL,
    customer_key     integer     NOT NULL REFERENCES warehouse.dim_customer (customer_key),
    review_date_key  integer REFERENCES warehouse.dim_date (date_key),
    answer_date_key  integer REFERENCES warehouse.dim_date (date_key),
    review_score     integer CHECK (review_score BETWEEN 1 AND 5),
    has_comment      boolean NOT NULL,
    is_synthetic     boolean NOT NULL DEFAULT false,
    PRIMARY KEY (review_id, order_id)
);
CREATE INDEX ON warehouse.fact_reviews (order_id);
CREATE INDEX ON warehouse.fact_reviews (customer_key);
