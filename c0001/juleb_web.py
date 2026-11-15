#!/usr/bin/env python3
"""3pi - طبقة قراءة بجلسة ويب لجوليب (Odoo 13). قراءة فقط، والقيد في الكود.

* المسارات المسموحة: /web/session/authenticate (دخول واحد) و /web/dataset/search_read بس.
* الموديلات المسموحة: ALLOWED_MODELS بس. أي موديل تاني = رفض قبل ما الطلب يتبعت.
* الطريقة الوحيدة: search_read. أي write/create/unlink/call_kw/... = رفض.
* الجلسة (الكوكي) في الذاكرة بس. الباسورد عمره ما بيتطبع ولا بيتكتب في ملف.
* 401/403/429/5xx أو خطأ جلسة = وقف فوري (ReadOnlyStop). ومفيش تبديل حسابات.
"""
import json, os, time, urllib.request, urllib.error, http.cookiejar

ALLOWED_PATHS = {"/web/session/authenticate", "/web/dataset/search_read"}
ALLOWED_METHODS = {"search_read"}
ALLOWED_MODELS = {
    "pos.order", "pos.order.line", "pos.payment", "pos.session", "pos.payment.method",
    "product.product", "product.template", "product.category", "branch.stock.page",
}
ALLOWED_PARAM_KEYS = {"model", "domain", "fields", "limit", "offset", "sort", "context"}
LOGIN_PARAM_KEYS = {"db", "login", "password"}


class ReadOnlyViolation(Exception):
    """محاولة لعملية مش قراءة. ده خطأ برمجي ولازم يوقف كل حاجة."""


class ReadOnlyStop(Exception):
    """رفض من السيرفر أو حد معدل: وقف من غير إعادة محاولة."""


class Transport:
    """الطبقة الوحيدة اللي بتكلم السيرفر. كل طلب بيعدي على check() الأول."""

    def __init__(self, base, cap=200, gap=3.0, opener=None):
        self.base = base.rstrip("/")
        if self.base.endswith("/web"): self.base = self.base[:-4]
        self.cap, self.gap, self.used, self.last = cap, gap, 0, 0.0
        self.jar = http.cookiejar.CookieJar()
        self.opener = opener or urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    @staticmethod
    def check(path, payload):
        if path not in ALLOWED_PATHS:
            raise ReadOnlyViolation(f"مسار مش مسموح: {path}")
        if payload.get("method") != "call" or set(payload) - {"jsonrpc", "method", "params", "id"}:
            raise ReadOnlyViolation("شكل طلب مش مسموح")
        params = payload.get("params") or {}
        if path == "/web/session/authenticate":
            if set(params) != LOGIN_PARAM_KEYS:
                raise ReadOnlyViolation("مفاتيح دخول مش مسموحة")
            return
        extra = set(params) - ALLOWED_PARAM_KEYS
        if extra:  # args/kwargs/method/... = محاولة call_kw أو غيره
            raise ReadOnlyViolation(f"مفاتيح مش مسموحة: {sorted(extra)}")
        if params.get("model") not in ALLOWED_MODELS:
            raise ReadOnlyViolation(f"موديل مش مسموح: {params.get('model')}")

    def post(self, path, payload):
        self.check(path, payload)
        if self.used >= self.cap:
            raise ReadOnlyStop("سقف الطلبات")
        w = self.gap - (time.time() - self.last)
        if w > 0: time.sleep(w)
        req = urllib.request.Request(self.base + path, data=json.dumps(payload).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "Accept": "application/json"})
        self.used += 1; self.last = time.time()
        try:
            with self.opener.open(req, timeout=90) as r:
                body = json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise ReadOnlyStop(f"HTTP {e.code}")
        except Exception as e:
            raise ReadOnlyStop("network:" + type(e).__name__)
        if body.get("error"):
            msg = str((body["error"].get("data") or {}).get("name") or body["error"].get("message"))[:80]
            raise ReadOnlyStop("JSON-RPC error: " + msg)
        return body.get("result")


class Session:
    def __init__(self, transport):
        self.t = transport
        self.companies = []
        self.uid = None

    def login(self, db, user, password):
        if self.uid is not None:
            raise ReadOnlyViolation("دخول واحد بس لكل تشغيل")
        res = self.t.post("/web/session/authenticate",
                          {"jsonrpc": "2.0", "method": "call", "params": {"db": db, "login": user, "password": password}})
        if not res or not res.get("uid"):
            raise ReadOnlyStop("الدخول فشل")
        self.uid = res["uid"]
        uc = res.get("user_companies") or {}
        self.companies = [c[0] if isinstance(c, list) else c for c in (uc.get("allowed_companies") or [])]
        return {"companies": len(self.companies)}

    def search_read(self, model, domain, fields, limit=1000, offset=0, sort="id asc"):
        if self.uid is None:
            raise ReadOnlyViolation("لازم دخول الأول")
        ctx = {"allowed_company_ids": self.companies} if self.companies else {}
        res = self.t.post("/web/dataset/search_read", {"jsonrpc": "2.0", "method": "call", "params": {
            "model": model, "domain": domain, "fields": fields, "limit": limit, "offset": offset, "sort": sort,
            "context": ctx}})
        return res  # {"length": N, "records": [...]}

    def read_all(self, model, domain, fields, page=1000):
        """كل الصفحات مع فحوص السلامة: length ثابت، ومفيش تكرار، ومفيش صفحة فاضية قبل النهاية."""
        rows, seen, offset, length = [], set(), 0, None
        while True:
            r = self.search_read(model, domain, fields, limit=page, offset=offset)
            L = r.get("length")
            if length is None: length = L
            elif L != length: raise ReadOnlyStop(f"{model}: length اتغيّر بين الصفحات")
            recs = r.get("records") or []
            if not recs and len(rows) < (length or 0): raise ReadOnlyStop(f"{model}: صفحة فاضية قبل النهاية")
            for x in recs:
                if x.get("id") in seen: raise ReadOnlyStop(f"{model}: تكرار id")
                seen.add(x.get("id")); rows.append(x)
            offset += len(recs)
            if not recs or len(rows) >= (length or 0): break
        if length is not None and len(rows) != length:
            raise ReadOnlyStop(f"{model}: {len(rows)} ≠ length {length}")
        return rows
