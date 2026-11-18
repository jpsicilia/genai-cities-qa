"""Set de prueba PROPIO para Zúrich. Los ids se eligen de los datos al correr, evitando los del Test.
Solo para MEDIR (no ajustar protecciones mirando sus fallos).

Uso: python -u scripts/eval_zurich.py [--fake]
"""
import os
import re
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import evaluate  # noqa: E402
from tools import loaders  # noqa: E402
from tools.profiles import Profile  # noqa: E402

def _test_text():
    """Texto de las preguntas del Test, leído al correr (no se escribe nada del Test en el código)."""
    try:
        return " ".join(pd.read_csv(os.path.join(loaders.DATA, "Test.csv"))["Question"].astype(str))
    except (OSError, KeyError):
        return ""


TEST_TEXT = _test_text()
ID_RE = re.compile(r"[A-Za-z0-9]+(?:[_-][A-Za-z0-9]+)+")
TEST_TOKENS = set(ID_RE.findall(TEST_TEXT))


def in_test(v):
    """True si el valor aparece en alguna pregunta del Test: esos valores no se usan en sets propios."""
    v = str(v)
    if v in TEST_TOKENS:
        return True
    if ID_RE.fullmatch(v):
        return False
    return len(v) >= 4 and re.search(rf"(?<!\w){re.escape(v)}(?!\w)", TEST_TEXT) is not None


def pick(series, i):
    vals = []
    for v in series.dropna().astype(str).unique():
        if not in_test(v):
            vals.append(v)
            if len(vals) > i:
                break
    return vals[min(i, len(vals) - 1)]


def f(field, op, value=None):
    d = {"field": field, "op": op}
    if value is not None:
        d["value"] = value
    return d


def build_cases(P):
    reg, _ = P.table("register")
    inv, _ = P.table("inventory")
    crown, _ = P.geo("crown")
    parts, _ = P.table("parts3d")
    c1, c2 = pick(crown[crown.is_valid]["baumnummer"], 50), pick(crown[crown.is_valid]["baumnummer"], 120)
    a = pick(reg["baumnummer"], 1000)
    p3 = pick(parts["baumnummer"], 20)
    quart = reg["quartier"].value_counts().index[0]
    streets = [s for s in reg["strasse"].value_counts().index if not in_test(s)]
    street = streets[0]
    return [
        {"id": "z01", "q": f"What are the planar areas of the crown drawing features {c1} and {c2}, and how many square metres larger is {c1} than {c2}?",
         "ref": {"calls": [{"tool": "areas", "table": "crown", "ids": [c1, c2]}]}},
        {"id": "z02", "q": "How many polygons in the position-symbol view are invalid? Should we silently drop them?",
         "ref": {"calls": [{"tool": "validity", "table": "symbol"}]}, "verdicts": ["No"]},
        {"id": "z03", "q": f"Which other register entry is nearest to {a}, and at what distance?",
         "ref": {"calls": [{"tool": "nearest", "table": "register", "anchor": a}]}},
        {"id": "z04", "q": f"Within 50 m of register entry {a}, including it, how many records are there and what share have a planting year of 2010 or later?",
         "ref": {"calls": [{"tool": "within_radius", "table": "register", "anchor": a, "radius": 50,
                            "filters": [f("pflanzjahr", "ge", 2010)]}]}},
        {"id": "z05", "q": f"What vertical extent does the supplied 3D part of {p3} have? Is that the whole-tree height?",
         "ref": {"calls": [{"tool": "z_extent", "table": "parts3d", "ids": [p3]}]}, "verdicts": ["No"]},
        {"id": "z06", "q": f"How many register records are in quartier {quart}, and how many of those have no planting year?",
         "ref": {"calls": [{"tool": "count", "table": "register", "filters": [f("quartier", "eq", quart)]},
                           {"tool": "count", "table": "register", "filters": [f("quartier", "eq", quart), f("pflanzjahr", "null")]}]}},
        {"id": "z07", "q": f"Among register entries whose strasse is exactly {street}, which genus (baumgattunglat) is most common and how many entries have it?",
         "ref": {"calls": [{"tool": "group_count", "table": "register", "field": "baumgattunglat",
                            "filters": [f("strasse", "eq", street)]}]}},
        {"id": "z08", "q": "How many inventory entries have status 'Strassenbaum (A)', and how many have status 'Strassenbaum'?",
         "ref": {"calls": [{"tool": "count", "table": "inventory", "filters": [f("status", "eq", "Strassenbaum (A)")]},
                           {"tool": "count", "table": "inventory", "filters": [f("status", "eq", "Strassenbaum")]}]}},
        {"id": "z09", "q": "How many register locations have genauigkeit Eingemessen? Does that certify the tree is still there today?",
         "ref": {"calls": [{"tool": "count", "table": "register", "filters": [f("genauigkeit", "eq", "Eingemessen")]}]},
         "verdicts": ["No"]},
        {"id": "z10", "q": "What is the mean hoehe of inventory entries with status Strassenbaum?",
         "ref": {"calls": [{"tool": "mean", "table": "inventory", "field": "hoehe", "filters": [f("status", "eq", "Strassenbaum")]}]}},
        {"id": "z11", "q": "What is the largest kronendurchmesser in the register, and which entries have it? Was that crown measured in the field?",
         "ref": {"calls": [{"tool": "extreme", "table": "register", "field": "kronendurchmesser"}]}, "verdicts": ["No"]},
        {"id": "z12", "q": "Compare objectid 10 in the crown drawing and in the register: do they describe the same tree?",
         "ref": {"calls": [{"tool": "record", "table": "crown", "key_field": "objectid", "ids": [10]},
                           {"tool": "record", "table": "register", "key_field": "objectid", "ids": [10]}]},
         "text_check": False},
        {"id": "z13", "q": "How many register baumnummer values start with nn-?",
         "ref": {"calls": [{"tool": "prefix_counts", "table": "register", "field": "baumnummer", "prefixes": ["nn-"]}]}},
        {"id": "z14", "q": "What percentage of all inventory rows have uuid_tlm3d recorded as null? Are those invalid trees?",
         "ref": {"calls": [{"tool": "percent", "table": "inventory", "filters": [f("uuid_tlm3d", "null")], "denominator": []}]},
         "verdicts": ["No"]},
    ]


if __name__ == "__main__":
    P = Profile("zurich")
    cases = build_cases(P)
    evaluate.run(cases, P, fake="--fake" in sys.argv)
