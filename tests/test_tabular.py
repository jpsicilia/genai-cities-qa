"""Tests de las herramientas con datos sintéticos (no usan datos del Test).
Correr: python -m pytest tests -q
"""
import math

import pandas as pd
import pytest

from tools import tabular as T


@pytest.fixture
def df():
    return pd.DataFrame({
        "id": ["a", "b", "b", "dup-x", "dup-x", "c"],
        "street": ["MAIN ST", "Main St", " main st ", None, "", "Oak Rd"],
        "cond": ["Poor", "Fair", None, "Poor", "Dead", "Poor"],
        "band": ["00 to 05m", "Over 25m", None, "05 to 10m", "05 to 10m", "Over 25m"],
        "h": [0.0, 10.0, 20.0, 0.0, 5.0, 89.0],
    })


def test_null_vs_blank(df):
    assert T.count(df, [{"field": "street", "op": "null"}])["value"] == 1
    assert T.count(df, [{"field": "street", "op": "blank"}])["value"] == 2


def test_eq_norm_and_variants(df):
    assert T.count(df, [{"field": "street", "op": "eq_norm", "value": "main st"}])["value"] == 3
    v = T.variants(df, "street", "MAIN ST")
    assert v["value"] == 3 and v["by_spelling"]["MAIN ST"] == 1


def test_percent_two_denominators(df):
    poor = [{"field": "cond", "op": "eq", "value": "Poor"}]
    all_rows = T.percent(df, poor)
    recorded = T.percent(df, poor, [{"field": "cond", "op": "notnull"}])
    assert all_rows["denominator"] == 6 and all_rows["display"] == "50.00%"
    assert recorded["denominator"] == 5 and recorded["display"] == "60.00%"


def test_mean_raw_vs_positive(df):
    raw = T.mean(df, "h")
    pos = T.mean(df, "h", positive_only=True)
    assert raw["n_used"] == 6 and pos["n_removed"] == 2
    assert math.isclose(pos["value"], (10 + 20 + 5 + 89) / 4)


def test_mean_with_mapping_ignores_missing_band(df):
    edges = {"00 to 05m": 0, "05 to 10m": 5, "Over 25m": 25}
    r = T.mean(df, "band", mapping=edges)
    assert r["n_used"] == 5 and math.isclose(r["value"], (0 + 25 + 5 + 5 + 25) / 5)


def test_extreme_returns_all_ties():
    d = pd.DataFrame({"k": [1, 2, 3], "x": [9.0, 89.0, 89.0]})
    r = T.extreme(d, "x", id_field="k")
    assert r["value"] == 89.0 and r["n_hits"] == 2 and [x["k"] for x in r["records"]] == [2, 3]


def test_distinct_and_dedupe(df):
    r = T.distinct(df, "id")
    assert r["n_rows"] == 6 and r["n_distinct_nonnull"] == 4
    assert r["n_values_repeated"] == 2 and r["rows_dropped_by_dedupe"] == 2


def test_best_combo_budget_and_ties():
    items = [{"name": "A", "cost": 300, "value": 10}, {"name": "B", "cost": 250, "value": 9},
             {"name": "C", "cost": 100, "value": 9}, {"name": "D", "cost": 50, "value": 1}]
    r = T.best_combo(items, k=2, budget=400)
    assert r["value"]["covered"] == 19 and r["value"]["cost"] == 400   # A + C
    r2 = T.best_combo(items, k=2, budget=550)
    assert r2["value"]["covered"] == 19 and r2["value"]["cost"] == 400  # empate A+B (550) vs A+C (400)
    assert ["A", "B"] in r2["ties"]


def test_circle_area():
    lo, hi = T.circle_area_range(2, 4)["value"]
    assert math.isclose(lo, math.pi) and math.isclose(hi, 4 * math.pi)
