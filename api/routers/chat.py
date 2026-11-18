"""
Unified AI Assistant for Warehouse Analytics & Inventory-Aware Product Recommendations.
"""
from typing import Any, Dict, List, Optional
from fastapi import APIRouter
from pydantic import BaseModel
from api.db import fetch_all, load_analytical_queries
from api.routers.analytics import get_executive_kpis
from api.routers.recommendations import get_trending_in_stock

router = APIRouter(prefix="/api/chat", tags=["AI Assistant"])


class ChatRequest(BaseModel):
    message: str
    include_synthetic: bool = True


@router.post("")
def chat_assistant(req: ChatRequest) -> Dict[str, Any]:
    msg = req.message.lower().strip()
    queries = load_analytical_queries()

    # 2. Product Recommendation questions
    if any(k in msg for k in ["recommend", "suggest", "trending", "رشح", "اقترح", "توصية", "منتجات"]):
        cats = fetch_all("""
            SELECT DISTINCT category_name_en
            FROM warehouse.dim_product
            WHERE category_name_en IS NOT NULL;
        """)
        matched_cat: Optional[str] = None
        for c in cats:
            cat_name = c["category_name_en"]
            if cat_name and (cat_name.lower() in msg or cat_name.lower().replace("_", " ") in msg):
                matched_cat = cat_name
                break

        trending = get_trending_in_stock(category=matched_cat, limit=6)
        recs: List[Dict[str, Any]] = trending["recommendations"]
        cat_label = matched_cat if matched_cat else "all categories"
        return {
            "intent": "product_recommendation",
            "title": f"Top In-Stock Recommendations ({cat_label})",
            "answer": f"Found {len(recs)} high-velocity products in **{cat_label}** with healthy stock levels (`closing_stock > reorder_level`).",
            "query_id": None,
            "data": [],
            "recommendations": recs,
        }

    # 1. Inventory & Low-stock questions
    if any(k in msg for k in ["stock", "inventory", "reorder", "مخزون", "نواقص", "رصيد"]):
        if any(k in msg for k in ["cover", "coverage", "تغطية"]):
            q = queries[20]
        elif any(k in msg for k in ["health", "monthly", "شهري"]):
            q = queries[19]
        elif any(k in msg for k in ["best", "top", "أفضل"]):
            q = queries[21]
        else:
            q = queries[18]
        rows = fetch_all(q["sql"])
        return {
            "intent": "inventory_analytics",
            "title": q["title"],
            "answer": f"Here is the live warehouse report for **{q['title']}** ({len(rows)} records returned from `warehouse.fact_inventory`).",
            "query_id": q["query_id"],
            "data": rows,
            "recommendations": [],
        }

    # 3. Delivery & Shipping delay questions
    if any(k in msg for k in ["delivery", "delay", "late", "shipping", "توصيل", "تأخير", "شحن"]):
        q_id = 12 if "review" in msg or "تقييم" in msg else (11 if req.include_synthetic else 2)
        q = queries[q_id]
        rows = fetch_all(q["sql"])
        return {
            "intent": "delivery_analytics",
            "title": q["title"],
            "answer": f"Executed **{q['title']}** on `warehouse.fact_sales`.",
            "query_id": q_id,
            "data": rows,
            "recommendations": [],
        }

    # 4. Reviews & Satisfaction questions
    if any(k in msg for k in ["review", "rating", "score", "star", "تقييم", "مراجعات"]):
        q_id = 13 if req.include_synthetic else 3
        q = queries[q_id]
        rows = fetch_all(q["sql"])
        return {
            "intent": "review_analytics",
            "title": q["title"],
            "answer": f"Customer review breakdown from `warehouse.fact_reviews` (**{q['title']}**):",
            "query_id": q_id,
            "data": rows,
            "recommendations": [],
        }

    # 5. Payment methods questions
    if any(k in msg for k in ["payment", "credit", "boleto", "voucher", "installment", "دفع", "مدفوعات"]):
        q_id = 14 if req.include_synthetic else 4
        q = queries[q_id]
        rows = fetch_all(q["sql"])
        return {
            "intent": "payment_analytics",
            "title": q["title"],
            "answer": f"Payment method distribution from `warehouse.fact_payments` (**{q['title']}**):",
            "query_id": q_id,
            "data": rows,
            "recommendations": [],
        }

    # 6. Top Categories / Products / Sellers / States / Repeat Customers
    if any(k in msg for k in ["category", "categories", "فئات", "اقسام", "أقسام"]):
        q = queries[8]
        rows = fetch_all(q["sql"])
        return {"intent": "category_analytics", "title": q["title"], "answer": f"Top 10 categories by revenue (**{q['title']}**):", "query_id": 8, "data": rows, "recommendations": []}

    if any(k in msg for k in ["seller", "merchant", "بائعين", "تجار"]):
        q = queries[10]
        rows = fetch_all(q["sql"])
        return {"intent": "seller_analytics", "title": q["title"], "answer": f"Top 10 sellers by revenue (**{q['title']}**):", "query_id": 10, "data": rows, "recommendations": []}

    if any(k in msg for k in ["state", "region", "geography", "ولاية", "مناطق", "محافظات"]):
        q_id = 15 if req.include_synthetic else 5
        q = queries[q_id]
        rows = fetch_all(q["sql"])
        return {"intent": "state_analytics", "title": q["title"], "answer": f"Sales breakdown by customer state (**{q['title']}**):", "query_id": q_id, "data": rows, "recommendations": []}

    if any(k in msg for k in ["repeat", "retention", "spending", "عملاء", "تكرار"]):
        q = queries[16]
        rows = fetch_all(q["sql"])
        return {"intent": "customer_analytics", "title": q["title"], "answer": f"Customer spending and repeat order metrics (**{q['title']}**):", "query_id": 16, "data": rows, "recommendations": []}

    if any(k in msg for k in ["growth", "aov", "month", "trend", "نمو", "شهري", "مبيعات"]):
        q = queries[7] if req.include_synthetic else queries[1]
        rows = fetch_all(q["sql"])
        return {"intent": "monthly_sales", "title": q["title"], "answer": f"Monthly revenue and order trend (**{q['title']}**):", "query_id": q["query_id"], "data": rows[-24:], "recommendations": []}

    # Default: Executive KPI overview
    kpis = get_executive_kpis(include_synthetic=req.include_synthetic)
    s = kpis["sales"]
    d = kpis["delivery"]
    r = kpis["reviews"]
    inv = kpis["inventory"]
    summary_text = (
        f"**Warehouse Executive Summary ({kpis['scope']}):**\n"
        f"- **Total Revenue:** R$ {s['total_revenue']:,.2f} across **{s['total_orders']:,}** orders (AOV: R$ {s['avg_order_value']:,.2f})\n"
        f"- **Delivery:** Avg **{d['avg_delivery_days']} days** ({d['late_order_percentage']}% late orders)\n"
        f"- **Customer Satisfaction:** **{r['avg_review_score']} / 5.0** across {r['total_reviews']:,} reviews\n"
        f"- **Inventory Health:** **{inv['low_stock_products']:,}** low-stock items out of {inv['products_tracked']:,} tracked products."
    )
    return {
        "intent": "executive_summary",
        "title": "Executive Warehouse KPI Summary",
        "answer": summary_text,
        "query_id": None,
        "data": [s, d, r, inv],
        "recommendations": [],
    }
