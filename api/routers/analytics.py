"""
Analytics & Executive Dashboard endpoints backed by warehouse.* tables.
"""
from typing import Any, Dict
from fastapi import APIRouter, HTTPException, Query
from api.db import fetch_all, fetch_one, load_analytical_queries

router = APIRouter(prefix="/api/analytics", tags=["Analytics"])


@router.get("/kpis")
def get_executive_kpis(
    include_synthetic: bool = Query(True, description="True = Full 2016-2026 timeline, False = Olist original only")
) -> Dict[str, Any]:
    syn_filter_sales = "" if include_synthetic else "AND f.is_synthetic = FALSE"
    syn_filter_plain = "" if include_synthetic else "AND is_synthetic = FALSE"

    sales_kpi = fetch_one(f"""
        SELECT
            COUNT(DISTINCT f.order_id) AS total_orders,
            COUNT(DISTINCT f.customer_key) FILTER (WHERE f.customer_key <> -1) AS unique_customers,
            ROUND(COALESCE(SUM(f.price), 0), 2) AS total_revenue,
            ROUND(COALESCE(SUM(f.freight_value), 0), 2) AS total_freight,
            ROUND(
                COALESCE(SUM(f.price) / NULLIF(COUNT(DISTINCT f.order_id), 0), 0),
                2
            ) AS avg_order_value
        FROM warehouse.fact_sales f
        WHERE f.is_valid_sale = TRUE {syn_filter_sales};
    """)

    delivery_kpi = fetch_one(f"""
        WITH order_delivery AS (
            SELECT
                order_id,
                MAX(delivery_days) AS delivery_days,
                MAX(delay_days) AS delay_days
            FROM warehouse.fact_sales
            WHERE is_delivered = TRUE {syn_filter_plain}
            GROUP BY order_id
        )
        SELECT
            COUNT(*) AS delivered_orders,
            ROUND(COALESCE(AVG(delivery_days), 0), 2) AS avg_delivery_days,
            ROUND(
                COALESCE(
                    100.0 * COUNT(*) FILTER (WHERE delay_days > 0)
                    / NULLIF(COUNT(*) FILTER (WHERE delay_days IS NOT NULL), 0),
                    0
                ),
                2
            ) AS late_order_percentage
        FROM order_delivery;
    """)

    review_kpi = fetch_one(f"""
        SELECT
            COUNT(*) AS total_reviews,
            ROUND(COALESCE(AVG(review_score), 0), 2) AS avg_review_score
        FROM warehouse.fact_reviews
        WHERE review_score IS NOT NULL {syn_filter_plain};
    """)

    inventory_kpi = fetch_one("""
        WITH latest AS (
            SELECT MAX(snapshot_date_key) AS snapshot_date_key
            FROM warehouse.fact_inventory
        )
        SELECT
            COUNT(*) AS products_tracked,
            COUNT(*) FILTER (WHERE i.is_low_stock = TRUE) AS low_stock_products,
            COUNT(*) FILTER (WHERE i.closing_stock = 0) AS stock_out_products
        FROM warehouse.fact_inventory i
        JOIN latest l ON i.snapshot_date_key = l.snapshot_date_key;
    """)

    return {
        "scope": "full_timeline" if include_synthetic else "olist_reference",
        "sales": sales_kpi,
        "delivery": delivery_kpi,
        "reviews": review_kpi,
        "inventory": inventory_kpi,
    }


@router.get("/queries")
def list_queries():
    queries = load_analytical_queries()
    return [
        {
            "query_id": q["query_id"],
            "title": q["title"],
            "section": q["section"],
        }
        for q in queries.values()
    ]


@router.get("/queries/{query_id}")
def execute_analytical_query(query_id: int):
    queries = load_analytical_queries()
    if query_id not in queries:
        raise HTTPException(status_code=404, detail=f"Query {query_id} not found (valid range: 1-21).")

    q = queries[query_id]
    rows = fetch_all(q["sql"])
    return {
        "query_id": q["query_id"],
        "title": q["title"],
        "section": q["section"],
        "row_count": len(rows),
        "data": rows,
    }


@router.get("/dashboard")
def get_dashboard_bundle(include_synthetic: bool = Query(True)):
    """
    Returns KPIs + key analytical queries in a single payload for the frontend dashboard.
    """
    queries = load_analytical_queries()
    kpis = get_executive_kpis(include_synthetic=include_synthetic)

    if include_synthetic:
        monthly_q, cat_q, deliv_rev_q, pay_q, state_q, low_stock_q = 7, 8, 12, 14, 15, 18
    else:
        monthly_q, cat_q, deliv_rev_q, pay_q, state_q, low_stock_q = 1, 8, 12, 4, 5, 18

    return {
        "kpis": kpis,
        "monthly_sales": fetch_all(queries[monthly_q]["sql"]) if monthly_q in queries else [],
        "top_categories": fetch_all(queries[cat_q]["sql"]) if cat_q in queries else [],
        "delivery_vs_reviews": fetch_all(queries[deliv_rev_q]["sql"]) if deliv_rev_q in queries else [],
        "payment_mix": fetch_all(queries[pay_q]["sql"]) if pay_q in queries else [],
        "sales_by_state": fetch_all(queries[state_q]["sql"]) if state_q in queries else [],
        "low_stock_alerts": fetch_all(queries[low_stock_q]["sql"]) if low_stock_q in queries else [],
    }
