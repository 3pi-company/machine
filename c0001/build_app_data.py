#!/usr/bin/env python3
"""3pi - المخزن التراكمي اللي اللوحة بتقراه (data/store/) من مخزن المزامنة والماستر. قايمة بيضا بس.
مفيش: ملاحظات، ولا روشتات، ولا أسماء أو موبايلات عملاء (partner_id رقم بس + النوع + أول ظهور)، ولا أسرار.
الأسماء الوحيدة: أسماء مستخدمي جوليب (الصيادلة) بقرار المالك، وأسماء طرق الدفع، وأسماء الأصناف.
التقسيم: orders/lines/pays حسب شهر الرياض (YYYY-MM)، والباقي ملفات صغيرة."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone

RIYADH = timezone(timedelta(hours=3))
O = ["id", "name", "date_order", "state", "amount_total", "amount_tax", "session_id", "user_id", "company_id", "partner_id",
     "insurance_order", "insurance_id", "on_account_payment", "redeem_loyalty_points", "has_global_discount",
     "global_discount_type", "global_discount_amount", "return_ref", "return_order"]
L = ["order_id", "product_id", "qty", "price_unit", "discount", "price_subtotal", "price_subtotal_incl",
     "price_subtotal_after_global_disc", "cost_price", "pharmacist_commission"]
P = ["pos_order_id", "payment_method_id", "amount", "is_insurance"]
# أسماء عربي لطرق الدفع لما جوليب ما يرجّعش name_ar
AR = {"cash": "نقدي", "mada": "مدى", "visa": "فيزا", "mastercard": "ماستركارد", "master card": "ماستركارد", "bank": "حوالة بنك",
      "on account": "آجل", "pay via terminal": "الدفع عن طريق الربط", "gccnet": "الشبكة الخليجية", "american express": "أمريكان إكسبريس",
      "amex": "أمريكان إكسبريس", "stc pay": "STC Pay", "tabby": "تابي", "tamara": "تمارا"}


def _m2o(v):
    return v[0] if isinstance(v, (list, tuple)) and v else v


def _rday(s):
    try:
        d = datetime.strptime(str(s).replace("T", " ").replace("Z", "")[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        r = d.astimezone(RIYADH)
        return r.strftime("%Y-%m-%d"), r.hour
    except Exception:
        return None, None


def build(store, master, client, health, relevant_pids=None):
    """بيرجّع {مسار نسبي: محتوى} تحت data/store/.
    relevant_pids: لو الماستر كتالوج عام مش خاص بالفرع (زي C-0001: منتجات search_read بترجع كل منتجات جوليب
    مش بس المسحوبة لهذا الفرع)، بنقصر تنبيه الهامش على الأصناف اللي اتباعت أو موجودة في رصيد الفرع بس،
    عشان ما يتجمّعش آلاف التنبيهات لمنتجات الفرع ده أصلًا معندوش علاقة بيها."""
    files = defaultdict(list)
    month_of, first_seen = {}, {}
    for o in store.get("orders", {}).values():
        if o.get("state") == "cancel":
            continue
        day, hour = _rday(o.get("date_order"))
        if not day:
            continue
        r = {k: _m2o(o.get(k)) for k in O if k in o}
        r["day"], r["hour"] = day, hour
        files[f"orders/{day[:7]}.json"].append(r)
        month_of[str(o["id"])] = day[:7]
        pid = r.get("partner_id")
        if pid not in (None, False, 0):
            first_seen[pid] = min(first_seen.get(pid, day), day)
    for l in store.get("lines", {}).values():
        m = month_of.get(str(_m2o(l.get("order_id"))))
        if m:
            files[f"lines/{m}.json"].append({k: _m2o(l.get(k)) for k in L if k in l})
    for p in store.get("payments", {}).values():
        m = month_of.get(str(_m2o(p.get("pos_order_id"))))
        if m:
            files[f"pays/{m}.json"].append({k: _m2o(p.get(k)) for k in P if k in p})
    used = {str(_m2o(l.get("product_id"))) for l in store.get("lines", {}).values()}
    prods, alert = {}, []
    for it in (master or {}).get("items", []):
        pid = str(it.get("product_id"))
        p, c = it.get("list_price") or 0, it.get("cost") or 0
        m = (p - c) / p * 100 if p > 0 and c > 0 else None
        cat = str(it.get("category") or "—").split(" / ")[-1]
        name = it.get("name_ar") or it.get("name_en")
        if pid in used:
            prods[pid] = {"code": it.get("code"), "n": name, "cat": cat, "cost": c, "price": p, "bc": it.get("barcode"),
                          "tax": it.get("taxes") or it.get("tax")}
        if m is not None and m < 5 and it.get("active", True) and (relevant_pids is None or pid in relevant_pids):
            alert.append({"pid": pid, "code": it.get("code"), "bc": it.get("barcode"), "n": name, "cat": cat,
                          "price": round(p, 2), "cost": round(c, 2), "m": round(m, 1)})
    for pid, info in (store.get("products_info") or {}).items():   # عملاء الجلسة (من غير ماستر): من بيانات الأصناف اللي اتباعت
        if pid in used and pid not in prods:
            prods[pid] = {"code": info.get("code"), "n": info.get("n") or f"صنف #{pid}", "cat": info.get("cat") or "—",
                          "cost": info.get("cost") or 0, "price": info.get("price") or 0, "bc": info.get("bc"), "tax": None}
    pm = store.get("payment_methods", {})
    out = dict(files)
    out.update({
        "meta.json": {"client": client, "synced_at_utc": store.get("synced_at_utc"), "lines_final": store.get("lines_final", []),
                      "months": sorted({k.split("/")[1][:7] for k in files if k.startswith("orders/")})},
        "methods.json": {k: {"name": v.get("name_ar") or AR.get(str(v.get("name") or "").strip().lower()) or v.get("name"), "en": v.get("name"),
                             "insurance": bool(v.get("is_insurance")),
                             "on_account": bool(v.get("is_on_account")) or str(v.get("name") or "").strip().lower() == "on account"}
                         for k, v in pm.items()},
        "users.json": {k: v.get("name") for k, v in store.get("users", {}).items() if v.get("name")},
        "sessions.json": [{k: _m2o(s.get(k)) for k in ("id", "start_at", "stop_at", "user_id", "state")} for s in store.get("sessions", {}).values()],
        "partners.json": {str(k): {"type": "registered", "first_seen": v, **({"name": (store.get("partner_names") or {}).get(str(k))}
                                                                              if (store.get("partner_names") or {}).get(str(k)) else {})}
                          for k, v in first_seen.items()},
        "products.json": prods,
        "margin_alert.json": sorted(alert, key=lambda x: x["m"]),
    })
    its = [i for i in (master or {}).get("items", []) if i.get("active", True)]
    if its:   # عدد الأصناف في ماستر العميل (طلب المسؤول 2026-11-18): كارت جنب قيمة المخزون
        out["master_stats.json"] = {"total": len(its), "with_barcode": sum(1 for i in its if i.get("barcode")),
                                    "drugs": sum(1 for i in its if i.get("category") == "Drugs")}
    return out


def write(files, root):
    import json, os
    for rel, obj in files.items():
        path = os.path.join(root, "data", "store", rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
