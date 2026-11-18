"""Demo: herramientas + perfil de Dublín sobre preguntas PROPIAS (variantes, no del Test).

Cada bloque imita cómo el LLM va a llamar a las herramientas: elige operación y
parámetros; Python calcula y arma la evidencia en formato SOURCE_ID | locator | claim.

Uso: python scripts/demo_variants.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools import tabular as T  # noqa: E402
from tools.profiles import Profile  # noqa: E402

P = Profile("dublin")
dcc, DCC = P.table("dcc")
dlr, DLR = P.table("dlr")
costs, COSTS = P.table("costs")


def show(question, res):
    print("\n" + "=" * 80 + f"\nQ: {question}\nA: {res['display']}")
    for k in ("total_rows", "numerator", "denominator", "n_used", "n_removed", "n_hits", "by_spelling", "ties"):
        if k in res and res[k] not in (None, [], {}):
            print(f"   {k}: {res[k]}")
    for e in res["evidence"]:
        print(f"   - {e['source_id']} | {e['locator']} | {e['claim']}")


street = lambda s: {"field": "Street", "op": "eq_norm", "value": s}  # noqa: E731

show("How many DCC records are on Herbert Park, ignoring letter case? Split by spelling.",
     T.variants(dcc, "Street", "herbert park", source_id=DCC))

show("What % of DCC rows are Good, over all rows and over rows with a recorded condition?",
     T.percent(dcc, [{"field": "Condition", "op": "eq", "value": "Good (Normal Vitality. No Major Defects)"}],
               source_id=DCC))
show("   ...same, denominator = recorded condition",
     T.percent(dcc, [{"field": "Condition", "op": "eq", "value": "Good (Normal Vitality. No Major Defects)"}],
               [{"field": "Condition", "op": "notnull"}], source_id=DCC))

loc = [{"field": "Location", "op": "eq", "value": "Dundrum-Sandyford"}]
show("Raw mean Act_height in Dundrum-Sandyford (DLR)?", T.mean(dlr, "Act_height", loc, source_id=DLR))
show("   ...positive-only", T.mean(dlr, "Act_height", loc, positive_only=True, source_id=DLR))

show("Maximum Act_spread in DLR and which Tree_codes reach it?",
     T.extreme(dlr, "Act_spread", id_field="Tree_code", show=["Common_nam", "Site_name"], source_id=DLR))

show("How many distinct non-null Common_nam labels in DLR?", T.distinct(dlr, "Common_nam", source_id=DLR))

show("Lookup DLR Tree_code 608", T.lookup(dlr, "Tree_code", 608, ["Common_nam", "Act_height", "Height", "Age"],
                                          source_id=DLR))

show("Top 3 streets by Poor-and-tall records (normalised)?",
     T.group_count(dcc, "Street", P.filters("poor_tall"), normalize=True, top=3, source_id=DCC))

show("Lower-edge mean height among DCC records on Herbert Park with a band?",
     T.mean(dcc, "Height", [street("herbert park")], mapping=P.mapping("dcc_height_lower_edge"), source_id=DCC))

# Variante del problema de presupuesto: tope 400 en vez de 550
items = [{"name": r.street, "cost": int(r.hypothetical_cost_credits),
          "value": T.count(dcc, P.filters("poor_tall", street(r.street)))["value"]}
         for r in costs.itertuples()]
show("Best pair of streets under 400 credits covering most Poor-and-tall records?",
     T.best_combo(items, k=2, budget=400, source_id=COSTS))

show("Circle area range for the DCC 3-6 m Spread band?", T.circle_area_range(3, 6))
