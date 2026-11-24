"""Medición del perfil automático en familias sin perfil escrito a mano.

Preguntas propias (NO del Test) con su plan de referencia. Para cada familia se arma el perfil automático
con los Source_IDs que trae el Test.csv para esa familia (solo los IDs, nunca preguntas ni respuestas) y se
compara: ¿el plan del modelo da los mismos números que el plan de referencia? ¿el texto los dice?

Uso:  python -u scripts/eval_auto.py [--fake] [--family bike]
  --fake   usa los planes de referencia en vez del modelo (prueba que alias y herramientas existen)
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd  # noqa: E402

from pipeline import evaluate  # noqa: E402
from tools import loaders  # noqa: E402
from tools.autoprofile import AutoProfile  # noqa: E402


def f(field, op, value=None):
    return {"field": field, "op": op, **({"value": value} if value is not None else {})}


# familia -> (Source_ID ancla para encontrar sus Source_IDs en Test.csv, casos)
FAMILIES = {
    "bike": ("SRC_7824dbf4af25", [
        {"id": "b1", "q": "How many daily records are in season 3, and what is their total of casual rentals?",
         "ref": {"calls": [{"tool": "count", "table": "day", "filters": [f("season", "eq", 3)]},
                           {"tool": "sum", "table": "day", "field": "casual", "filters": [f("season", "eq", 3)]}]}},
        {"id": "b2", "q": "What is the mean registered count on holidays in the daily file?",
         "ref": {"calls": [{"tool": "mean", "table": "day", "field": "registered", "filters": [f("holiday", "eq", 1)]}]}},
        {"id": "b3", "q": "In the hourly file, which hour label has the most records with weathersit 3?",
         "ref": {"calls": [{"tool": "group_count", "table": "hour", "field": "hr", "filters": [f("weathersit", "eq", 3)]}]}},
        {"id": "b4", "q": "What was the total cnt in month 7 of yr 0 and in month 7 of yr 1, in the daily file? "
                          "Give the percentage change from yr 0.",
         "ref": {"calls": [{"tool": "sum", "table": "day", "field": "cnt", "filters": [f("mnth", "eq", 7), f("yr", "eq", 0)]},
                           {"tool": "sum", "table": "day", "field": "cnt", "filters": [f("mnth", "eq", 7), f("yr", "eq", 1)]}]}},
        {"id": "b5", "q": "Which daily record has the lowest cnt, and on what date?",
         "ref": {"calls": [{"tool": "extreme", "table": "day", "field": "cnt", "which": "min"}]}},
    ]),
    "toulouse": ("SRC_6eef62cb8980", [
        {"id": "t1", "q": "What were the annual plantings in 2021 and in 2023? Give the percentage change from 2021.",
         "ref": {"calls": [{"tool": "value", "table": "records", "field": "plantes_annuel", "filters": [f("annee", "eq", 2021)]},
                           {"tool": "value", "table": "records", "field": "plantes_annuel", "filters": [f("annee", "eq", 2023)]}]}},
        {"id": "t2", "q": "What is the sum of the annual net balance (solde_net_annuel) over all entries?",
         "ref": {"calls": [{"tool": "sum", "table": "records", "field": "solde_net_annuel"}]}},
    ]),
    "durban": ("SRC_2c00a653a45a", [
        {"id": "d1", "q": "What was the Maximum kVA in 1990/1991 and in 2000/2001? How much did it change?",
         "ref": {"calls": [{"tool": "value", "table": "electricity_use_ethekwini", "field": "Maximum kVA",
                            "filters": [f("Year", "eq", "1990/1991")]},
                           {"tool": "value", "table": "electricity_use_ethekwini", "field": "Maximum kVA",
                            "filters": [f("Year", "eq", "2000/2001")]}]}},
        {"id": "d2", "q": "Which period in the utility series has the highest Percent loss (%)?",
         "ref": {"calls": [{"tool": "extreme", "table": "electricity_use_ethekwini", "field": "Percent loss (%)"}]}},
        {"id": "d3", "q": "What is the mean Number of customers over all supplied periods of the utility series?",
         "ref": {"calls": [{"tool": "mean", "table": "electricity_use_ethekwini", "field": "Number of customers"}]}},
        {"id": "d4", "q": "What average FBE claims figure is reported for 12/13?",
         "ref": {"calls": [{"tool": "value", "table": "annual_free_basic_electricity_claims",
                            "field": "Average FBE claims per year", "filters": [f("Year", "eq", "12/13")]}]}},
    ]),
    "energy_efficiency": ("SRC_a08b15340994", [
        {"id": "s1", "q": "In the CSV, how many rows have X6 = 3 and X8 = 0, and what is their mean Y2?",
         "ref": {"calls": [{"tool": "count", "table": "data", "filters": [f("X6", "eq", 3), f("X8", "eq", 0)]},
                           {"tool": "mean", "table": "data", "field": "Y2", "filters": [f("X6", "eq", 3), f("X8", "eq", 0)]}]}},
        {"id": "s2", "q": "In the workbook, which X5 value occurs in the most rows?",
         "ref": {"calls": [{"tool": "group_count", "table": "enb2012_data", "field": "X5"}]}},
        {"id": "s3", "q": "What is the highest Y1 in the workbook, and in how many rows does it occur?",
         "ref": {"calls": [{"tool": "extreme", "table": "enb2012_data", "field": "Y1"}]}},
    ]),
    "berlin": ("SRC_ec49599c7cc8", [
        {"id": "g1", "q": "How many street-tree records have gattung Acer, and what share of the street layer is that?",
         "ref": {"calls": [{"tool": "count", "table": "strassenbaeume", "filters": [f("gattung", "eq", "Acer")]},
                           {"tool": "percent", "table": "strassenbaeume", "filters": [f("gattung", "eq", "Acer")],
                            "denominator": []}]}},
        {"id": "g2", "q": "What is the tallest baumhoehe among the park trees, and which record has it?",
         "ref": {"calls": [{"tool": "extreme", "table": "anlagenbaeume", "field": "baumhoehe"}]}},
        {"id": "g3", "q": "Across both layers together, how many trees have no pflanzjahr recorded?",
         "ref": {"calls": [{"tool": "count", "table": "combined", "filters": [f("pflanzjahr", "null")]}]}},
        {"id": "g4", "q": "What is the mean crown diameter (kronedurch) of the street trees on Rochstraße?",
         "ref": {"calls": [{"tool": "mean", "table": "strassenbaeume", "field": "kronedurch",
                            "filters": [f("strname", "eq", "Rochstraße")]}]}},
    ]),
}


def family_sources(anchor):
    test = pd.read_csv(os.path.join(loaders.DATA, "Test.csv"))
    for s in test["Source_IDs"]:
        ids = json.loads(s)
        if anchor in ids:
            return ids
    raise SystemExit(f"no encuentro {anchor} en Test.csv")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fake", action="store_true")
    ap.add_argument("--family", choices=list(FAMILIES))
    a = ap.parse_args()
    tot = {"plan": 0, "n": 0, "text": 0, "text_n": 0, "invented": 0}
    for fam, (anchor, cases) in FAMILIES.items():
        if a.family and fam != a.family:
            continue
        P = AutoProfile(family_sources(anchor))
        print(f"\n######## {fam}: tablas {list(P._t)}")
        r = evaluate.run(cases, P, fake=a.fake)
        tot["plan"] += r["plan"]
        tot["n"] += len(cases)
        for k in ("text", "text_n", "invented"):
            tot[k] += r[k]
    print(f"\n=== TOTAL plan {tot['plan']}/{tot['n']}" + ("" if a.fake else
          f" | texto con los números {tot['text']}/{tot['text_n']} | números inventados {tot['invented']}") + " ===")


if __name__ == "__main__":
    main()
