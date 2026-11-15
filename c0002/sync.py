#!/usr/bin/env python3
"""3pi - دورة مزامنة واحدة لـC-0002 (قراءة فقط، GET). بتشتغل من الحلقة كل 20 دقيقة نهارًا و60 بالليل.

1) الجلسات وطرق الدفع (طلبين). المستخدمين كل ساعة.
2) الفواتير: بفلتر date_order>= (آخر مزامنة - ساعتين). لو الفلتر ما اشتغلش (رجع فواتير أقدم) بنسجّل ده ونكمّل.
   ومرة بعد نص الليل (00:10 الرياض): رؤوس كل الفواتير عشان نلقط أي إلغاء متأخر.
3) بنود ومدفوعات الفواتير الجديدة. والفاتورة اللي جلستها اتقفلت ولسه مش نهائية: نعيد سحب بنودها مرة واحدة ونعلّمها نهائية.
4) reports.json (المحرك، صفر طلبات) + data/health/sync.json (الحالة). والمطابقة الداخلية كل دورة.
الحماية: سقف طلبات للدورة (REQ_CAP=80)، و3 ثواني بين الطلبات، ووقف عند 401/403/429/5xx، ومفيش تبديل حسابات.
"""
import json, os, sys, time, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import reports

RIYADH = timezone(timedelta(hours=3))
CAP = int(os.environ.get("REQ_CAP", "80"))
GAP = float(os.environ.get("REQ_GAP", "3"))
STORE = os.environ.get("STORE_PATH", "data/rest_store/pos_store.json")
MASTER = os.environ.get("MASTER_PATH", "data/master/master_c0002.json")
OUT = os.environ.get("OUT_DIR", "out")
KEEP = {
    "order": ["id", "name", "pos_reference", "date_order", "create_date", "write_date", "state", "amount_total",
              "amount_tax", "amount_paid", "amount_return", "j_amount_untaxed", "session_id", "user_id", "employee_id",
              "company_id", "location_id", "return_order", "return_ref", "return_status", "is_hungerstation",
              "is_home_delivery", "is_on_account_return", "insurance_order", "global_discount_amount",
              "discount_total_amt_pct", "unit_sold", "payment_method", "from_medium", "on_account_payment",
              "partner_id", "insurance_id", "redeem_loyalty_points", "has_global_discount", "global_discount_type"],
    "line": ["id", "order_id", "product_id", "qty", "price_unit", "price_subtotal", "price_subtotal_incl",
             "price_subtotal_after_global_disc", "price_subtotal_incl_after_global_disc", "discount", "cost_price",
             "is_return", "returned_qty", "pharmacist", "pharmacist_commission", "p_commission_total", "write_date"],
    "payment": ["id", "pos_order_id", "amount", "payment_method_id", "payment_date", "session_id", "is_insurance"],
    "payment_method": ["id", "name", "name_ar", "is_cash_count", "is_insurance", "is_on_account", "active"],
    "user": ["id", "name", "active", "is_pharmacist", "is_seller", "company_id"],   # الاسم بقرار المالك (يظهر في لوحة العميل نفسه)
    "session": ["id", "config_id", "start_at", "stop_at", "state", "user_id"],
    "partner": ["id", "name", "display_name"],   # اسم العميل كامل، بموافقة المالك 2026-11-15 (مُفحوص: probe_partner.py)
}


class Stop(Exception):
    pass


class C:
    def __init__(self, base, key):
        self.base, self.key, self.used, self.last = base, key, 0, 0.0

    def get(self, path, params):
        if self.used >= CAP: raise Stop("cap")
        w = GAP - (time.time() - self.last)
        if w > 0: time.sleep(w)
        q = "?" + "&".join(f"{k}={urllib.request.quote(str(v), safe=',')}" for k, v in params.items())
        req = urllib.request.Request(self.base + path + q, method="GET",
                                     headers={"Authorization": f"Bearer {self.key}", "Accept": "application/json"})
        self.used += 1; self.last = time.time()
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise Stop(f"HTTP {e.code} on {path.rsplit('/', 1)[-1] if '{' not in path else path}")
        except Exception as e:
            raise Stop("network:" + type(e).__name__)


def m2o(v):
    if isinstance(v, list) and v and isinstance(v[0], int): return v[0]
    if isinstance(v, dict) and "id" in v: return v["id"]
    return v


def slim(kind, r): return {k: m2o(r.get(k)) for k in KEEP[kind] if k in r}


def fetch_all(c, path, kind, extra=None):
    rows, seen, page, total = [], set(), 1, None
    while True:
        j = c.get(path, {"limit": 1000, "page": page, **(extra or {})})
        data, meta = j.get("data") or [], j.get("meta") or {}
        if total is None:
            total = meta.get("total")
            if total is None: raise Stop(f"{kind}: no meta.total")
        if not data and len(rows) < total: raise Stop(f"{kind}: empty page before end")
        for r in data:
            if r.get("id") in seen: raise Stop(f"{kind}: duplicate id")
            seen.add(r.get("id")); rows.append(slim(kind, r))
        if len(rows) >= total or not data: break
        page += 1
    if len(rows) != total: raise Stop(f"{kind}: rows {len(rows)} != total {total}")
    return rows


def parse(s):
    if not s: return None
    try: return datetime.strptime(str(s).replace("T", " ").replace("Z", "")[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError: return None


def main():
    base = os.environ.get("CLIENT_C0002_JULEB_URL", "").strip().rstrip("/")
    if base.endswith("/web"): base = base[:-4]
    key = os.environ.get("CLIENT_C0002_JULEB_API_KEY", "")
    now = datetime.now(timezone.utc)
    store = json.load(open(STORE, encoding="utf-8")) if os.path.exists(STORE) else \
        {"version": 1, "orders": {}, "lines": {}, "payments": {}, "lines_final": [], "payment_methods": {}, "users": {}, "sessions": {}}
    meta = store.setdefault("sync_meta", {})
    h = {"task": "sync", "client": "C-0002", "run_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "result": "fail",
         "stopped": None, "requests": 0, "new_orders": 0, "finalized": 0, "filter_ok": None, "full_refresh": False}
    c = None
    try:
        if os.environ.get("PLATFORM_PAUSE", "").lower() in ("juleb", "all"):
            raise Stop("PLATFORM_PAUSE")
        if not base or not key: raise Stop("secrets missing")
        c = C(base, key)
        store["sessions"] = {str(s["id"]): s for s in fetch_all(c, "/api/v1/pos/session", "session")}
        store["payment_methods"] = {str(p["id"]): p for p in fetch_all(c, "/api/v1/pos/payment-method", "payment_method")}
        if (now - (parse(meta.get("users_at")) or datetime(2000, 1, 1, tzinfo=timezone.utc))) > timedelta(minutes=55) \
                or not any("name" in u for u in store.get("users", {}).values()):
            store["users"] = {str(u["id"]): u for u in fetch_all(c, "/api/v1/resources/res-users", "user")}
            meta["users_at"] = now.strftime("%Y-%m-%d %H:%M:%S")
        # أسماء العملاء كاملة (موافقة المالك 2026-11-15)، مرة كل 23 ساعة. خطوة معزولة: أي فشل هنا ما بيوقّفش
        # باقي المزامنة (الفواتير والبنود)، وبيتسجّل في الصحة بس.
        try:
            if (now - (parse(meta.get("partners_at")) or datetime(2000, 1, 1, tzinfo=timezone.utc))) > timedelta(hours=23):
                if c.used + 5 <= CAP:
                    partners = fetch_all(c, "/api/v1/resources/partner", "partner")
                    store["partner_names"] = {str(p["id"]): p.get("name") or p.get("display_name") for p in partners if p.get("id")}
                    meta["partners_at"] = now.strftime("%Y-%m-%d %H:%M:%S")
        except Exception as e:
            h["partners_note"] = "تعذّر تحديث أسماء العملاء: " + type(e).__name__
        last = parse(store.get("synced_at_utc")) or (now - timedelta(days=40))
        riy = now.astimezone(RIYADH)
        full = (riy.hour == 0 and riy.minute >= 10 and (now - (parse(meta.get("full_at")) or datetime(2000, 1, 1, tzinfo=timezone.utc))) > timedelta(hours=20)) \
            or not store["orders"] or store.get("schema", 1) < 2
        if full:
            orders = fetch_all(c, "/api/v1/pos/order", "order")
            meta["full_at"] = now.strftime("%Y-%m-%d %H:%M:%S"); h["full_refresh"] = True
        else:
            since = (last - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
            orders = fetch_all(c, "/api/v1/pos/order", "order", {"filter": f"date_order>={since}"})
            older = [o for o in orders if (parse(o.get("date_order")) or now) < parse(since + "Z")]
            h["filter_ok"] = not older
        known_lines = {str(l.get("order_id")) for l in store["lines"].values()}
        new = [o for o in orders if str(o["id"]) not in known_lines]
        for o in orders: store["orders"][str(o["id"])] = o
        closed = {sid for sid, s in store["sessions"].items() if s.get("stop_at")}
        final = set(store.get("lines_final", []))
        to_final = [o for o in store["orders"].values() if str(o["id"]) not in final and str(o.get("session_id")) in closed
                    and str(o["id"]) in known_lines]
        for o in new:
            oid = o["id"]
            for l in fetch_all(c, f"/api/v1/pos/order/{oid}/line", "line"): store["lines"][str(l["id"])] = l
            for p in fetch_all(c, f"/api/v1/pos/order/{oid}/payment", "payment"): store["payments"][str(p["id"])] = p
            if str(o.get("session_id")) in closed: final.add(str(oid))
        h["new_orders"] = len(new)
        for o in to_final:
            if c.used + 1 > CAP: break
            for l in fetch_all(c, f"/api/v1/pos/order/{o['id']}/line", "line"): store["lines"][str(l["id"])] = l
            final.add(str(o["id"])); h["finalized"] += 1
        store["lines_final"] = sorted(final)
        if h["full_refresh"]: store["schema"] = 2
        store["synced_at_utc"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        h["result"] = "ok"
    except Stop as e:
        h["stopped"] = str(e)
    except Exception as e:
        h["stopped"] = "internal:" + type(e).__name__
    h["requests"] = c.used if c else 0
    # المطابقة الداخلية + التقارير (صفر طلبات) حتى لو الدورة وقفت: من آخر بيانات سليمة
    from collections import Counter
    bl, bp = Counter(), Counter()
    for l in store["lines"].values(): bl[str(l.get("order_id"))] += l.get("price_subtotal_incl") or 0
    for p in store["payments"].values(): bp[str(p.get("pos_order_id"))] += p.get("amount") or 0
    live = [o for o in store["orders"].values() if o.get("state") != "cancel" and str(o["id"]) in bl]
    h["recon"] = {"orders_checked": len(live),
                  "lines_mismatch": sum(1 for o in live if abs(bl[str(o["id"])] - (o.get("amount_total") or 0)) > 0.05),
                  "payments_mismatch": sum(1 for o in live if abs(bp[str(o["id"])] - (o.get("amount_total") or 0)) > 0.05)}
    h["alert"] = bool(h["stopped"]) or h["recon"]["lines_mismatch"] > 0 or h["recon"]["payments_mismatch"] > 0
    os.makedirs(f"{OUT}/data/rest_store", exist_ok=True); os.makedirs(f"{OUT}/data/health", exist_ok=True)
    master = json.load(open(MASTER, encoding="utf-8")) if os.path.exists(MASTER) else None
    cfg = json.load(open("config.json", encoding="utf-8")) if os.path.exists("config.json") else None
    import build_app_data
    build_app_data.write(build_app_data.build(store, master, "C-0002", h), OUT)
    # حقول الصحة الموحّدة (last_success_utc / consecutive_failures / last_error) من ملف الصحة السابق
    prev = json.load(open("prev_health.json", encoding="utf-8")) if os.path.exists("prev_health.json") else {}
    if h["result"] == "ok":
        h["last_success_utc"], h["consecutive_failures"], h["last_error"] = h["run_at_utc"], 0, None
    else:
        h["last_success_utc"] = prev.get("last_success_utc") or (prev.get("run_at_utc") if prev.get("result") == "ok" else None)
        h["consecutive_failures"] = int(prev.get("consecutive_failures") or 0) + 1
        h["last_error"] = h["stopped"]
    rep = reports.build(store, master, cfg, now=now)
    rep["health"] = h

    if h["result"] == "ok":
        json.dump(store, open(f"{OUT}/data/rest_store/pos_store.json", "w"), ensure_ascii=False, separators=(",", ":"))
    json.dump(rep, open(f"{OUT}/reports.json", "w"), ensure_ascii=False)
    json.dump(h, open(f"{OUT}/data/health/sync.json", "w"), ensure_ascii=False, indent=2)
    print(json.dumps(h, ensure_ascii=False))
    return 0 if h["result"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
