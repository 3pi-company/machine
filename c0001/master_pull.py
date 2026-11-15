#!/usr/bin/env python3
"""3pi - سحب ماستر كامل لC-0001 من product.product. قراءة فقط (search_read)،
بموافقة المالك 2026-11-15. يشمل الأصناف المؤرشفة (active=False) عشان نقدر نميّزها زي C-0002.

الفرع بيكوّد أصناف جديدة ويغيّر التسعير بشكل شبه يومي (الفرع لسه جديد)، فالماستر ده لازم يتحدّث كل
دورة مزامنة (مش مرة باليوم بس) عشان الكود/الباركود الجديد يبان في اللوحة بسرعة.

المخرج: out/data/master/master_c0001.json (قائمة بيضا من الحقول بس، زي C-0002، بدون أي قيمة سرية)
"""
import json, os, sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
import juleb_web as jw

# تدرّج الحقول: نجرّب الأوسع الأول (تخصيصات جوليب العربية لو موجودة)، ولو JSON-RPC رفض حقل، ننزل للأضيق.
TIERS = [
    ["id", "product_tmpl_id", "barcode", "default_code", "name", "categ_id", "j_name_ar", "j_brand",
     "j_brand_ar", "list_price", "standard_price", "active", "sale_ok"],
    ["id", "product_tmpl_id", "barcode", "default_code", "name", "categ_id", "list_price",
     "standard_price", "active", "sale_ok"],
    ["id", "barcode", "default_code", "name", "categ_id", "list_price", "standard_price", "active"],
]


def m2o(v):
    if isinstance(v, list) and v and isinstance(v[0], int):
        return v[0] if len(v) == 1 else (v[0], v[1] if len(v) > 1 else None)
    return v


def env(k):
    return os.environ.get(f"CLIENT_C0001_JULEB_{k}", "")


def main():
    rep = {"run_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    base = env("URL")
    t = jw.Transport(base, cap=int(os.environ.get("REQ_CAP", "150")), gap=float(os.environ.get("REQ_GAP", "3")))
    s = jw.Session(t)
    rows, used_fields = None, None
    try:
        s.login(env("DB"), env("USER"), env("PASS"))
        for fields in TIERS:
            try:
                rows = s.read_all("product.product", [["active", "in", [True, False]]], fields)
                used_fields = fields
                break
            except jw.ReadOnlyStop as e:
                if "JSON-RPC" not in str(e):
                    raise
        if rows is None:
            rep["stopped"] = "كل مستويات الحقول اتردّت"
        else:
            items, archived = [], 0
            for p in rows:
                active = p.get("active", True)
                if not active:
                    archived += 1
                cat = p.get("categ_id")
                items.append({
                    "product_id": p["id"],
                    "code": (p.get("default_code") or "").strip() or None,
                    "barcode": p.get("barcode"),
                    "name_ar": p.get("j_name_ar"),
                    "name_en": p.get("name"),
                    "category": (cat[1].split(" / ")[-1] if isinstance(cat, list) and len(cat) > 1 else None),
                    "cost": p.get("standard_price") or 0,
                    "list_price": p.get("list_price") or 0,
                    "active": active,
                })
            rep["total"] = len(items)
            rep["archived"] = archived
            rep["fields_used"] = used_fields
            os.makedirs("out/data/master", exist_ok=True)
            # نفس شكل master_c0002.json بالظبط (build_app_data.build() بيقرا {"items":[...]})
            with open("out/data/master/master_c0001.json", "w", encoding="utf-8") as f:
                json.dump({"items": items}, f, ensure_ascii=False)
            rep["requests_used"] = t.used
    except jw.ReadOnlyStop as e:
        rep["stopped"] = str(e)
    except Exception as e:
        rep["stopped"] = "unexpected:" + type(e).__name__
    os.makedirs("out", exist_ok=True)
    with open("out/master_report.json", "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)
    print(json.dumps(rep, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
