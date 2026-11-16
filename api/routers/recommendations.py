"""
Inventory-Aware Hybrid Recommendation Engine using warehouse.* tables.
"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from api.db import fetch_all, fetch_one

router = APIRouter(prefix="/api/recommendations", tags=["Recommendations"])


@router.get("/samples")
def get_demo_samples():
    """
    Returns sample products, repeat customers, and categories for frontend dropdowns.
    """
    categories = fetch_all("""
        SELECT DISTINCT COALESCE(category_name_en, 'Unknown') AS category_name_en
        FROM warehouse.dim_product
        WHERE product_key <> -1 AND category_name_en IS NOT NULL
        ORDER BY category_name_en;
    """)

    top_products = fetch_all("""
        WITH latest_inv AS (
            SELECT product_key, closing_stock, is_low_stock
            FROM warehouse.fact_inventory
            WHERE snapshot_date_key = (SELECT MAX(snapshot_date_key) FROM warehouse.fact_inventory)
        )
        SELECT
            p.product_id,
            COALESCE(p.category_name_en, 'Unknown') AS category_name_en,
            COUNT(*) AS orders_count,
            ROUND(AVG(f.price), 2) AS avg_price,
            COALESCE(i.closing_stock, 0) AS closing_stock
        FROM warehouse.fact_sales f
        JOIN warehouse.dim_product p ON f.product_key = p.product_key
        LEFT JOIN latest_inv i ON p.product_key = i.product_key
        WHERE f.is_valid_sale = TRUE AND p.product_key <> -1
        GROUP BY p.product_id, p.category_name_en, i.closing_stock
        ORDER BY orders_count DESC
        LIMIT 20;
    """)

    repeat_customers = fetch_all("""
        SELECT
            c.customer_unique_id,
            c.customer_city,
            c.customer_state,
            COUNT(DISTINCT f.order_id) AS total_orders,
            ROUND(SUM(f.price), 2) AS total_spent
        FROM warehouse.fact_sales f
        JOIN warehouse.dim_customer c ON f.customer_key = c.customer_key
        WHERE f.is_valid_sale = TRUE AND c.customer_key <> -1
        GROUP BY c.customer_unique_id, c.customer_city, c.customer_state
        HAVING COUNT(DISTINCT f.order_id) >= 2
        ORDER BY total_orders DESC, total_spent DESC
        LIMIT 20;
    """)

    return {
        "categories": [c["category_name_en"] for c in categories],
        "sample_products": top_products,
        "sample_customers": repeat_customers,
    }


@router.get("/product/{product_id}")
def recommend_for_product(
    product_id: str,
    limit: int = Query(8, ge=1, le=25),
    in_stock_only: bool = Query(True, description="Only recommend items with closing_stock > 0"),
):
    target = fetch_one("""
        WITH latest_inv AS (
            SELECT product_key, closing_stock, reorder_level, is_low_stock
            FROM warehouse.fact_inventory
            WHERE snapshot_date_key = (SELECT MAX(snapshot_date_key) FROM warehouse.fact_inventory)
        )
        SELECT
            p.product_key,
            p.product_id,
            COALESCE(p.category_name_en, 'Unknown') AS category_name_en,
            p.weight_g,
            ROUND(AVG(f.price), 2) AS avg_price,
            COUNT(DISTINCT f.order_id) AS total_orders,
            COALESCE(i.closing_stock, 0) AS closing_stock,
            COALESCE(i.is_low_stock, FALSE) AS is_low_stock
        FROM warehouse.dim_product p
        LEFT JOIN warehouse.fact_sales f
            ON p.product_key = f.product_key AND f.is_valid_sale = TRUE
        LEFT JOIN latest_inv i
            ON p.product_key = i.product_key
        WHERE p.product_id = %s
        GROUP BY p.product_key, p.product_id, p.category_name_en, p.weight_g, i.closing_stock, i.is_low_stock;
    """, (product_id,))

    if not target:
        raise HTTPException(status_code=404, detail=f"Product '{product_id}' not found in warehouse.dim_product.")

    stock_filter = "AND COALESCE(inv.closing_stock, 0) > 0" if in_stock_only else ""

    recs = fetch_all(f"""
        WITH latest_snap AS (
            SELECT MAX(snapshot_date_key) AS snapshot_date_key FROM warehouse.fact_inventory
        ),
        latest_inv AS (
            SELECT i.product_key, i.closing_stock, i.reorder_level, i.is_low_stock
            FROM warehouse.fact_inventory i
            JOIN latest_snap s ON i.snapshot_date_key = s.snapshot_date_key
        ),
        target_orders AS (
            SELECT DISTINCT order_id
            FROM warehouse.fact_sales
            WHERE product_key = %s AND is_valid_sale = TRUE
        ),
        co_purchased AS (
            SELECT
                f.product_key,
                COUNT(DISTINCT f.order_id) AS co_purchase_count
            FROM warehouse.fact_sales f
            JOIN target_orders t ON f.order_id = t.order_id
            WHERE f.product_key <> %s AND f.is_valid_sale = TRUE
            GROUP BY f.product_key
        ),
        product_stats AS (
            SELECT
                f.product_key,
                COUNT(DISTINCT f.order_id) AS total_orders,
                ROUND(AVG(f.price), 2) AS avg_price,
                ROUND(AVG(r.review_score), 2) AS avg_review_score
            FROM warehouse.fact_sales f
            LEFT JOIN warehouse.fact_reviews r ON f.order_id = r.order_id
            WHERE f.is_valid_sale = TRUE
            GROUP BY f.product_key
        )
        SELECT
            p.product_id,
            COALESCE(p.category_name_en, 'Unknown') AS category_name_en,
            ps.avg_price,
            ps.total_orders,
            COALESCE(ps.avg_review_score, 4.0) AS avg_review_score,
            COALESCE(cp.co_purchase_count, 0) AS co_purchase_count,
            COALESCE(inv.closing_stock, 0) AS closing_stock,
            COALESCE(inv.reorder_level, 0) AS reorder_level,
            COALESCE(inv.is_low_stock, FALSE) AS is_low_stock,
            CASE
                WHEN COALESCE(cp.co_purchase_count, 0) > 0 THEN 'Frequently Bought Together'
                WHEN p.category_name_en = %s THEN 'Top Rated in Same Category'
                ELSE 'Popular Alternative'
            END AS recommendation_reason,
            ROUND(
                (COALESCE(cp.co_purchase_count, 0) * 25.0)
                + (CASE WHEN p.category_name_en = %s THEN 30.0 ELSE 0.0 END)
                + (COALESCE(ps.avg_review_score, 4.0) * 5.0)
                + LEAST(ps.total_orders / 20.0, 25.0)
                + (CASE WHEN COALESCE(inv.closing_stock, 0) > COALESCE(inv.reorder_level, 0) THEN 10.0 ELSE 0.0 END)
                - LEAST(ABS(COALESCE(ps.avg_price, 0) - COALESCE(%s, ps.avg_price)) / 25.0, 15.0),
                2
            ) AS recommendation_score
        FROM warehouse.dim_product p
        JOIN product_stats ps ON p.product_key = ps.product_key
        LEFT JOIN co_purchased cp ON p.product_key = cp.product_key
        LEFT JOIN latest_inv inv ON p.product_key = inv.product_key
        WHERE p.product_key <> %s
          AND p.product_key <> -1
          AND (COALESCE(cp.co_purchase_count, 0) > 0 OR p.category_name_en = %s)
          {stock_filter}
        ORDER BY recommendation_score DESC, ps.total_orders DESC
        LIMIT %s;
    """, (
        target["product_key"],
        target["product_key"],
        target["category_name_en"],
        target["category_name_en"],
        target["avg_price"],
        target["product_key"],
        target["category_name_en"],
        limit,
    ))

    return {
        "target_product": target,
        "recommendations": recs,
    }


@router.get("/customer/{customer_unique_id}")
def recommend_for_customer(
    customer_unique_id: str,
    limit: int = Query(8, ge=1, le=25),
    in_stock_only: bool = Query(True),
):
    customer = fetch_one("""
        SELECT customer_key, customer_unique_id, customer_city, customer_state
        FROM warehouse.dim_customer
        WHERE customer_unique_id = %s;
    """, (customer_unique_id,))

    if not customer:
        raise HTTPException(status_code=404, detail=f"Customer '{customer_unique_id}' not found.")

    history = fetch_all("""
        SELECT
            p.product_id,
            COALESCE(p.category_name_en, 'Unknown') AS category_name_en,
            f.price,
            f.order_id
        FROM warehouse.fact_sales f
        JOIN warehouse.dim_product p ON f.product_key = p.product_key
        WHERE f.customer_key = %s AND f.is_valid_sale = TRUE
        ORDER BY f.purchase_date_key DESC
        LIMIT 15;
    """, (customer["customer_key"],))

    stock_filter = "AND COALESCE(inv.closing_stock, 0) > 0" if in_stock_only else ""

    recs = fetch_all(f"""
        WITH latest_snap AS (
            SELECT MAX(snapshot_date_key) AS snapshot_date_key FROM warehouse.fact_inventory
        ),
        latest_inv AS (
            SELECT i.product_key, i.closing_stock, i.reorder_level, i.is_low_stock
            FROM warehouse.fact_inventory i
            JOIN latest_snap s ON i.snapshot_date_key = s.snapshot_date_key
        ),
        cust_items AS (
            SELECT DISTINCT product_key
            FROM warehouse.fact_sales
            WHERE customer_key = %s AND is_valid_sale = TRUE
        ),
        cust_categories AS (
            SELECT
                p.category_name_en,
                COUNT(*) AS cat_purchases
            FROM warehouse.fact_sales f
            JOIN warehouse.dim_product p ON f.product_key = p.product_key
            WHERE f.customer_key = %s AND f.is_valid_sale = TRUE
            GROUP BY p.category_name_en
        ),
        product_stats AS (
            SELECT
                f.product_key,
                COUNT(DISTINCT f.order_id) AS total_orders,
                ROUND(AVG(f.price), 2) AS avg_price,
                ROUND(AVG(r.review_score), 2) AS avg_review_score
            FROM warehouse.fact_sales f
            LEFT JOIN warehouse.fact_reviews r ON f.order_id = r.order_id
            WHERE f.is_valid_sale = TRUE
            GROUP BY f.product_key
        )
        SELECT
            p.product_id,
            COALESCE(p.category_name_en, 'Unknown') AS category_name_en,
            ps.avg_price,
            ps.total_orders,
            COALESCE(ps.avg_review_score, 4.0) AS avg_review_score,
            COALESCE(inv.closing_stock, 0) AS closing_stock,
            COALESCE(inv.is_low_stock, FALSE) AS is_low_stock,
            CASE
                WHEN cc.cat_purchases IS NOT NULL THEN 'Matches Your Favorite Category (' || p.category_name_en || ')'
                ELSE 'Trending Best-Seller in Stock'
            END AS recommendation_reason,
            ROUND(
                (COALESCE(cc.cat_purchases, 0) * 30.0)
                + (COALESCE(ps.avg_review_score, 4.0) * 6.0)
                + LEAST(ps.total_orders / 15.0, 30.0)
                + (CASE WHEN COALESCE(inv.closing_stock, 0) > COALESCE(inv.reorder_level, 0) THEN 15.0 ELSE 0.0 END),
                2
            ) AS recommendation_score
        FROM warehouse.dim_product p
        JOIN product_stats ps ON p.product_key = ps.product_key
        LEFT JOIN cust_categories cc ON p.category_name_en = cc.category_name_en
        LEFT JOIN latest_inv inv ON p.product_key = inv.product_key
        WHERE p.product_key NOT IN (SELECT product_key FROM cust_items)
          AND p.product_key <> -1
          {stock_filter}
        ORDER BY recommendation_score DESC, ps.total_orders DESC
        LIMIT %s;
    """, (customer["customer_key"], customer["customer_key"], limit))

    return {
        "customer": customer,
        "purchase_history": history,
        "recommendations": recs,
    }


@router.get("/trending")
def get_trending_in_stock(
    category: Optional[str] = Query(None, description="Filter by category_name_en"),
    limit: int = Query(10, ge=1, le=30),
):
    cat_clause = "AND p.category_name_en = %s" if category else ""
    params = (category, limit) if category else (limit,)

    rows = fetch_all(f"""
        WITH latest_snap AS (
            SELECT MAX(snapshot_date_key) AS snapshot_date_key FROM warehouse.fact_inventory
        ),
        latest_inv AS (
            SELECT i.product_key, i.closing_stock, i.reorder_level, i.units_sold, i.is_low_stock
            FROM warehouse.fact_inventory i
            JOIN latest_snap s ON i.snapshot_date_key = s.snapshot_date_key
        )
        SELECT
            p.product_id,
            COALESCE(p.category_name_en, 'Unknown') AS category_name_en,
            COUNT(DISTINCT f.order_id) AS total_orders,
            ROUND(AVG(f.price), 2) AS avg_price,
            COALESCE(inv.closing_stock, 0) AS closing_stock,
            COALESCE(inv.reorder_level, 0) AS reorder_level,
            COALESCE(inv.units_sold, 0) AS units_sold_last_month,
            COALESCE(inv.is_low_stock, FALSE) AS is_low_stock
        FROM warehouse.fact_sales f
        JOIN warehouse.dim_product p ON f.product_key = p.product_key
        JOIN latest_inv inv ON p.product_key = inv.product_key
        WHERE f.is_valid_sale = TRUE
          AND inv.closing_stock > inv.reorder_level
          {cat_clause}
        GROUP BY p.product_id, p.category_name_en, inv.closing_stock, inv.reorder_level, inv.units_sold, inv.is_low_stock
        ORDER BY inv.units_sold DESC, total_orders DESC
        LIMIT %s;
    """, params)

    return {"category": category or "all", "recommendations": rows}
