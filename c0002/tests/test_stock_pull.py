"""اختيار حقول branch.stock.page من سجل واحد (أسماء بس)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import stock_pull


def test_pick_fields():
    prod, qty, branch, keys = stock_pull.pick_fields({"id": 1, "product_id": [5, "x"], "qty_available": -2.0, "company_id": [1, "c"], "active": True})
    assert (prod, qty, branch) == ("product_id", "qty_available", "company_id")


def test_pick_fields_fallback_qty_name():
    prod, qty, branch, _ = stock_pull.pick_fields({"id": 1, "product_id": 3, "branch_qty": 4, "price": 9.5})
    assert prod == "product_id" and qty == "branch_qty"
