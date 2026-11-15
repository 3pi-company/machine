"""اختبارات القيد: أي محاولة كتابة أو موديل أو مسار مش مسموح = رفض قبل ما الطلب يتبعت."""
import json, pytest
import juleb_web as jw


class NoNet:
    def open(self, *a, **k):
        raise AssertionError("الطلب اتبعت رغم إنه المفروض يترفض")


def T():
    return jw.Transport("https://example.invalid", gap=0, opener=NoNet())


def sr(params):
    return {"jsonrpc": "2.0", "method": "call", "params": params}


@pytest.mark.parametrize("path", ["/web/dataset/call_kw", "/web/dataset/call_kw/pos.order/write", "/web/dataset/call_button",
                                  "/xmlrpc/2/object", "/api/v1/pos/order", "/web/session/destroy"])
def test_forbidden_paths(path):
    with pytest.raises(jw.ReadOnlyViolation):
        T().post(path, sr({"model": "pos.order"}))


@pytest.mark.parametrize("extra", [{"method": "write"}, {"method": "create"}, {"method": "unlink"}, {"args": [[1], {"x": 1}]},
                                   {"kwargs": {}}, {"method": "search_read", "args": []}])
def test_write_like_params_rejected(extra):
    with pytest.raises(jw.ReadOnlyViolation):
        T().post("/web/dataset/search_read", sr({"model": "pos.order", "domain": [], "fields": ["id"], **extra}))


@pytest.mark.parametrize("model", ["res.users", "res.partner", "account.move", "stock.quant", "ir.config_parameter"])
def test_model_not_in_whitelist(model):
    with pytest.raises(jw.ReadOnlyViolation):
        T().post("/web/dataset/search_read", sr({"model": model, "domain": [], "fields": ["id"]}))


def test_field_names_with_create_are_fine():
    # create_date اسم حقل عادي ومش لازم يترفض (بيعدي الفحص ويوصل للشبكة)
    with pytest.raises(jw.ReadOnlyStop, match="network:AssertionError"):  # عدّى الفحص ووصل للشبكة
        T().post("/web/dataset/search_read", sr({"model": "pos.order", "domain": [], "fields": ["id", "create_date", "write_date"]}))


def test_one_login_only():
    s = jw.Session(T()); s.uid = 5
    with pytest.raises(jw.ReadOnlyViolation):
        s.login("db", "u", "p")


def test_bad_login_keys():
    with pytest.raises(jw.ReadOnlyViolation):
        T().post("/web/session/authenticate", sr({"db": "d", "login": "u", "password": "p", "context": {}}))
