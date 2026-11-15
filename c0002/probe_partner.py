#!/usr/bin/env python3
"""3pi - فحص صغير قراءة فقط: هل فيه مسار REST لاسم العميل (res.partner) لـC-0002؟
بموافقة المالك 2026-11-15 (إظهار اسم العميل كامل بدل الرقم).

1) يقرا مواصفات swagger (طلب واحد) ويدوّر على أي مسار فيه partner/customer.
2) لو لقى مسار، بيجرب GET عليه (limit=1) ويسجّل *أسماء الحقول وشكلها* بس (من غير قيم ولا أسماء عملاء حقيقية).
الضمانات: GET بس، سقف 6 طلبات، 3 ثواني بين الطلبات، وقف عند 401/403/429/5xx. لا طباعة لأي بيانات عميل.
النتيجة بتتكتب في docs/PROBE_PARTNER.md. مفيش أي تعديل على sync.py ولا على المخزن الأساسي.
"""
import json, os, re, time, urllib.request, urllib.error
from datetime import datetime, timezone

BASE_CANDIDATES = ["/api/v1/resources/res-partner", "/api/v1/resources/res-customer",
                    "/api/v1/customers", "/api/v1/partners", "/api/v1/resources/partner"]


class C:
    def __init__(self, base, key, cap=6, gap=3.0):
        self.base, self.key, self.cap, self.gap, self.used, self.last = base, key, cap, gap, 0, 0.0

    def get(self, path, params=None):
        if self.used >= self.cap:
            return 0, b"cap"
        w = self.gap - (time.time() - self.last)
        if w > 0:
            time.sleep(w)
        q = ("?" + "&".join(f"{k}={v}" for k, v in (params or {}).items()))
        req = urllib.request.Request(self.base + path + q, method="GET",
                                     headers={"Authorization": f"Bearer {self.key}", "Accept": "application/json"})
        self.used += 1
        self.last = time.time()
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, b""
        except Exception as e:
            return 0, type(e).__name__.encode()


def kind(v):
    if v is None: return "null"
    if isinstance(v, bool): return "bool"
    if isinstance(v, (int, float)): return type(v).__name__
    if isinstance(v, str): return "str"
    if isinstance(v, list): return f"list[{len(v)}]"
    if isinstance(v, dict): return "obj"
    return type(v).__name__


def main():
    base = os.environ.get("CLIENT_C0002_JULEB_URL", "").strip().rstrip("/")
    if base.endswith("/web"): base = base[:-4]
    key = os.environ.get("CLIENT_C0002_JULEB_API_KEY", "")
    rep = {"run_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "found_paths": [], "tried": [], "field_shapes": None}
    if not base or not key:
        rep["stopped"] = "secrets missing"
    else:
        c = C(base, key)
        st, body = c.get("/api/v1/docs/swagger-ui-init.js")
        if st == 200:
            try:
                txt = body.decode("utf-8", "ignore")
                m = re.search(r"\{.*\"paths\"\s*:.*\}", txt, re.S)
                spec = json.loads(m.group(0)) if m else {}
                paths = list((spec.get("paths") or {}).keys())
                rep["found_paths"] = [p for p in paths if re.search(r"partner|customer|عميل", p, re.I)]
            except Exception as e:
                rep["spec_parse_error"] = type(e).__name__
        candidates = rep["found_paths"] or BASE_CANDIDATES
        for p in candidates:
            if c.used >= c.cap: break
            st, body = c.get(p, {"limit": 1, "page": 1})
            rep["tried"].append({"path": p, "status": st})
            if st == 200 and rep["field_shapes"] is None:
                try:
                    j = json.loads(body)
                    row = (j.get("data") or [None])[0]
                    if isinstance(row, dict):
                        rep["field_shapes"] = {k: kind(v) for k, v in row.items()}
                        rep["working_path"] = p
                except Exception:
                    pass
        rep["requests_used"] = c.used
    os.makedirs("docs", exist_ok=True)
    with open("docs/PROBE_PARTNER.md", "w", encoding="utf-8") as f:
        f.write("# فحص اسم العميل (res.partner) — C-0002\n\n```json\n" + json.dumps(rep, ensure_ascii=False, indent=2) + "\n```\n")
    print(json.dumps(rep, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
