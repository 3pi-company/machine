#!/usr/bin/env python3
"""3pi - رصيد فرع علي الصياد (C-0001/vaccine) من branch.stock.page (جلسة ويب، قراءة فقط عبر juleb_web.py
المقيّد أصلًا بـALLOWED_MODELS). بموافقة المالك 2026-11-15 (نفس نمط C-0002).
يكتب:
  out/data/store/stock.json   {qty: {pid: qty}, negative: [...], archived_negative: [...]}
  out/data/health/stock.json  last_success_utc / consecutive_failures / last_error (بدون أي قيمة عميل)
"""
import json, os, sys
from datetime import datetime, timezone
import juleb_web as jw

MODEL = "branch.stock.page"
QTY_PREF = ["qty_available", "quantity", "qty", "stock_qty", "available_qty", "balance", "qty_on_hand", "on_hand"]


def pick_fields(sample):
    keys = list(sample.keys())
    prod = next((k for k in ("product_id", "product_product_id", "product_tmpl_id", "product") if k in keys), None)
    num = [k for k in keys if isinstance(sample.get(k), (int, float)) and not isinstance(sample.get(k), bool) and k != "id"]
    qty = next((k for k in QTY_PREF if k in num), None) or next((k for k in num if "qty" in k or "quant" in k or "stock" in k), None)
    act = next((k for k in ("active", "product_active", "is_active") if k in keys), None)
    return prod, qty, act, sorted(keys)


def m2o(v):
    return v[0] if isinstance(v, list) and v else v


def main():
    env = lambda k: os.environ.get(f"CLIENT_C0001_JULEB_{k}", "").strip()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    prev = json.load(open("prev_stock_health.json", encoding="utf-8")) if os.path.exists("prev_stock_health.json") else {}
    try:  # الرصيد كل 60 دقيقة بس
        last = datetime.strptime(str(prev.get("run_at_utc")), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if (datetime.now(timezone.utc) - last).total_seconds() < 55 * 60 and not os.environ.get("STOCK_FORCE"):
            print("stock: skipped (آخر تشغيل من أقل من ساعة)"); return 0
    except ValueError:
        pass
    h = {"task": "stock", "client": "C-0001", "run_at_utc": now, "result": "fail", "stopped": None}
    os.makedirs("out/data/store", exist_ok=True); os.makedirs("out/data/health", exist_ok=True)
    t = None
    try:
        if os.environ.get("PLATFORM_PAUSE", "").lower() in ("juleb", "all"):
            raise jw.ReadOnlyStop("PLATFORM_PAUSE")
        if not all(env(k) for k in ("URL", "DB", "USER", "PASS")):
            raise jw.ReadOnlyStop("أسرار الدخول مش موجودة (DB/USER/PASS)")
        t = jw.Transport(env("URL"), cap=int(os.environ.get("REQ_CAP", "40")), gap=float(os.environ.get("REQ_GAP", "3")))
        s = jw.Session(t)
        h["login"] = s.login(env("DB"), env("USER"), env("PASS"))
        first = s.search_read(MODEL, [], [], limit=1)
        recs = (first or {}).get("records") or []
        if not recs:
            raise jw.ReadOnlyStop("branch.stock.page فاضي")
        prod, qty, act, keys = pick_fields(recs[0])
        h["fields_seen"], h["fields_used"] = keys, {"product": prod, "qty": qty, "active": act}
        if not prod or not qty:
            raise jw.ReadOnlyStop("مش لاقي حقل الصنف أو الكمية")
        rows = s.read_all(MODEL, [], [f for f in ("id", prod, qty, act) if f], page=2000)
        master = json.load(open("data/master/master_c0001.json", encoding="utf-8")) if os.path.exists("data/master/master_c0001.json") else {}
        mi = {str(it.get("product_id")): it for it in master.get("items", [])}
        tot, archived = {}, set()
        for r in rows:
            pid = str(m2o(r.get(prod)))
            it = mi.get(pid)
            if (act and r.get(act) is False) or (it is not None and it.get("active") is False):
                archived.add(pid)
            tot[pid] = tot.get(pid, 0.0) + float(r.get(qty) or 0)
        prev_n = int(prev.get("rows") or 0)
        if prev_n and len(rows) < prev_n * 0.9:
            raise jw.ReadOnlyStop(f"العدد نزل فجأة ({len(rows)} بدل {prev_n})")
        neg, arch_neg = [], []
        for pid, q in tot.items():
            it = mi.get(pid, {})
            if q < 0 and pid in archived:
                arch_neg.append({"pid": pid, "qty": round(q, 3), "n": it.get("name_ar") or it.get("name_en")})
            elif q < 0:
                neg.append({"pid": pid, "code": str(it.get("code") or "").strip(), "bc": it.get("barcode"),
                            "n": it.get("name_ar") or it.get("name_en") or f"صنف #{pid}", "cat": it.get("category") or "—",
                            "qty": round(q, 3), "cost": it.get("cost"), "price": it.get("list_price")})
        # قيمة المخزون الكلي: Σ(الرصيد الموجب × التكلفة الحالية) لكل صنف له تكلفة معروفة، بالفئة (بقرار المالك 2026-11-15).
        by_cat, priced, unpriced = {}, 0, 0
        for pid, q in tot.items():
            if q <= 0 or pid in archived:
                continue
            it = mi.get(pid) or {}
            cost = it.get("cost")
            if cost in (None, 0, False):
                unpriced += 1
                continue
            priced += 1
            cat = str(it.get("category") or "—").split(" / ")[-1]
            by_cat[cat] = round(by_cat.get(cat, 0.0) + q * cost, 2)
        valuation = {"total": round(sum(by_cat.values()), 2), "by_category": dict(sorted(by_cat.items(), key=lambda x: -x[1])),
                     "items_priced": priced, "items_unpriced": unpriced}
        json.dump({"as_of_utc": now, "qty": {k: round(v, 3) for k, v in tot.items()}, "negative": sorted(neg, key=lambda x: x["qty"]),
                   "archived_negative": sorted(arch_neg, key=lambda x: x["qty"]), "valuation": valuation},
                  open("out/data/store/stock.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
        h.update(result="ok", rows=len(rows), products=len(tot), negative=len(neg), archived_negative=len(arch_neg))
    except (jw.ReadOnlyStop, jw.ReadOnlyViolation) as e:
        h["stopped"] = f"{type(e).__name__}: {e}"
    except Exception as e:
        h["stopped"] = "internal:" + type(e).__name__
    h["requests"] = t.used if t else 0
    if h["result"] == "ok":
        h["last_success_utc"], h["consecutive_failures"], h["last_error"] = now, 0, None
    else:
        h["last_success_utc"] = prev.get("last_success_utc")
        h["consecutive_failures"] = int(prev.get("consecutive_failures") or 0) + 1
        h["last_error"] = h["stopped"]
    json.dump(h, open("out/data/health/stock.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k, v in h.items() if k != "fields_seen"}, ensure_ascii=False))
    return 0 if h["result"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
