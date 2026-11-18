"""Los planes malos que produjo qwen3:1.7b en eval_v1 deben dar lo mismo que el plan correcto
después de pasar por las protecciones del ejecutor. Funciona con cualquier copia de los datos.
"""
import pytest

from pipeline import executor
from tools.profiles import Profile

POOR = "Poor (Low Vitality/Extensive Defects)"
YOUNG = "Young (Within first third of life span)"

CASES = [
    ("v01 named filter de otra tabla",
     "How many DCC records are marked Fallen?",
     {"calls": [{"tool": "count", "table": "dcc", "named_filter": "dlr_screen_keep",
                 "filters": [{"field": "Condition", "op": "eq", "value": "Fallen"}]}]},
     {"calls": [{"tool": "count", "table": "dcc", "filters": [{"field": "Condition", "op": "eq", "value": "Fallen"}]}]}),
    ("v02 denominador contradictorio",
     "What percentage of all DCC rows have no Spread value recorded?",
     {"calls": [{"tool": "percent", "table": "dcc", "filters": [{"field": "Spread", "op": "null"}],
                 "denominator": [{"field": "Spread", "op": "notnull"}]}]},
     {"calls": [{"tool": "percent", "table": "dcc", "filters": [{"field": "Spread", "op": "null"}], "denominator": []}]}),
    ("v04 tabla equivocada",
     "Species starting with 'Tilia '?",
     {"calls": [{"tool": "count", "table": "dlr", "filters": [{"field": "Species", "op": "startswith", "value": "Tilia "}]}]},
     {"calls": [{"tool": "count", "table": "dcc", "filters": [{"field": "Species", "op": "startswith", "value": "Tilia "}]}]}),
    ("v08 lookup con filtro en vez de key",
     "Read DLR record Tree_code 609",
     {"calls": [{"tool": "lookup", "table": "dlr", "filters": [{"field": "Tree_code", "op": "eq", "value": 609}]}]},
     {"calls": [{"tool": "lookup", "table": "dlr", "key": 609}]}),
    ("v11 denominador igual al numerador",
     "How many DCC records are Young, and what percentage of rows with a recorded Age is that?",
     {"calls": [{"tool": "percent", "table": "dcc", "filters": [{"field": "Age", "op": "eq", "value": YOUNG}],
                 "denominator": [{"field": "Age", "op": "eq", "value": YOUNG}]}]},
     {"calls": [{"tool": "percent", "table": "dcc", "filters": [{"field": "Age", "op": "eq", "value": YOUNG}],
                 "denominator": [{"field": "Age", "op": "notnull"}]}]}),
    ("v12 media categórica sin mapping",
     "Mean of the bands' lower edges for Poor trees?",
     {"calls": [{"tool": "mean", "table": "dcc", "field": "Height",
                 "filters": [{"field": "Condition", "op": "eq", "value": POOR}]}]},
     {"calls": [{"tool": "mean", "table": "dcc", "field": "Height", "mapping": "dcc_height_lower_edge",
                 "filters": [{"field": "Condition", "op": "eq", "value": POOR}]}]}),
]


@pytest.fixture(scope="module")
def P():
    return Profile("dublin")


@pytest.mark.parametrize("name,q,bad,good", CASES, ids=[c[0] for c in CASES])
def test_guard(P, name, q, bad, good):
    got = [r["display"] for r in executor.execute(executor.route(q, bad, P), P, q)]
    want = [r["display"] for r in executor.execute(good, P, q)]
    assert got == want


def test_router_allocation(P):
    q = "Under 400 hypothetical credits, which two streets cover the most Poor-and-tall screening records?"
    bad = {"calls": [{"tool": "count", "table": "dcc", "named_filter": "poor_tall"}]}
    plan = executor.route(q, bad, P)
    assert plan["calls"][0]["tool"] == "allocation" and plan["calls"][0]["budget"] == 400


def test_mapping_on_wrong_field(P):
    q = "Mean of the bands' lower edges?"
    bad = {"calls": [{"tool": "mean", "table": "dcc", "field": "StemDiameter", "mapping": "dcc_height_lower_edge"}]}
    good = {"calls": [{"tool": "mean", "table": "dcc", "field": "Height", "mapping": "dcc_height_lower_edge"}]}
    assert [r["display"] for r in executor.execute(bad, P, q)] == [r["display"] for r in executor.execute(good, P, q)]


def test_scope_and_dedupe(P):
    q = "Read DLR record Tree_code 609"
    bad = {"calls": [{"tool": "lookup", "table": "dlr", "key": 609},
                     {"tool": "lookup", "table": "dcc", "filters": [{"field": "ID", "op": "eq", "value": "609"}]},
                     {"tool": "lookup", "table": "dlr", "key": 609}]}
    assert len(executor.execute(bad, P, q)) == 1


def test_group_count_without_field(P):
    q = "Species starting with Tilia?"
    bad = {"calls": [{"tool": "group_count", "table": "dcc",
                      "filters": [{"field": "Species", "op": "startswith", "value": "Tilia "}]}]}
    r = executor.execute(bad, P, q)[0]
    assert r["op"] == "count"


# ---------------- Zúrich: patrones de error vistos con qwen3:1.7b ----------------
@pytest.fixture(scope="module")
def Z():
    return Profile("zurich")


def _crown_ids(Z, n=2):
    g, _ = Z.geo("crown")
    return list(g[g.is_valid]["baumnummer"].astype(str)[:n])


def test_z_extent_on_2d_with_area_wording(Z):
    a, b = _crown_ids(Z)
    q = f"What are the planar areas of crown features {a} and {b}?"
    r = executor.execute({"calls": [{"tool": "z_extent", "table": "crown", "ids": [a, b]}]}, Z, q)[0]
    assert r["op"] == "areas"


def test_year_threshold_from_question(Z):
    reg, _ = Z.table("register")
    a = str(reg["baumnummer"].iloc[5])
    q = f"Within 50 m of {a}, how many records and what share have a planting year of 2010 or later?"
    bad = {"calls": [{"tool": "within_radius", "table": "register", "anchor": a, "radius": 50, "prefixes": ["2010"]}]}
    good = {"calls": [{"tool": "within_radius", "table": "register", "anchor": a, "radius": 50,
                       "filters": [{"field": "pflanzjahr", "op": "ge", "value": 2010}]}]}
    assert [r["display"] for r in executor.execute(bad, Z, q)] == [r["display"] for r in executor.execute(good, Z, q)]


def test_count_with_denominator_splits(Z):
    reg, _ = Z.table("register")
    quart = reg["quartier"].iloc[0]
    q = f"How many register records are in quartier {quart}, and how many of those have no planting year?"
    bad = {"calls": [{"tool": "count", "table": "register", "filters": [{"field": "quartier", "op": "eq", "value": quart}],
                      "denominator": [{"field": "pflanzjahr", "op": "null"}]}]}
    assert len(executor.execute(bad, Z, q)) == 2


def test_value_on_wrong_field_and_most_common(Z):
    reg, _ = Z.table("register")
    street = reg["strasse"].dropna().iloc[0]
    q = f"Among register entries whose strasse is exactly {street}, which genus (baumgattunglat) is most common?"
    bad = {"calls": [{"tool": "distinct", "table": "register",
                      "filters": [{"field": "baumgattunglat", "op": "startswith", "value": street}]}]}
    good = {"calls": [{"tool": "group_count", "table": "register", "field": "baumgattunglat",
                       "filters": [{"field": "strasse", "op": "startswith", "value": street}]}]}
    assert [r["display"] for r in executor.execute(bad, Z, q)] == [r["display"] for r in executor.execute(good, Z, q)]


def test_ungrounded_filter_dropped(Z):
    q = "What percentage of all inventory rows have uuid_tlm3d recorded as null?"
    bad = {"calls": [{"tool": "percent", "table": "inventory",
                      "filters": [{"field": "uuid_tlm3d", "op": "null"}, {"field": "pflanzjahr", "op": "null"}]}]}
    good = {"calls": [{"tool": "percent", "table": "inventory", "filters": [{"field": "uuid_tlm3d", "op": "null"}],
                       "denominator": []}]}
    assert [r["display"] for r in executor.execute(bad, Z, q)] == [r["display"] for r in executor.execute(good, Z, q)]


def _same_display(bad, good, P, q):
    return [r["display"] for r in executor.execute(bad, P, q)] == [r["display"] for r in executor.execute(good, P, q)]


def test_second_id_in_wrong_param(Z):
    a, b = _crown_ids(Z)
    q = f"How big is the supplied crown footprint of {a} in square metres, compared with {b}?"
    bad = {"calls": [{"tool": "z_extent", "table": "crown", "ids": [a], "prefixes": [b]}]}
    good = {"calls": [{"tool": "areas", "table": "crown", "ids": [a, b]}]}
    assert _same_display(bad, good, Z, q)


def test_how_many_of_those_split(Z):
    reg, _ = Z.table("register")
    quart = reg["quartier"].iloc[0]
    q = f"How many register entries are in quartier {quart}, and how many of those are kategorie Strassenbaum?"
    bad = {"calls": [{"tool": "count", "table": "register", "filters": [
        {"field": "quartier", "op": "eq", "value": quart}, {"field": "kategorie", "op": "eq", "value": "Strassenbaum"}]}]}
    good = {"calls": [{"tool": "count", "table": "register", "filters": [{"field": "quartier", "op": "eq", "value": quart}]},
                      {"tool": "count", "table": "register", "filters": [
                          {"field": "quartier", "op": "eq", "value": quart},
                          {"field": "kategorie", "op": "eq", "value": "Strassenbaum"}]}]}
    assert _same_display(bad, good, Z, q)


def test_value_prefixed_with_column_name(Z):
    reg, _ = Z.table("register")
    street = reg["strasse"].dropna().iloc[0]
    q = f"On strasse {street}, which German tree name (baumnamedeu) is most frequent in the register?"
    bad = {"calls": [{"tool": "distinct", "table": "register",
                      "filters": [{"field": "baumnamedeu", "op": "startswith", "value": f"strasse {street}"}]}]}
    good = {"calls": [{"tool": "group_count", "table": "register", "field": "baumnamedeu",
                       "filters": [{"field": "strasse", "op": "startswith", "value": street}]}]}
    assert _same_display(bad, good, Z, q)


def test_text_value_on_numeric_field_and_mean_field(Z):
    q = "What is the mean hoehe of inventory entries with status unbekannt?"
    bad = {"calls": [{"tool": "mean", "table": "inventory", "filters": [{"field": "hoehe", "op": "eq", "value": "unbekannt"}]}]}
    good = {"calls": [{"tool": "mean", "table": "inventory", "field": "hoehe",
                       "filters": [{"field": "status", "op": "eq", "value": "unbekannt"}]}]}
    assert _same_display(bad, good, Z, q)
