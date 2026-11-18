"""Evalúa el pipeline con preguntas PROPIAS (no del Test).

Para cada pregunta hay un plan de referencia escrito a mano. Se compara el número
principal que sale del plan del LLM contra el que sale del plan de referencia
(ambos calculados por las mismas herramientas). Así medimos si el LLM elige bien
herramientas y filtros, sin usar respuestas del Test.

Uso:
  python scripts/eval_variants.py            # usa Ollama
  python scripts/eval_variants.py --fake     # sin LLM: el "modelo" devuelve el plan de referencia
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import evaluate  # noqa: E402
from tools.profiles import Profile  # noqa: E402

POOR = "Poor (Low Vitality/Extensive Defects)"
CASES = [
    ("v01", "How many DCC records are marked Fallen, and how many Felled?",
     {"calls": [{"tool": "count", "table": "dcc", "filters": [{"field": "Condition", "op": "eq", "value": "Fallen"}]},
                {"tool": "count", "table": "dcc", "filters": [{"field": "Condition", "op": "eq", "value": "Felled"}]}]}),
    ("v02", "What percentage of all DCC rows have no Spread value recorded?",
     {"calls": [{"tool": "percent", "table": "dcc", "filters": [{"field": "Spread", "op": "null"}], "denominator": []}]}),
    ("v03", "How many DCC records are on Malahide Rd if we ignore letter case, and how is that split by spelling?",
     {"calls": [{"tool": "variants", "table": "dcc", "field": "Street", "key": "malahide rd"}]}),
    ("v04", "For the group whose Species starts with 'Tilia ', how many records are there and what share are Poor?",
     {"calls": [{"tool": "count", "table": "dcc", "filters": [{"field": "Species", "op": "startswith", "value": "Tilia "}]},
                {"tool": "percent", "table": "dcc", "filters": [{"field": "Condition", "op": "eq", "value": POOR}],
                 "denominator": [{"field": "Species", "op": "startswith", "value": "Tilia "}]}]}),
    ("v05", "In DLR, what is the raw mean Act_height for Ballinteer-Marley?",
     {"calls": [{"tool": "mean", "table": "dlr", "field": "Act_height",
                 "filters": [{"field": "Location", "op": "eq", "value": "Ballinteer-Marley"}]}]}),
    ("v06", "How many DLR records have Common_nam exactly 'Ash spp'?",
     {"calls": [{"tool": "count", "table": "dlr", "filters": [{"field": "Common_nam", "op": "eq", "value": "Ash spp"}]}]}),
    ("v07", "What is the maximum Act_spread in DLR and which Tree_code has it?",
     {"calls": [{"tool": "extreme", "table": "dlr", "field": "Act_spread"}]}),
    ("v08", "Read DLR record Tree_code 609: what are its Common_nam and Act_height?",
     {"calls": [{"tool": "lookup", "table": "dlr", "key": 609}]}),
    ("v09", "How many DLR rows have blank Tree_locn text after trimming spaces?",
     {"calls": [{"tool": "count", "table": "dlr", "filters": [{"field": "Tree_locn", "op": "blank"}]}]}),
    ("v10", "Under 400 hypothetical credits, which two streets cover the most Poor-and-tall screening records?",
     {"calls": [{"tool": "allocation", "table": "dcc", "budget": 400}]}),
    ("v11", "How many DCC records are Young, and what percentage of rows with a recorded Age is that?",
     {"calls": [{"tool": "count", "table": "dcc", "filters": [{"field": "Age", "op": "eq", "value": "Young (Within first third of life span)"}]},
                {"tool": "percent", "table": "dcc", "filters": [{"field": "Age", "op": "eq", "value": "Young (Within first third of life span)"}],
                 "denominator": [{"field": "Age", "op": "notnull"}]}]}),
    ("v12", "Among DCC records with a height band, what is the mean of the bands' lower edges for Poor trees?",
     {"calls": [{"tool": "mean", "table": "dcc", "field": "Height", "mapping": "dcc_height_lower_edge",
                 "filters": [{"field": "Condition", "op": "eq", "value": POOR}]}]}),
]


def main(fake=False):
    cases = [{"id": i, "q": q, "ref": p, "text_check": i != "v08"} for i, q, p in CASES]
    evaluate.run(cases, Profile("dublin"), fake=fake)


if __name__ == "__main__":
    main(fake="--fake" in sys.argv)
