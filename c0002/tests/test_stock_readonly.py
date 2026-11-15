"""قارئ الرصيد: branch.stock.page بـsearch_read بس. أي حاجة تانية مرفوضة قبل ما الطلب يتبعت."""
import os, sys, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import stock_web as jw


def rq(params, method="call"):
    return {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}


def test_only_branch_stock_model():
    jw.Transport.check("/web/dataset/search_read", rq({"model": "branch.stock.page", "domain": [], "fields": ["id"]}))
    for m in ("pos.order", "product.product", "res.users", "stock.quant", "res.partner"):
        with pytest.raises(jw.ReadOnlyViolation):
            jw.Transport.check("/web/dataset/search_read", rq({"model": m, "domain": [], "fields": ["id"]}))


@pytest.mark.parametrize("path", ["/web/dataset/call_kw", "/web/dataset/call_kw/branch.stock.page/write",
                                  "/web/dataset/call_kw/branch.stock.page/create", "/web/dataset/call_kw/branch.stock.page/unlink",
                                  "/web/dataset/call", "/jsonrpc", "/xmlrpc/2/object"])
def test_write_paths_rejected(path):
    with pytest.raises(jw.ReadOnlyViolation):
        jw.Transport.check(path, rq({"model": "branch.stock.page", "method": "write", "args": [[1], {"x": 1}]}))


@pytest.mark.parametrize("extra", [{"method": "write"}, {"args": [[1]]}, {"kwargs": {}}, {"method": "unlink"}, {"method": "create"}])
def test_call_kw_style_params_rejected(extra):
    with pytest.raises(jw.ReadOnlyViolation):
        jw.Transport.check("/web/dataset/search_read", rq({"model": "branch.stock.page", "domain": [], "fields": [], **extra}))


def test_login_only_db_login_password():
    jw.Transport.check("/web/session/authenticate", rq({"db": "x", "login": "u", "password": "p"}))
    with pytest.raises(jw.ReadOnlyViolation):
        jw.Transport.check("/web/session/authenticate", rq({"db": "x", "login": "u", "password": "p", "context": {}}))


def test_stops_on_http_errors():
    import urllib.error

    class Op:
        def __init__(self, code): self.code = code
        def open(self, req, timeout=0): raise urllib.error.HTTPError(req.full_url, self.code, "x", {}, None)
    for code in (401, 403, 429, 500):
        t = jw.Transport("https://example.invalid", gap=0, opener=Op(code))
        with pytest.raises(jw.ReadOnlyStop):
            t.post("/web/dataset/search_read", rq({"model": "branch.stock.page", "domain": [], "fields": ["id"]}))


def test_cap():
    t = jw.Transport("https://example.invalid", cap=0, gap=0)
    with pytest.raises(jw.ReadOnlyStop):
        t.post("/web/dataset/search_read", rq({"model": "branch.stock.page", "domain": [], "fields": ["id"]}))
