"""Set de PRUEBA (holdout): 20 preguntas propias que el sistema nunca vio.

REGLA: este set solo se usa para MEDIR. No se ajustan protecciones, prompts ni ejemplos
mirando sus fallos; para eso está eval_variants.py. Si lo usamos para ajustar, deja de medir.

Uso:
  python -u scripts/eval_holdout.py [--fake]
  GENAI_MODEL=qwen2.5:3b python -u scripts/eval_holdout.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import evaluate  # noqa: E402
from tools.profiles import Profile  # noqa: E402


def f(field, op, value=None):
    d = {"field": field, "op": op}
    if value is not None:
        d["value"] = value
    return d


POOR = "Poor (Low Vitality/Extensive Defects)"
GOOD = "Good (Normal Vitality. No Major Defects)"
MATURE = "Mature (Within final third of lifespan)"

CASES = [
    {"id": "h01", "q": "How many DCC records have the condition Overgrown (Ivy/Bramble etc)? Does that label tell us the tree's species?",
     "ref": {"calls": [{"tool": "count", "table": "dcc", "filters": [f("Condition", "eq", "Overgrown (Ivy/Bramble etc)")]}]},
     "verdicts": ["No"]},
    {"id": "h02", "q": "What percentage of all DCC rows have Proximity recorded as null? Does a null Proximity mean there is no nearby building?",
     "ref": {"calls": [{"tool": "percent", "table": "dcc", "filters": [f("Proximity", "null")], "denominator": []}]},
     "verdicts": ["No"]},
    {"id": "h03", "q": "Ignoring letter case, how many DCC records are on Ringsend Park, and how are they split by spelling? Should an abbreviated spelling be merged automatically?",
     "ref": {"calls": [{"tool": "variants", "table": "dcc", "field": "Street", "key": "ringsend park"}]},
     "verdicts": ["No"]},
    {"id": "h04", "q": "For DCC records whose Species starts with 'Fraxinus ', how many are there and how many are marked Dead?",
     "ref": {"calls": [{"tool": "count", "table": "dcc", "filters": [f("Species", "startswith", "Fraxinus ")]},
                       {"tool": "count", "table": "dcc", "filters": [f("Species", "startswith", "Fraxinus "), f("Condition", "eq", "Dead")]}]}},
    {"id": "h05", "q": "Among DCC rows with a recorded Spread, what share are in the Over 15m (Diameter) band?",
     "ref": {"calls": [{"tool": "percent", "table": "dcc", "filters": [f("Spread", "eq", "Over 15m (Diameter)")],
                        "denominator": [f("Spread", "notnull")]}]}},
    {"id": "h06", "q": "Using the band lower edges, what is the mean height of Good DCC trees? Is that the observed mean height?",
     "ref": {"calls": [{"tool": "mean", "table": "dcc", "field": "Height", "mapping": "dcc_height_lower_edge",
                        "filters": [f("Condition", "eq", GOOD)]}]},
     "verdicts": ["No"]},
    {"id": "h07", "q": "How many distinct non-null StemDiameter labels does DCC have, and how many rows have it null?",
     "ref": {"calls": [{"tool": "distinct", "table": "dcc", "field": "StemDiameter"}]}},
    {"id": "h08", "q": "With 300 hypothetical credits, which two streets cover the most Poor-and-tall screening records? Are these costs real council prices?",
     "ref": {"calls": [{"tool": "allocation", "table": "dcc", "budget": 300}]},
     "verdicts": ["No"]},
    {"id": "h09", "q": "Which DCC street, after case normalisation, has the most records marked Dead?",
     "ref": {"calls": [{"tool": "group_count", "table": "dcc", "field": "Street", "filters": [f("Condition", "eq", "Dead")]}]}},
    {"id": "h10", "q": "Assume a circular crown with a diameter in the DCC 9-12m Spread band. What area range follows, and how many records carry that band? Would summing those circles give measured canopy cover?",
     "ref": {"calls": [{"tool": "circle_area", "table": "dcc", "d_min": 9, "d_max": 12},
                       {"tool": "count", "table": "dcc", "filters": [f("Spread", "eq", "9-12m (Diameter)")]}]},
     "verdicts": ["No"]},
    {"id": "h11", "q": "For Dundrum-Balally in DLR, give the record count, the raw mean Act_height and the mean using only positive values.",
     "ref": {"calls": [{"tool": "count", "table": "dlr", "filters": [f("Location", "eq", "Dundrum-Balally")]},
                       {"tool": "mean", "table": "dlr", "field": "Act_height", "filters": [f("Location", "eq", "Dundrum-Balally")]},
                       {"tool": "mean", "table": "dlr", "field": "Act_height", "filters": [f("Location", "eq", "Dundrum-Balally")],
                        "positive_only": True}]}},
    {"id": "h12", "q": "Among DLR records with Common_nam 'Ash spp', what is the maximum Act_height and which Tree_codes reach it?",
     "ref": {"calls": [{"tool": "extreme", "table": "dlr", "field": "Act_height", "filters": [f("Common_nam", "eq", "Ash spp")]}]}},
    {"id": "h13", "q": "How many DLR rows have Age code 5? Does code 5 mean the tree is five years old?",
     "ref": {"calls": [{"tool": "count", "table": "dlr", "filters": [f("Age", "eq", 5)]}]},
     "verdicts": ["No"]},
    {"id": "h14", "q": "How many DLR rows have blank Site_name text but nonblank Location text, after trimming spaces?",
     "ref": {"calls": [{"tool": "count", "table": "dlr", "filters": [f("Site_name", "blank"), f("Location", "nonblank")]}]}},
    {"id": "h15", "q": "What percentage of all DLR rows have Act_spread equal to 0?",
     "ref": {"calls": [{"tool": "percent", "table": "dlr", "filters": [f("Act_spread", "eq", 0)], "denominator": []}]}},
    {"id": "h16", "q": "Read DLR record Tree_code 610. Does the record itself give map coordinates?",
     "ref": {"calls": [{"tool": "lookup", "table": "dlr", "key": 610}]},
     "verdicts": ["No"], "text_check": False},
    {"id": "h17", "q": "After the explicit DLR exclusion screen, how many records remain? Does that make them verified living trees?",
     "ref": {"calls": [{"tool": "count", "table": "dlr", "named_filter": "dlr_screen_keep"}]},
     "verdicts": ["No"]},
    {"id": "h18", "q": "How many DCC rows have BuildingNumber recorded as null, and how many are blank after trimming spaces?",
     "ref": {"calls": [{"tool": "count", "table": "dcc", "filters": [f("BuildingNumber", "null")]},
                       {"tool": "count", "table": "dcc", "filters": [f("BuildingNumber", "blank")]}]}},
    {"id": "h19", "q": "How many DCC records are Mature, and how many DLR records have Age code 3? Can we treat those as the same age class?",
     "ref": {"calls": [{"tool": "count", "table": "dcc", "filters": [f("Age", "eq", MATURE)]},
                       {"tool": "count", "table": "dlr", "filters": [f("Age", "eq", 3)]}]},
     "verdicts": ["No"]},
    {"id": "h20", "q": "How many DCC records have Area 'Griffith Park', and how many have no Area recorded at all?",
     "ref": {"calls": [{"tool": "count", "table": "dcc", "filters": [f("Area", "eq", "Griffith Park")]},
                       {"tool": "count", "table": "dcc", "filters": [f("Area", "null")]}]}},
]

if __name__ == "__main__":
    evaluate.run(CASES, Profile("dublin"), fake="--fake" in sys.argv)
