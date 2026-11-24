"""Set de PRÁCTICA para Zúrich: aquí sí se ajusta mirando fallos. Ids distintos a eval_zurich.py y al Test.
Uso: python -u scripts/eval_zurich_dev.py [--fake]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eval_zurich import f, first_not_in_test, pick  # noqa: E402
from pipeline import evaluate  # noqa: E402
from tools.profiles import Profile  # noqa: E402


def build_cases(P):
    reg, _ = P.table("register")
    crown, _ = P.geo("crown")
    parts, _ = P.table("parts3d")
    c1, c2 = pick(crown[crown.is_valid]["baumnummer"], 10), pick(crown[crown.is_valid]["baumnummer"], 160)
    a = pick(reg["baumnummer"], 30000)
    p3 = pick(parts["baumnummer"], 150)
    qv = reg["quartier"].value_counts().index
    quart = qv[min(3, len(qv) - 1)]
    streets = first_not_in_test(reg["strasse"].value_counts().index, 6)
    street = streets[min(5, len(streets) - 1)]
    return [
        {"id": "d01", "q": f"How big is the supplied crown footprint of {c1} in square metres, compared with {c2}?",
         "ref": {"calls": [{"tool": "areas", "table": "crown", "ids": [c1, c2]}]}},
        {"id": "d02", "q": f"Inside a 30 m radius of register entry {a}, how many entries are there and what share were planted since 2015?",
         "ref": {"calls": [{"tool": "within_radius", "table": "register", "anchor": a, "radius": 30,
                            "filters": [f("pflanzjahr", "ge", 2015)]}]}},
        {"id": "d03", "q": f"How many register entries are in quartier {quart}, and how many of those are kategorie Strassenbaum?",
         "ref": {"calls": [{"tool": "count", "table": "register", "filters": [f("quartier", "eq", quart)]},
                           {"tool": "count", "table": "register", "filters": [f("quartier", "eq", quart), f("kategorie", "eq", "Strassenbaum")]}]}},
        {"id": "d04", "q": f"On strasse {street}, which German tree name (baumnamedeu) is most frequent in the register, and with how many entries?",
         "ref": {"calls": [{"tool": "group_count", "table": "register", "field": "baumnamedeu", "filters": [f("strasse", "eq", street)]}]}},
        {"id": "d05", "q": "What percentage of all register rows have no planting year? Should we fill them with zero?",
         "ref": {"calls": [{"tool": "percent", "table": "register", "filters": [f("pflanzjahr", "null")], "denominator": []}]},
         "verdicts": ["No"]},
        {"id": "d06", "q": f"What vertical extent does the 3D Stamm part of {p3} span, and how does it compare with its hoehe_baum_total?",
         "ref": {"calls": [{"tool": "z_extent", "table": "parts3d", "ids": [p3]}]}},
        {"id": "d07", "q": "How many register entries have genauigkeit Luftbild? Are those field-surveyed points?",
         "ref": {"calls": [{"tool": "count", "table": "register", "filters": [f("genauigkeit", "eq", "Luftbild")]}]},
         "verdicts": ["No"]},
        {"id": "d08", "q": "How many of the 3D part geometries fail validity checks? Should we repair them before using them?",
         "ref": {"calls": [{"tool": "validity", "table": "parts3d"}]}, "verdicts": ["No"]},
        {"id": "d09", "q": "What is the mean hoehe of inventory entries with status Grünanlage?",
         "ref": {"calls": [{"tool": "mean", "table": "inventory", "field": "hoehe", "filters": [f("status", "eq", "Grünanlage")]}]}},
        {"id": "d10", "q": "How many register entries have status Kanton, and how many have status Obst?",
         "ref": {"calls": [{"tool": "count", "table": "register", "filters": [f("status", "eq", "Kanton")]},
                           {"tool": "count", "table": "register", "filters": [f("status", "eq", "Obst")]}]}},
    ]


if __name__ == "__main__":
    P = Profile("zurich")
    evaluate.run(build_cases(P), P, fake="--fake" in sys.argv)
