from datetime import datetime, timezone
import reports

NOW = datetime(2026, 11, 14, 20, 0, tzinfo=timezone.utc)  # 23:00 الرياض يوم 14


def store():
    return {
        "synced_at_utc": "2026-11-14T20:00:00Z",
        "payment_methods": {"1": {"name": "Cash"}, "2": {"name": "Mada"}},
        "orders": {
            # 22:30 UTC يوم 13 = 01:30 الرياض يوم 14 → لازم يتحسب يوم 14
            "1": {"id": 1, "date_order": "2026-11-13T22:30:00.000Z", "state": "paid", "amount_total": 115.0, "amount_tax": 15.0},
            # 20:59 UTC يوم 13 = 23:59 الرياض يوم 13
            "2": {"id": 2, "date_order": "2026-11-13T20:59:00.000Z", "state": "done", "amount_total": 50.0, "amount_tax": 0.0},
            # ملغية: ما تتحسبش
            "3": {"id": 3, "date_order": "2026-11-14T10:00:00.000Z", "state": "cancel", "amount_total": 999.0, "amount_tax": 0.0},
        },
        "payments": {
            "a": {"pos_order_id": 1, "payment_method_id": 1, "amount": 15.0},
            "b": {"pos_order_id": 1, "payment_method_id": 2, "amount": 100.0},
            "c": {"pos_order_id": 2, "payment_method_id": 2, "amount": 50.0},
        },
        "lines": {},
        # جلسة يوم 13 من 05:00 لـ21:00 UTC، وجلسة يوم 14 من 05:00 لـ20:00 UTC
        "sessions": {"s1": {"start_at": "2026-11-13T05:00:00Z", "stop_at": "2026-11-13T21:00:00Z"},
                     "s2": {"start_at": "2026-11-14T05:00:00Z", "stop_at": "2026-11-14T20:00:00Z"}},
    }


def test_riyadh_day_and_cancel():
    r = reports.build(store(), now=NOW)
    t = r["page1_now"]["today"]
    assert t["invoices"] == 1 and t["gross"] == 115.0 and t["net"] == 100.0
    assert r["page1_now"]["month_to_date"]["invoices"] == 2  # الملغية مستبعدة


def test_split_payment_counted_in_both_methods():
    r = reports.build(store(), now=NOW)
    m = {x["method_en"]: x for x in r["page1_now"]["today"]["by_method"]}
    assert m["Cash"]["count"] == 1 and m["Mada"]["count"] == 1
    assert m["Cash"]["amount"] == 15.0 and m["Mada"]["amount"] == 100.0


def test_payments_to_yesterday_only():
    r = reports.build(store(), now=NOW)
    p = r["page2_payments_to_yesterday"]
    assert p["invoices"] == 1 and p["by_method"][0]["method_en"] == "Mada" and p["by_method"][0]["amount_pct"] == 100.0


def test_hourly_divides_by_open_days():
    r = reports.build(store(), now=NOW)
    h = {x["hour"]: x for x in r["page6_hourly"]["hours"]}
    assert h[1]["days_open"] == 0 and h[1]["avg_per_open_day"] is None  # الساعة 1 الصبح مش جوه أي جلسة
    assert h[23]["days_open"] == 2 and h[23]["total"] == 50.0 and h[23]["avg_per_open_day"] == 25.0


def test_target():
    r = reports.build(store(), cfg={"targets": {"2026-11": 3000}}, now=NOW)
    t = r["page7_target"]
    assert t["achieved_net"] == 150.0 and t["remaining"] == 2850.0 and t["required_per_day"] == round(2850 / 16, 2)


def test_profitability_from_master():
    m = {"items": [{"product_id": 1, "list_price": 10, "cost": 11, "name_ar": "a"},
                   {"product_id": 2, "list_price": 10, "cost": 9.7, "name_ar": "b"},
                   {"product_id": 3, "list_price": 10, "cost": 5, "name_ar": "c"},
                   {"product_id": 4, "list_price": 0, "cost": 5, "name_ar": "d"}]}
    p = reports.build(store(), master=m, now=NOW)["page5_profitability"]
    assert [x["name"] for x in p["margin_le_0"]] == ["a"] and [x["name"] for x in p["margin_lt_5"]] == ["b"] and p["checked"] == 3


def test_periods_delta_and_users():
    st = store()
    st["orders"]["1"]["user_id"] = 7; st["orders"]["2"]["user_id"] = 9
    r = reports.build(st, now=NOW)
    assert r["periods"]["today"]["gross"] == 115.0 and r["periods"]["yesterday"]["gross"] == 50.0
    assert r["periods"]["today"]["delta"]["gross"] == 130.0
    assert {u["user"] for u in r["by_user"]["month"]} == {"P1", "P2"}
    assert "top_products_mtd" not in r
    assert r["hourly_compare"]["today"][1] == 115.0 and r["hourly_compare"]["yesterday"][23] == 50.0
