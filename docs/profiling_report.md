# Raw Data Profiling Report
_Generated: 2026-10-23 19:02 UTC_

## 1. Data quality checks

| Check | Table | Category | Severity | Failed | Total | Fail % | Status |
|---|---|---|---|---:|---:|---:|---|
| delivered_without_delivery_date | orders | completeness | high | 8 | 96478 | 0.008 | FAIL |
| carrier_before_purchase | orders | consistency | high | 166 | 97658 | 0.17 | FAIL |
| pk_order_reviews_review_id | order_reviews | uniqueness | medium | 814 | 99224 | 0.82 | FAIL |
| fk_products_category_translation | products | integrity | medium | 13 | 32341 | 0.04 | FAIL |
| orders_without_items | orders | integrity | medium | 775 | 99441 | 0.779 | FAIL |
| orders_without_payments | orders | integrity | medium | 1 | 99441 | 0.001 | FAIL |
| products_null_category | products | completeness | medium | 610 | 32951 | 1.851 | FAIL |
| products_null_dimensions | products | completeness | medium | 2 | 32951 | 0.006 | FAIL |
| payments_zero_installments | order_payments | validity | medium | 2 | 103886 | 0.002 | FAIL |
| products_zero_weight | products | validity | medium | 4 | 32951 | 0.012 | FAIL |
| geolocation_outside_brazil | geolocation | validity | medium | 42 | 1000163 | 0.004 | FAIL |
| delivered_before_carrier | orders | consistency | medium | 23 | 96475 | 0.024 | FAIL |
| non_delivered_with_delivery_date | orders | consistency | medium | 6 | 96476 | 0.006 | FAIL |
| review_before_purchase | order_reviews | consistency | medium | 74 | 99224 | 0.075 | FAIL |
| payment_vs_items_mismatch | orders | consistency | medium | 249 | 98665 | 0.252 | FAIL |
| dup_geolocation_rows | geolocation | uniqueness | low | 261831 | 1000163 | 26.179 | FAIL |
| fk_customers_zip_geolocation | customers | integrity | low | 278 | 99441 | 0.28 | FAIL |
| reviews_without_comment | order_reviews | completeness | low | 58247 | 99224 | 58.703 | FAIL |
| payments_not_defined_type | order_payments | validity | low | 3 | 103886 | 0.003 | FAIL |
| pk_customers_customer_id | customers | uniqueness | high | 0 | 99441 | 0.0 | PASS |
| pk_orders_order_id | orders | uniqueness | high | 0 | 99441 | 0.0 | PASS |
| pk_products_product_id | products | uniqueness | high | 0 | 32951 | 0.0 | PASS |
| pk_sellers_seller_id | sellers | uniqueness | high | 0 | 3095 | 0.0 | PASS |
| pk_order_items | order_items | uniqueness | high | 0 | 112650 | 0.0 | PASS |
| pk_order_payments | order_payments | uniqueness | high | 0 | 103886 | 0.0 | PASS |
| fk_orders_customer | orders | integrity | high | 0 | 99441 | 0.0 | PASS |
| fk_items_order | order_items | integrity | high | 0 | 112650 | 0.0 | PASS |
| fk_items_product | order_items | integrity | high | 0 | 112650 | 0.0 | PASS |
| fk_items_seller | order_items | integrity | high | 0 | 112650 | 0.0 | PASS |
| fk_payments_order | order_payments | integrity | high | 0 | 103886 | 0.0 | PASS |
| fk_reviews_order | order_reviews | integrity | high | 0 | 99224 | 0.0 | PASS |
| items_non_positive_price | order_items | validity | high | 0 | 112650 | 0.0 | PASS |
| items_negative_freight | order_items | validity | high | 0 | 112650 | 0.0 | PASS |
| payments_negative_value | order_payments | validity | high | 0 | 103886 | 0.0 | PASS |
| reviews_score_out_of_range | order_reviews | validity | high | 0 | 99224 | 0.0 | PASS |
| delivered_before_purchase | orders | consistency | high | 0 | 96476 | 0.0 | PASS |
| orders_invalid_status | orders | validity | medium | 0 | 99441 | 0.0 | PASS |
| customers_invalid_state | customers | validity | low | 0 | 99441 | 0.0 | PASS |

## 2. Columns with nulls

| Table | Column | Nulls | Null % | Distinct |
|---|---|---:|---:|---:|
| order_reviews | review_comment_title | 87,656 | 88.34 | 4,527 |
| order_reviews | review_comment_message | 58,247 | 58.7 | 36,159 |
| orders | order_delivered_customer_date | 2,965 | 2.98 | 95,664 |
| products | product_category_name | 610 | 1.85 | 73 |
| products | product_name_lenght | 610 | 1.85 | 66 |
| products | product_description_lenght | 610 | 1.85 | 2,960 |
| products | product_photos_qty | 610 | 1.85 | 19 |
| orders | order_delivered_carrier_date | 1,783 | 1.79 | 81,018 |
| orders | order_approved_at | 160 | 0.16 | 90,733 |
| products | product_weight_g | 2 | 0.01 | 2,204 |
| products | product_length_cm | 2 | 0.01 | 99 |
| products | product_height_cm | 2 | 0.01 | 102 |
| products | product_width_cm | 2 | 0.01 | 95 |

## 3. Full column profile

| Table | Column | Rows | Nulls | Distinct | Min | Max |
|---|---|---:|---:|---:|---|---|
| customers | customer_id | 99,441 | 0 | 99,441 | 00012a2ce6f8dcda20d059ce98491703 | ffffe8b65bbe3087b653a978c870db99 |
| customers | customer_unique_id | 99,441 | 0 | 96,096 | 0000366f3b9a7992bf8c76cfdf3221e2 | ffffd2657e2aad2907e67c3e9daecbeb |
| customers | customer_zip_code_prefix | 99,441 | 0 | 14,994 | 01003 | 99990 |
| customers | customer_city | 99,441 | 0 | 4,119 | abadia dos dourados | zortea |
| customers | customer_state | 99,441 | 0 | 27 | AC | TO |
| geolocation | geolocation_zip_code_prefix | 1,000,163 | 0 | 19,015 | 01001 | 99990 |
| geolocation | geolocation_lat | 1,000,163 | 0 | 717,372 | -0.00004367379244740171 | -9.99973165863238 |
| geolocation | geolocation_lng | 1,000,163 | 0 | 717,615 | -101.46676644931476 | -98.48412074808029 |
| geolocation | geolocation_city | 1,000,163 | 0 | 8,011 | 4o. centenario | zortéa |
| geolocation | geolocation_state | 1,000,163 | 0 | 27 | AC | TO |
| order_items | order_id | 112,650 | 0 | 98,666 | 00010242fe8c5a6d1ba2dd792cb16214 | fffe41c64501cc87c801fd61db3f6244 |
| order_items | order_item_id | 112,650 | 0 | 21 | 1 | 9 |
| order_items | product_id | 112,650 | 0 | 32,951 | 00066f42aeeb9f3007548bb9d3f33c38 | fffe9eeff12fcbd74a2f2b007dde0c58 |
| order_items | seller_id | 112,650 | 0 | 3,095 | 0015a82c2db000af6aaaf3ae2ecb0532 | ffff564a4f9085cd26170f4732393726 |
| order_items | shipping_limit_date | 112,650 | 0 | 93,318 | 2016-09-19 00:15:34 | 2020-04-09 22:35:08 |
| order_items | price | 112,650 | 0 | 5,968 | 0.85 | 999.99 |
| order_items | freight_value | 112,650 | 0 | 6,999 | 0.00 | 99.97 |
| order_payments | order_id | 103,886 | 0 | 99,440 | 00010242fe8c5a6d1ba2dd792cb16214 | fffe41c64501cc87c801fd61db3f6244 |
| order_payments | payment_sequential | 103,886 | 0 | 29 | 1 | 9 |
| order_payments | payment_type | 103,886 | 0 | 5 | boleto | voucher |
| order_payments | payment_installments | 103,886 | 0 | 24 | 0 | 9 |
| order_payments | payment_value | 103,886 | 0 | 29,077 | 0.00 | 99.99 |
| order_reviews | review_id | 99,224 | 0 | 98,410 | 0001239bc1de2e33cb583967c2ca4c67 | fffefe7a48d22f7b32046421062219d1 |
| order_reviews | order_id | 99,224 | 0 | 98,673 | 00010242fe8c5a6d1ba2dd792cb16214 | fffe41c64501cc87c801fd61db3f6244 |
| order_reviews | review_score | 99,224 | 0 | 5 | 1 | 5 |
| order_reviews | review_comment_title | 99,224 | 87,656 | 4,527 |   | ZMA |
| order_reviews | review_comment_message | 99,224 | 58,247 | 36,159 | 
 | Zero responsabilidade |
| order_reviews | review_creation_date | 99,224 | 0 | 636 | 2016-10-02 00:00:00 | 2018-08-31 00:00:00 |
| order_reviews | review_answer_timestamp | 99,224 | 0 | 98,248 | 2016-10-07 18:32:28 | 2018-10-29 12:27:35 |
| orders | order_id | 99,441 | 0 | 99,441 | 00010242fe8c5a6d1ba2dd792cb16214 | fffe41c64501cc87c801fd61db3f6244 |
| orders | customer_id | 99,441 | 0 | 99,441 | 00012a2ce6f8dcda20d059ce98491703 | ffffe8b65bbe3087b653a978c870db99 |
| orders | order_status | 99,441 | 0 | 8 | approved | unavailable |
| orders | order_purchase_timestamp | 99,441 | 0 | 98,875 | 2016-09-04 21:15:19 | 2018-10-17 17:30:18 |
| orders | order_approved_at | 99,441 | 160 | 90,733 | 2016-09-15 12:16:38 | 2018-09-03 17:40:06 |
| orders | order_delivered_carrier_date | 99,441 | 1,783 | 81,018 | 2016-10-08 10:34:01 | 2018-09-11 19:48:28 |
| orders | order_delivered_customer_date | 99,441 | 2,965 | 95,664 | 2016-10-11 13:46:32 | 2018-10-17 13:22:46 |
| orders | order_estimated_delivery_date | 99,441 | 0 | 459 | 2016-09-30 00:00:00 | 2018-11-12 00:00:00 |
| products | product_id | 32,951 | 0 | 32,951 | 00066f42aeeb9f3007548bb9d3f33c38 | fffe9eeff12fcbd74a2f2b007dde0c58 |
| products | product_category_name | 32,951 | 610 | 73 | agro_industria_e_comercio | utilidades_domesticas |
| products | product_name_lenght | 32,951 | 610 | 66 | 10 | 9 |
| products | product_description_lenght | 32,951 | 610 | 2,960 | 100 | 999 |
| products | product_photos_qty | 32,951 | 610 | 19 | 1 | 9 |
| products | product_weight_g | 32,951 | 2 | 2,204 | 0 | 998 |
| products | product_length_cm | 32,951 | 2 | 99 | 10 | 99 |
| products | product_height_cm | 32,951 | 2 | 102 | 10 | 99 |
| products | product_width_cm | 32,951 | 2 | 95 | 10 | 98 |
| sellers | seller_id | 3,095 | 0 | 3,095 | 0015a82c2db000af6aaaf3ae2ecb0532 | ffff564a4f9085cd26170f4732393726 |
| sellers | seller_zip_code_prefix | 3,095 | 0 | 2,246 | 01001 | 99730 |
| sellers | seller_city | 3,095 | 0 | 611 | 04482255 | xaxim |
| sellers | seller_state | 3,095 | 0 | 23 | AC | SP |
| product_category_translation | product_category_name | 71 | 0 | 71 | agro_industria_e_comercio | utilidades_domesticas |
| product_category_translation | product_category_name_english | 71 | 0 | 71 | agro_industry_and_commerce | watches_gifts |