#!/usr/bin/env python3
"""3pi - محرك تقارير C-0002 من المخزن المحلي (صفر طلبات لجوليب).

التعريفات (واحدة في كل الصفحات):
  * الإجمالي = amount_total (شامل الضريبة).
  * الصافي  = amount_total - amount_tax (بعد الخصم والضريبة والمرتجع). ده اللي بيتحسب بيه التارجت.
  * الفاتورة الملغية (state = cancel) بتتخزن ومش بتتحسب.
  * يوم الرياض = من 21:00 UTC لـ21:00 UTC. والأوقات في جوليب UTC (بحرف Z) [اتحققت من الشكل؛ رقم يوم من جوليب هيأكد].
  * طرق الدفع بمبالغ الدفع الفعلية. والفاتورة المدفوعة بطريقتين بتتعد في الاتنين.
الاستخدام: python reports.py <pos_store.json> [master.json] [config.json] > reports.json
"""
import json, sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

RIYADH = timezone(timedelta(hours=3))
EXCLUDED_STATES = {"cancel"}


def parse(s):
    if not s: return None
    s = str(s).replace("T", " ").replace("Z", "")[:19]
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def r2(x):
    return round(float(x or 0), 2)


def build(store, master=None, cfg=None, now=None):
    cfg = cfg or {}
    now = (now or datetime.now(timezone.utc)).astimezone(RIYADH)
    today = now.date()
    month_start = today.replace(day=1)
    yesterday = today - timedelta(days=1)
    pm = {str(k): (v.get("name_ar") or v.get("name") or f"طريقة {k}") for k, v in store.get("payment_methods", {}).items()}
    pm_en = {str(k): v.get("name") for k, v in store.get("payment_methods", {}).items()}

    orders = []
    for o in store.get("orders", {}).values():
        if o.get("state") in EXCLUDED_STATES: continue
        d = parse(o.get("date_order"))
        if not d: continue
        o = dict(o); o["_dt"] = d.astimezone(RIYADH); orders.append(o)
    pays_by_order = defaultdict(list)
    for p in store.get("payments", {}).values():
        pays_by_order[str(p.get("pos_order_id"))].append(p)
    lines_by_order = defaultdict(list)
    for l in store.get("lines", {}).values():
        lines_by_order[str(l.get("order_id"))].append(l)

    def summarize(sel):
        gross = sum(o.get("amount_total") or 0 for o in sel)
        tax = sum(o.get("amount_tax") or 0 for o in sel)
        returns = sum(o.get("amount_total") or 0 for o in sel if (o.get("amount_total") or 0) < 0)
        n = len([o for o in sel if (o.get("amount_total") or 0) >= 0])
        by_m_amt, by_m_cnt, missing_pay = Counter(), Counter(), 0
        for o in sel:
            ps = pays_by_order.get(str(o["id"]), [])
            if not ps: missing_pay += 1
            for mid in {str(p.get("payment_method_id")) for p in ps}: by_m_cnt[mid] += 1
            for p in ps: by_m_amt[str(p.get("payment_method_id"))] += p.get("amount") or 0
        return {"invoices": n, "gross": r2(gross), "tax": r2(tax), "net": r2(gross - tax), "returns": r2(returns),
                "avg_invoice": r2(gross / n) if n else 0,
                "by_method": [{"method": pm.get(m, m), "method_en": pm_en.get(m), "count": by_m_cnt[m], "amount": r2(by_m_amt[m])}
                              for m in sorted(by_m_amt, key=lambda k: -by_m_amt[k])],
                "invoices_without_payment_rows": missing_pay}

    sel_today = [o for o in orders if o["_dt"].date() == today]
    sel_mtd = [o for o in orders if month_start <= o["_dt"].date() <= today]
    sel_to_yday = [o for o in orders if month_start <= o["_dt"].date() <= yesterday]
    last_dt = max((o["_dt"] for o in orders), default=None)

    # 2) تقرير طرق الدفع لحد أمس: نسب
    s2 = summarize(sel_to_yday)
    tot_cnt = sum(x["count"] for x in s2["by_method"]) or 1
    tot_amt = sum(x["amount"] for x in s2["by_method"]) or 1
    for x in s2["by_method"]:
        x["count_pct"] = round(100 * x["count"] / tot_cnt, 1)
        x["amount_pct"] = round(100 * x["amount"] / tot_amt, 1)

    # 6) مبيعات الساعة: المتوسط مقسوم على عدد الأيام اللي الفرع كان مفتوح فيها الساعة دي (من الجلسات)
    open_days = defaultdict(set)
    sessions_ok = 0
    for s in store.get("sessions", {}).values():
        a, b = parse(s.get("start_at")), parse(s.get("stop_at")) or datetime.now(timezone.utc)
        if not a: continue
        sessions_ok += 1
        t = a.astimezone(RIYADH).replace(minute=0, second=0, microsecond=0)
        b = b.astimezone(RIYADH)
        while t <= b:
            if month_start <= t.date() <= today: open_days[t.hour].add(t.date())
            t += timedelta(hours=1)
    hour_amt, hour_cnt = Counter(), Counter()
    for o in sel_mtd:
        hour_amt[o["_dt"].hour] += o.get("amount_total") or 0
        hour_cnt[o["_dt"].hour] += 1
    hours = []
    for h in range(24):
        days_open = len(open_days.get(h, ()))
        hours.append({"hour": h, "total": r2(hour_amt[h]), "invoices": hour_cnt[h], "days_open": days_open,
                      "avg_per_open_day": r2(hour_amt[h] / days_open) if days_open else None})

    # 5) تحذير الربحية: من الماستر (سعر البيع قبل الضريبة مقابل التكلفة). بيانات العميل نفسه بس.
    prof = {"source": None, "margin_le_0": [], "margin_lt_5": [], "checked": 0}
    if master:
        prof["source"] = "master (list_price vs standard_price)"
        for it in master.get("items", []):
            price, cost = it.get("list_price") or 0, it.get("cost") or 0
            if price <= 0 or cost <= 0 or not it.get("active", True): continue
            prof["checked"] += 1
            m = (price - cost) / price * 100
            row = {"code": it.get("code"), "barcode": it.get("barcode"), "name": it.get("name_ar") or it.get("name_en"),
                   "price": r2(price), "cost": r2(cost), "margin_pct": round(m, 1)}
            if m <= 0: prof["margin_le_0"].append(row)
            elif m < 5: prof["margin_lt_5"].append(row)
        for k in ("margin_le_0", "margin_lt_5"):
            prof[k].sort(key=lambda r: r["margin_pct"])

    # 7) التارجت
    tgt = None
    target = (cfg.get("targets") or {}).get(today.strftime("%Y-%m"))
    if target:
        achieved = summarize(sel_mtd)["net"]
        import calendar
        dim = calendar.monthrange(today.year, today.month)[1]
        days_left = dim - today.day
        days_done = today.day
        tgt = {"month": today.strftime("%Y-%m"), "target": r2(target), "achieved_net": achieved,
               "remaining": r2(max(0, target - achieved)), "achieved_pct": round(100 * achieved / target, 1),
               "required_per_day": r2(max(0, target - achieved) / days_left) if days_left else None,
               "forecast_month_end": r2(achieved / days_done * dim) if days_done else None}
        tgt["forecast_pct"] = round(100 * tgt["forecast_month_end"] / target, 1) if tgt["forecast_month_end"] else None

    # الفترات: اليوم، وأمس، وأول امبارح (للمقارنة)، والشهر
    day_before = yesterday - timedelta(days=1)
    sel_yday = [o for o in orders if o["_dt"].date() == yesterday]
    sel_dbefore = [o for o in orders if o["_dt"].date() == day_before]
    def delta(a, b):
        return round((a - b) / b * 100, 1) if b else None
    periods = {}
    for key, sel, prev in (("today", sel_today, sel_yday), ("yesterday", sel_yday, sel_dbefore), ("month", sel_mtd, None)):
        sm = summarize(sel)
        if prev is not None:
            pv = summarize(prev)
            sm["delta"] = {k: delta(sm[k], pv[k]) for k in ("gross", "net", "invoices", "avg_invoice")}
        periods[key] = sm
    # الساعة: اليوم وأمس ومتوسط الشهر لكل يوم مفتوح
    def by_hour(sel):
        c = Counter()
        for o in sel: c[o["_dt"].hour] += o.get("amount_total") or 0
        return [r2(c[h]) for h in range(24)]
    hourly_cmp = {"today": by_hour(sel_today), "yesterday": by_hour(sel_yday),
                  "month_avg_per_open_day": [h["avg_per_open_day"] for h in hours]}
    # الصيادلة/المستخدمين برموز ثابتة (P1..Pn) — الأسماء ما بتدخلش هنا خالص
    uids = sorted({o.get("user_id") for o in orders if o.get("user_id") is not None}, key=lambda x: (str(type(x)), x))
    code = {u: f"P{i+1}" for i, u in enumerate(uids)}
    by_user = {}
    for key, sel in (("today", sel_today), ("yesterday", sel_yday), ("month", sel_mtd)):
        agg = defaultdict(lambda: [0, 0.0])
        for o in sel:
            if (o.get("amount_total") or 0) < 0: continue
            a = agg[code.get(o.get("user_id"), "P?")]; a[0] += 1; a[1] += o.get("amount_total") or 0
        by_user[key] = sorted([{"user": k, "invoices": v[0], "avg": r2(v[1] / v[0]) if v[0] else 0, "total": r2(v[1])}
                               for k, v in agg.items()], key=lambda x: -x["total"])

    return {
        "client": (cfg or {}).get("client", "C-0002"),
        "status": "معتمد بقواعد جوليب (UTC، ويوم الرياض من 21:00 UTC، وكل الحالات ما عدا cancel)",
        "generated_at_riyadh": now.strftime("%Y-%m-%d %H:%M"),
        "data_as_of_utc": store.get("synced_at_utc"),
        "last_invoice_riyadh": last_dt.strftime("%Y-%m-%d %H:%M") if last_dt else None,
        "coverage": {"orders": len(orders), "lines": len(store.get("lines", {})), "payments": len(store.get("payments", {})),
                     "lines_with_cost": sum(1 for l in store.get("lines", {}).values() if l.get("cost_price"))},
        "page1_now": {"today": summarize(sel_today), "month_to_date": summarize(sel_mtd)},
        "page2_payments_to_yesterday": {"from": month_start.isoformat(), "to": yesterday.isoformat(), **s2,
                                        "note": "الفاتورة المدفوعة بطريقتين بتتعد في الاتنين، فمجموع العدد ممكن يزيد عن عدد الفواتير"},
        "page3_negative_stock": {"available": False, "reason": "الرصيد مش متوصل لسه (مفيش مسار REST، وBranch Stock متأجل بقرار المالك)"},
        "page4_platforms": {"status": "جاري إعادة الربط - في انتظار الربط"},
        "page5_profitability": prof,
        "page6_hourly": {"hours": hours, "sessions_used": sessions_ok,
                         "adjusted": sessions_ok > 0,
                         "note": None if sessions_ok else "غير مُعدَّل بساعات الدوام"},
        "page7_target": tgt or {"status": "لم يُحدَّد تارجت للشهر"},
        "periods": periods,
        "hourly_compare": hourly_cmp,
        "by_user": by_user,
    }


if __name__ == "__main__":
    store = json.load(open(sys.argv[1], encoding="utf-8"))
    master = json.load(open(sys.argv[2], encoding="utf-8")) if len(sys.argv) > 2 and sys.argv[2] != "-" else None
    cfg = json.load(open(sys.argv[3], encoding="utf-8")) if len(sys.argv) > 3 else None
    print(json.dumps(build(store, master, cfg), ensure_ascii=False, indent=2))
