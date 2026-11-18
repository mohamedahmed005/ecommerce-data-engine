import threading
import time
from typing import Any, Dict, Optional, Tuple
from fastapi import APIRouter, Query
from api.db import fetch_all, fetch_one

router = APIRouter(prefix="/api/analytics", tags=["Analytics"])

_CACHE: Dict[Tuple[str, bool, Optional[int]], Tuple[float, Any]] = {}
CACHE_TTL_SECONDS = 3600  # 1 hour cache


def _get_cached(key: Tuple[str, bool, Optional[int]]):
    entry = _CACHE.get(key)
    if entry and (time.time() - entry[0]) < CACHE_TTL_SECONDS:
        return entry[1]
    return None


def _set_cached(key: Tuple[str, bool, Optional[int]], value: Any):
    _CACHE[key] = (time.time(), value)
    return value


def _syn_filter(include_synthetic: bool, alias: str = "f") -> str:
    return "" if include_synthetic else f"AND {alias}.is_synthetic = FALSE"


def _year_filter(year: Optional[int], alias: str = "d") -> str:
    return f"AND {alias}.year = {int(year)}" if year is not None else ""


@router.get("/kpis")
def get_kpis(
    include_synthetic: bool = Query(True),
    year: Optional[int] = Query(None),
):
    cache_key = ("kpis", include_synthetic, year)
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    syn = _syn_filter(include_synthetic, "f")
    yr_join = "JOIN warehouse.dim_date d ON f.purchase_date_key = d.date_key" if year is not None else ""
    yr_cond = _year_filter(year, "d")

    # Single-pass CTE combining Sales, Delivery & Reviews in one DB round-trip
    combined_kpi = fetch_one(f"""
        WITH valid_items AS (
            SELECT
                f.order_id,
                COALESCE(f.price, 0) AS price,
                COALESCE(f.freight_value, 0) AS freight_value,
                f.delivery_days,
                COALESCE(f.delay_days, 0) AS delay_days
            FROM warehouse.fact_sales f
            {yr_join}
            WHERE f.is_valid_sale = TRUE {syn} {yr_cond}
        ),
        orders_agg AS (
            SELECT
                order_id,
                SUM(price) AS ord_price,
                SUM(freight_value) AS ord_freight,
                MAX(delivery_days) AS delivery_days,
                BOOL_OR(delay_days > 0) AS is_late
            FROM valid_items
            GROUP BY order_id
        ),
        rev_agg AS (
            SELECT
                ROUND(AVG(r.review_score)::numeric, 2) AS avg_review_score,
                COUNT(*) AS total_reviews
            FROM warehouse.fact_reviews r
            WHERE EXISTS (SELECT 1 FROM orders_agg o WHERE o.order_id = r.order_id)
        )
        SELECT
            (SELECT COUNT(*) FROM orders_agg) AS total_orders,
            (SELECT COALESCE(SUM(ord_price + ord_freight), 0) FROM orders_agg) AS total_revenue,
            (SELECT COALESCE(SUM(ord_price), 0) FROM orders_agg) AS product_revenue,
            (SELECT COALESCE(SUM(ord_freight), 0) FROM orders_agg) AS freight_revenue,
            (SELECT COALESCE(AVG(price + freight_value), 0) FROM valid_items) AS avg_item_value,
            (SELECT ROUND(AVG(delivery_days)::numeric, 2) FROM orders_agg) AS avg_delivery_days,
            (SELECT ROUND(100.0 * SUM(CASE WHEN is_late THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 2) FROM orders_agg) AS late_order_percentage,
            (SELECT avg_review_score FROM rev_agg) AS avg_review_score,
            (SELECT total_reviews FROM rev_agg) AS total_reviews
    """)

    inv_cached = _get_cached(("inv_kpi", True, None))
    if inv_cached is None:
        inv_cached = fetch_one("""
            WITH latest AS (
                SELECT DISTINCT ON (product_key)
                    closing_stock, is_low_stock
                FROM warehouse.fact_inventory
                ORDER BY product_key, snapshot_date_key DESC
            )
            SELECT
                COUNT(*) AS tracked_products,
                SUM(CASE WHEN is_low_stock THEN 1 ELSE 0 END) AS low_stock_products,
                SUM(CASE WHEN closing_stock = 0 THEN 1 ELSE 0 END) AS out_of_stock_products
            FROM latest
        """)
        _set_cached(("inv_kpi", True, None), inv_cached)

    result = {
        "include_synthetic": include_synthetic,
        "scope": "Full Timeline (Olist + Synthetic)" if include_synthetic else "Original Olist Only",
        "year": year,
        "sales": {
            "total_orders": int(combined_kpi["total_orders"] or 0),
            "total_revenue": round(float(combined_kpi["total_revenue"] or 0), 2),
            "product_revenue": round(float(combined_kpi["product_revenue"] or 0), 2),
            "freight_revenue": round(float(combined_kpi["freight_revenue"] or 0), 2),
            "avg_item_value": round(float(combined_kpi["avg_item_value"] or 0), 2),
            "avg_order_value": round(float(combined_kpi["total_revenue"] or 0) / max(int(combined_kpi["total_orders"] or 1), 1), 2),
        },
        "delivery": {
            "avg_delivery_days": float(combined_kpi["avg_delivery_days"] or 0),
            "late_order_percentage": float(combined_kpi["late_order_percentage"] or 0),
        },
        "reviews": {
            "avg_review_score": float(combined_kpi["avg_review_score"] or 0),
            "total_reviews": int(combined_kpi["total_reviews"] or 0),
        },
        "inventory": {
            "tracked_products": int(inv_cached["tracked_products"] or 0),
            "products_tracked": int(inv_cached["tracked_products"] or 0),
            "low_stock_products": int(inv_cached["low_stock_products"] or 0),
            "out_of_stock_products": int(inv_cached["out_of_stock_products"] or 0),
        },
    }
    return _set_cached(cache_key, result)


@router.get("/dashboard")
def get_dashboard(
    include_synthetic: bool = Query(True),
    year: Optional[int] = Query(None),
):
    cache_key = ("dashboard", include_synthetic, year)
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    syn = _syn_filter(include_synthetic, "f")
    yr_cond = _year_filter(year, "d")

    monthly_cached = _get_cached(("monthly_base", include_synthetic, None))
    if monthly_cached is None:
        monthly_cached = fetch_all(f"""
            SELECT
                d.year,
                d.month,
                TRIM(d.month_name) AS month_name,
                COUNT(DISTINCT f.order_id) AS total_orders,
                ROUND(SUM(COALESCE(f.price, 0) + COALESCE(f.freight_value, 0))::numeric, 2) AS total_sales
            FROM warehouse.fact_sales f
            JOIN warehouse.dim_date d ON f.purchase_date_key = d.date_key
            WHERE f.is_valid_sale = TRUE {syn}
            GROUP BY d.year, d.month, d.month_name
            ORDER BY d.year, d.month
        """)
        _set_cached(("monthly_base", include_synthetic, None), monthly_cached)

    top_categories = fetch_all(f"""
        WITH cat_sales AS (
            SELECT
                COALESCE(p.category_name_en, 'uncategorized') AS category_name_en,
                COUNT(DISTINCT f.order_id) AS total_orders,
                SUM(COALESCE(f.price, 0) + COALESCE(f.freight_value, 0)) AS total_sales
            FROM warehouse.fact_sales f
            JOIN warehouse.dim_date d ON f.purchase_date_key = d.date_key
            LEFT JOIN warehouse.dim_product p ON f.product_key = p.product_key
            WHERE f.is_valid_sale = TRUE {syn} {yr_cond}
            GROUP BY 1
        )
        SELECT
            category_name_en,
            total_orders,
            ROUND(total_sales::numeric, 2) AS total_sales,
            ROUND(100.0 * total_sales / NULLIF(SUM(total_sales) OVER (), 0), 2) AS sales_share_percentage
        FROM cat_sales
        ORDER BY total_sales DESC
        LIMIT 10
    """)

    low_stock_cached = _get_cached(("low_stock_base", True, None))
    if low_stock_cached is None:
        low_stock_cached = fetch_all("""
            WITH latest AS (
                SELECT DISTINCT ON (i.product_key)
                    i.product_key,
                    i.closing_stock,
                    i.reorder_level,
                    i.units_sold AS units_sold_last_month,
                    i.is_low_stock
                FROM warehouse.fact_inventory i
                ORDER BY i.product_key, i.snapshot_date_key DESC
            )
            SELECT
                p.product_id,
                COALESCE(p.category_name_en, 'uncategorized') AS category_name_en,
                l.closing_stock,
                l.reorder_level,
                l.units_sold_last_month
            FROM latest l
            JOIN warehouse.dim_product p ON l.product_key = p.product_key
            WHERE l.is_low_stock = TRUE
            ORDER BY l.closing_stock ASC, l.units_sold_last_month DESC
            LIMIT 10
        """)
        _set_cached(("low_stock_base", True, None), low_stock_cached)

    geo_states = fetch_all(f"""
        WITH ord_state AS (
            SELECT
                f.order_id,
                COALESCE(c.customer_state, 'Unknown') AS state,
                SUM(COALESCE(f.price, 0) + COALESCE(f.freight_value, 0)) AS order_rev,
                MAX(f.delivery_days) AS delivery_days,
                BOOL_OR(COALESCE(f.delay_days, 0) > 0) AS is_late
            FROM warehouse.fact_sales f
            JOIN warehouse.dim_date d ON f.purchase_date_key = d.date_key
            LEFT JOIN warehouse.dim_customer c ON f.customer_key = c.customer_key
            WHERE f.is_valid_sale = TRUE {syn} {yr_cond}
            GROUP BY f.order_id, 2
        )
        SELECT
            state,
            COUNT(*) AS total_orders,
            ROUND(SUM(order_rev)::numeric, 2) AS total_sales,
            ROUND(AVG(delivery_days)::numeric, 1) AS avg_delivery_days,
            ROUND(100.0 * SUM(CASE WHEN is_late THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 1) AS late_pct
        FROM ord_state
        GROUP BY state
        ORDER BY total_sales DESC
        LIMIT 10
    """)

    payment_methods = fetch_all(f"""
        WITH valid_orders AS (
            SELECT DISTINCT f.order_id
            FROM warehouse.fact_sales f
            JOIN warehouse.dim_date d ON f.purchase_date_key = d.date_key
            WHERE f.is_valid_sale = TRUE {syn} {yr_cond}
        )
        SELECT
            COALESCE(fp.payment_type, 'other') AS payment_type,
            COUNT(*) AS payment_count,
            ROUND(SUM(fp.payment_value)::numeric, 2) AS total_value,
            ROUND(AVG(fp.payment_installments)::numeric, 1) AS avg_installments
        FROM warehouse.fact_payments fp
        JOIN valid_orders vo ON fp.order_id = vo.order_id
        GROUP BY 1
        ORDER BY total_value DESC
    """)

    top_sellers = fetch_all(f"""
        WITH seller_orders AS (
            SELECT
                s.seller_id,
                COALESCE(s.seller_city, 'Unknown') AS seller_city,
                COALESCE(s.seller_state, '--') AS seller_state,
                f.order_id,
                SUM(COALESCE(f.price, 0) + COALESCE(f.freight_value, 0)) AS item_rev,
                BOOL_OR(COALESCE(f.delay_days, 0) > 0) AS is_late
            FROM warehouse.fact_sales f
            JOIN warehouse.dim_date d ON f.purchase_date_key = d.date_key
            JOIN warehouse.dim_seller s ON f.seller_key = s.seller_key
            WHERE f.is_valid_sale = TRUE AND f.seller_key <> -1 {syn} {yr_cond}
            GROUP BY s.seller_id, 2, 3, f.order_id
        )
        SELECT
            seller_id,
            seller_city,
            seller_state,
            COUNT(*) AS total_orders,
            ROUND(SUM(item_rev)::numeric, 2) AS total_sales,
            ROUND(100.0 * SUM(CASE WHEN is_late THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 1) AS late_pct
        FROM seller_orders
        GROUP BY seller_id, seller_city, seller_state
        ORDER BY total_sales DESC
        LIMIT 8
    """)

    result = {
        "include_synthetic": include_synthetic,
        "scope": "Full Timeline (Olist + Synthetic)" if include_synthetic else "Original Olist Only",
        "year": year,
        "monthly_sales": monthly_cached,
        "top_categories": top_categories,
        "low_stock_alerts": low_stock_cached,
        "geo_states": geo_states,
        "payment_methods": payment_methods,
        "top_sellers": top_sellers,
    }
    return _set_cached(cache_key, result)


def _warm_cache_background():
    """Pre-warm ALL years & modes in background so switching years is instant."""
    try:
        dash = get_dashboard(include_synthetic=True, year=None)
        get_kpis(include_synthetic=True, year=None)
        years = sorted({int(m["year"]) for m in dash.get("monthly_sales", [])}, reverse=True)
        for yr in years:
            get_kpis(include_synthetic=True, year=yr)
            get_dashboard(include_synthetic=True, year=yr)
        get_kpis(include_synthetic=False, year=None)
        get_dashboard(include_synthetic=False, year=None)
    except Exception:
        pass


threading.Thread(target=_warm_cache_background, daemon=True).start()

# Backward-compatibility alias for chat.py
def get_executive_kpis(include_synthetic: bool = True, year: Optional[int] = None):
    return get_kpis(include_synthetic=include_synthetic, year=year)