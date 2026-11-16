#!/usr/bin/env python3
"""3pi - أول سحب مبيعات C-0001 بجلسة ويب (قراءة فقط عبر juleb_web).

من أول الشهر بتوقيت الرياض (21:00 UTC آخر يوم في الشهر اللي فات) لحد دلوقتي.
الفواتير، والبنود، والمدفوعات، والجلسات، وطرق الدفع. والحقول المرتبطة بتتخزن برقمها بس (من غير أسماء).
المخرجات: out/data/rest_store/pos_store.json (فرع data) و out/probe_report.json (أعداد بس).
"""
import json, os, sys, time
from collections import Counter
from datetime import datetime, timedelta, timezone
import juleb_web as jw
import reports

RIYADH = timezone(timedelta(hours=3))
F = {
    "pos.order": ["id", "name", "date_order", "state", "amount_total", "amount_tax", "amount_paid", "amount_return",
                  "session_id", "user_id", "company_id"],
    "pos.order.line": ["id", "order_id", "product_id", "qty", "price_unit", "price_subtotal", "price_subtotal_incl", "discount"],
    "pos.order.line+": ["cost_price", "pharmacist_commission"],   # حقول جوليب الإضافية (لو مش موجودة بنكمّل من غيرها)
    "pos.payment": ["id", "pos_order_id", "amount", "payment_method_id", "payment_date", "session_id"],
    "pos.session": ["id", "config_id", "start_at", "stop_at", "state"],
    "pos.payment.method": ["id", "name"],
    # حقول إضافية لصفحة العملاء (لو جوليب رفض أي منها بنكمّل بالأقل)
    "pos.order+": [["partner_id", "insurance_order", "on_account_payment", "redeem_loyalty_points", "has_global_discount",
                    "global_discount_amount", "return_ref"], ["partner_id"], []],
    "product.product": ["id", "default_code", "barcode", "categ_id", "standard_price", "lst_price"],
}


def m2o(v):
    return v[0] if isinstance(v, list) and v and isinstance(v[0], int) else v


def slim(rows, keep_names=False):
    return {str(r["id"]): {k: (v if keep_names else m2o(v)) for k, v in r.items()} for r in rows}


def main():
    env = lambda k: os.environ.get(f"CLIENT_C0001_JULEB_{k}", "")
    rep = {"step": "c0001_first_pull", "stopped": None, "saved": False, "checks": []}
    if not all(env(k) for k in ("URL", "DB", "USER", "PASS")):
        rep["stopped"] = "الأسرار مش موجودة (بالاسم)"; return out(rep, None, None)
    t = jw.Transport(env("URL"), cap=int(os.environ.get("REQ_CAP", "200")), gap=float(os.environ.get("REQ_GAP", "3")))
    s = jw.Session(t)
    now = datetime.now(timezone.utc)
    # قرار المالك 2026-11-15: تحميل كل تاريخ الفرع (الصيدلية فتحت قبل حوالي 20 يوم). بدل أول الشهر بس، بنرجع BACKFILL_DAYS
    # يوم للخلف (افتراضيًا 60، يغطي الافتتاح براحة). كل تشغيل بيعيد سحب الفترة كلها، فالتكلفة اللي بتكمل بعد قفل الجلسة
    # بتتحدّث لوحدها. لما الفرع يكبر وعدد الطلبات يزيد، نرجّع الرقم ده لأول الشهر بس (موافقة المالك الأولى).
    backfill_days = int(os.environ.get("BACKFILL_DAYS", "60"))
    start = min(
        (now.astimezone(RIYADH).replace(day=1, hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)).astimezone(timezone.utc),
        now - timedelta(days=backfill_days),
    )
    store = None
    try:
        rep["login"] = s.login(env("DB"), env("USER"), env("PASS"))
        pms = s.read_all("pos.payment.method", [], F["pos.payment.method"])
        sessions = s.read_all("pos.session", [["start_at", ">=", (start - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")]], F["pos.session"])
        dom = [["date_order", ">=", start.strftime("%Y-%m-%d %H:%M:%S")]]
        for extra in F["pos.order+"]:
            try:
                orders = s.read_all("pos.order", dom, F["pos.order"] + extra)
                rep["order_extra_fields"] = extra
                break
            except jw.ReadOnlyStop as e:
                if "JSON-RPC" not in str(e) or not extra:
                    raise
        # أسماء الصيادلة (بقرار المالك) من [id, name] في user_id - من غير أي طلب زيادة
        # أسماء العملاء زي ما هي في جوليب (طلب المالك، لوحة العميل نفسه بس) من [id, name] في partner_id - من غير طلب زيادة
        partner_names = {str(o["partner_id"][0]): o["partner_id"][1] for o in orders
                         if isinstance(o.get("partner_id"), list) and len(o["partner_id"]) > 1}
        user_names = {str(o["user_id"][0]): o["user_id"][1] for o in orders if isinstance(o.get("user_id"), list) and len(o["user_id"]) > 1}
        ids = [o["id"] for o in orders]
        lines, pays, line_fields = [], [], F["pos.order.line"] + F["pos.order.line+"]
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            try:
                lines += s.read_all("pos.order.line", [["order_id", "in", chunk]], line_fields)
            except jw.ReadOnlyStop as e:
                if "JSON-RPC" in str(e) and line_fields != F["pos.order.line"]:
                    rep["note_line_fields"] = "حقول جوليب الإضافية مش متاحة، والسحب كمّل من غيرها"
                    line_fields = F["pos.order.line"]
                    lines += s.read_all("pos.order.line", [["order_id", "in", chunk]], line_fields)
                else:
                    raise
            pays += s.read_all("pos.payment", [["pos_order_id", "in", chunk]], F["pos.payment"])
        prod_names = {str(l["product_id"][0]): l["product_id"][1] for l in lines if isinstance(l.get("product_id"), list) and len(l["product_id"]) > 1}
        products = {}
        try:  # الفئة والتكلفة الحالية للأصناف اللي اتباعت بس (طلب لكل 500 صنف)
            pids = sorted({int(k) for k in prod_names})
            for i in range(0, len(pids), 500):
                for p in s.read_all("product.product", [["id", "in", pids[i:i + 500]]], F["product.product"]):
                    c = p.get("categ_id")
                    products[str(p["id"])] = {"code": p.get("default_code"), "bc": p.get("barcode"),
                                              "cat": (c[1].split(" / ")[-1] if isinstance(c, list) and len(c) > 1 else "—"),
                                              "cost": p.get("standard_price") or 0, "price": p.get("lst_price") or 0}
        except jw.ReadOnlyStop as e:
            rep["note_products"] = "تفاصيل الأصناف مش متاحة: " + str(e)[:60]
        for k, n in prod_names.items():
            products.setdefault(k, {"cat": "—", "cost": 0, "price": 0})["n"] = n
        rep["checks"] = [{"model": m, "rows": n} for m, n in
                         [("pos.payment.method", len(pms)), ("pos.session", len(sessions)), ("pos.order", len(orders)),
                          ("pos.order.line", len(lines)), ("pos.payment", len(pays))]]
        st = Counter(o.get("state") for o in orders)
        rep["states"] = dict(st)
        live = [o for o in orders if o.get("state") != "cancel"]
        by_l, by_p = Counter(), Counter()
        for l in lines: by_l[m2o(l["order_id"])] += l.get("price_subtotal_incl") or 0
        for p in pays: by_p[m2o(p["pos_order_id"])] += p.get("amount") or 0
        rep["recon"] = {"orders": len(live),
                        "lines_sum_matches_total": sum(1 for o in live if abs(by_l[o["id"]] - (o.get("amount_total") or 0)) <= 0.05),
                        "payments_sum_matches_total": sum(1 for o in live if abs(by_p[o["id"]] - (o.get("amount_total") or 0)) <= 0.05)}
        days = Counter(datetime.strptime(o["date_order"][:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).astimezone(RIYADH).date().isoformat() for o in live)
        rep["orders_per_riyadh_day"] = dict(sorted(days.items()))
        pmn = {p["id"]: p.get("name") for p in pms}
        rep["payments_by_method_count"] = dict(Counter(pmn.get(m2o(p["payment_method_id"]), "?") for p in pays))
        rep["companies"] = rep["login"]["companies"]
        store = {"version": 1, "source": "web_session", "orders": slim(orders), "lines": slim(lines), "payments": slim(pays),
                 "payment_methods": {str(p["id"]): {"id": p["id"], "name": p.get("name")} for p in pms},
                 "sessions": slim(sessions), "lines_final": [], "synced_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "users": {k: {"id": int(k), "name": v} for k, v in user_names.items()}, "products_info": products, "partner_names": partner_names}
        rep["saved"] = True
    except (jw.ReadOnlyStop, jw.ReadOnlyViolation) as e:
        rep["stopped"] = f"{type(e).__name__}: {e}"
    except Exception as e:
        rep["stopped"] = "خطأ داخلي: " + type(e).__name__
    rep["requests_used"] = t.used
    rep["task"], rep["client"], rep["run_at_utc"] = "sync", "C-0001", now.strftime("%Y-%m-%dT%H:%M:%SZ")
    rep["result"] = "ok" if rep["saved"] else "fail"
    rep["alert"] = (not rep["saved"]) or bool(rep.get("recon") and (rep["recon"]["lines_sum_matches_total"] != rep["recon"]["orders"]
                                                                    or rep["recon"]["payments_sum_matches_total"] != rep["recon"]["orders"]))
    if store is None and os.path.exists("data/rest_store/pos_store.json"):  # آخر بيانات سليمة تفضل ظاهرة
        store_for_reports = json.load(open("data/rest_store/pos_store.json", encoding="utf-8"))
    else:
        store_for_reports = store
    os.makedirs("out/data/health", exist_ok=True)
    prev = json.load(open("prev_health.json", encoding="utf-8")) if os.path.exists("prev_health.json") else {}
    if rep["result"] == "ok":
        rep["last_success_utc"], rep["consecutive_failures"], rep["last_error"] = rep["run_at_utc"], 0, None
    else:
        rep["last_success_utc"] = prev.get("last_success_utc") or (prev.get("run_at_utc") if prev.get("result") == "ok" else None)
        rep["consecutive_failures"] = int(prev.get("consecutive_failures") or 0) + 1
        rep["last_error"] = rep["stopped"]
    json.dump(rep, open("out/data/health/sync.json", "w"), ensure_ascii=False, indent=2)
    # ماستر كامل (code/barcode/تصنيف/تكلفة) بموافقة المالك 2026-11-15، لو متوفر من master_pull.py؛ غيره نرجع للسلوك القديم (None)
    master = None
    for p in ("data/master/master_c0001.json", "out/data/master/master_c0001.json"):
        if os.path.exists(p):
            try:
                master = json.load(open(p, encoding="utf-8"))
            except Exception:
                master = None
            break
    if store_for_reports:
        import build_app_data
        # الماستر هنا كتالوج جوليب العام (كل الصيدليات)، مش خاص بفرع C-0001؛ فنقصر تنبيه الهامش على الأصناف
        # اللي اتباعت فعلًا أو موجودة في رصيد الفرع بس (relevant_pids) عشان منغرقش في آلاف الأصناف اللي
        # الفرع ده معندوش علاقة بيها (موافقة المالك 2026-11-15، سحب الماستر لـC-0001).
        relevant = {str(m2o(l.get("product_id"))) for l in store_for_reports.get("lines", {}).values()}
        for p in ("data/store/stock.json", "out/data/store/stock.json"):
            if os.path.exists(p):
                try:
                    relevant |= set(json.load(open(p, encoding="utf-8")).get("qty", {}).keys())
                except Exception:
                    pass
                break
        build_app_data.write(build_app_data.build(store_for_reports, master, "C-0001", rep, relevant_pids=relevant), "out")
    if store_for_reports:
        r = reports.build(store_for_reports, master, {"client": "C-0001"}, now=now)
        r["health"] = {k: rep.get(k) for k in ("result", "stopped", "requests_used", "recon", "alert", "run_at_utc")}
        json.dump(r, open("out/reports.json", "w"), ensure_ascii=False)
    return out(rep, t, store)


def out(rep, t, store):
    os.makedirs("out/data/rest_store", exist_ok=True)
    json.dump(rep, open("out/probe_report.json", "w"), ensure_ascii=False, indent=2)
    if store is not None:
        json.dump(store, open("out/data/rest_store/pos_store.json", "w"), ensure_ascii=False, separators=(",", ":"))
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
