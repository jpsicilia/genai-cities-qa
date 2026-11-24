"""Perfil automático sobre réplicas sintéticas de familias reales (formatos y rarezas del volcado de esquemas)."""
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import autofix  # noqa: E402

from pipeline import answer, derived, llm  # noqa: E402
from tools import autoload as A  # noqa: E402
from tools import guides, loaders  # noqa: E402
from tools.autoprofile import AutoProfile, has_tables  # noqa: E402


@pytest.fixture()
def fams(tmp_path, monkeypatch):
    f = autofix.build(str(tmp_path))
    monkeypatch.setattr(loaders, "DATA", str(tmp_path))
    for fn in (loaders.manifest, loaders.load_json, loaders.load_table, loaders.load_geo, guides.default_index):
        fn.cache_clear()
    yield f
    for fn in (loaders.manifest, loaders.load_json, loaders.load_table, loaders.load_geo, guides.default_index):
        fn.cache_clear()


def F(field, op, value=None):
    return {"field": field, "op": op, **({"value": value} if value is not None else {})}


def run(fam_sids, question, calls, monkeypatch):
    def fake(messages, budget, schema=None, max_tokens=800):
        budget.calls += 1
        if schema and "verdict" in schema.get("properties", {}):
            return json.dumps({"verdict": "No", "reason": "r", **({"note": "none"} if "note" in schema["properties"] else {})})
        return json.dumps({"calls": calls}) if schema else "x"
    monkeypatch.setattr(llm, "chat", fake)
    P = AutoProfile(fam_sids)
    return answer.answer("Q", question, P, source_ids=fam_sids)


# ------------------------------------------------------------------ carga
def test_formats_are_read_faithfully(fams):
    m = AutoProfile(fams["montreal"]).sample("outremont")
    assert m["EMP_NO"].tolist()[0] == "0000001"                 # código con ceros: texto
    assert m["DHP"].tolist() == [12.0, 0.0, 86.5]               # "12,00" con coma decimal
    assert m["Emplacement"].tolist()[0] == "façade"             # latin-1
    e = AutoProfile(fams["electricity"]).sample("eightclients")
    assert e["MT_162"].tolist()[0] == 150.5 and str(e["timestamp"].dtype) != "float64"
    t = AutoProfile(fams["toulouse"])
    assert list(t._t) == ["records"] and "type" in t.sample("records").columns   # BOM fuera del nombre
    assert "SRC_t2" in t.cfg["tables"]["records"]["description"]               # JSON = misma tabla


def test_spreadsheet_keeps_excel_rows_and_letters(fams):
    P = AutoProfile(fams["durban"])
    df, info = P.sample("electricity_use"), P.info("electricity_use")
    assert df["_row"].tolist() == [2, 3, 4] and info["letters"]["Number of customers"] == "E"
    assert P.cfg["tables"]["electricity_use"]["key"] == "Year"


def test_nested_json_lists_become_child_tables(fams):
    P = AutoProfile(fams["rnb"])
    assert {"records", "records_addresses", "records_ext_ids"} <= set(P._t)
    ad = P.sample("records_addresses")
    assert ad["rnb_id"].tolist() == ["AAAA1111", "AAAA1111", "BBBB2222"]
    assert "metadata_data_variables" in AutoProfile(fams["uci_meta"])._t


def test_layers_combine_only_when_keys_are_disjoint(fams):
    assert "combined" in AutoProfile(fams["berlin"])._t
    assert "combined" not in AutoProfile(fams["bike"])._t          # day/hour: claves que se pisan


def test_focus_picks_the_table_the_question_names(fams):
    P = AutoProfile(fams["bike"])
    assert P.focus("How many hourly rows have hr 3 on 2012-02-29?")[0] == "hour"
    assert has_tables(fams["bike"]) and not has_tables(["SRC_b3"])  # solo la guía: nada tabular


# ------------------------------------------------------------------ respuestas
def test_value_cells_and_derived_change(fams, monkeypatch):
    md, info = run(fams["durban"], "Compare 2006/2007 with 2008/2009: percentage change in Number of customers?",
                   [{"tool": "value", "table": "electricity_use", "field": "Number of customers",
                     "filters": [F("Year", "eq", "2006/2007")]},
                    {"tool": "value", "table": "electricity_use", "field": "Number of customers",
                     "filters": [F("Year", "eq", "2008/2009")]}], monkeypatch)
    assert "500000 (cell E2)" in md and "525000 (cell E4)" in md and "+5.00%" in md
    assert "sheet 'Sheet1' cell E2" in md and not info["writer_notes"]


def test_sum_with_numeric_filter_written_as_text(fams, monkeypatch):
    md, _ = run(fams["bike"], "Total cnt for yr 0 and yr 1, and the change?",
                [{"tool": "sum", "table": "day", "field": "cnt", "filters": [F("yr", "eq", "0")]},
                 {"tool": "sum", "table": "day", "field": "cnt", "filters": [F("yr", "eq", 1)]}], monkeypatch)
    assert "yr = 0 is 1100" in md and "yr = 1 is 2860" in md and "+160.00%" in md


def test_iso_time_window_and_min(fams, monkeypatch):
    md, _ = run(fams["electricity"], "Lowest MT_162 on 2012-01-16 and the MT_162 sum before 07:00?",
                [{"tool": "extreme", "table": "eightclients", "field": "MT_162",
                  "filters": [F("timestamp", "startswith", "2012-01-16")]},
                 {"tool": "sum", "table": "eightclients", "field": "MT_162",
                  "filters": [F("timestamp", "lt", "2012-01-16 07:00:00")]}], monkeypatch)
    assert "minimum MT_162" in md and "150.5" in md and "is 150.50" in md


def test_group_share_on_combined_layers_cites_both_sources(fams, monkeypatch):
    md, _ = run(fams["berlin"], "Which genus is most common across both layers? Give its share.",
                [{"tool": "group_count", "table": "combined", "field": "gattung"}], monkeypatch)
    assert "'Tilia' with 5 records (62.50% of 8 records)" in md
    assert "SRC_g1 |" in md and "SRC_g2 |" in md


def test_ratio_is_derived_when_asked():
    res = [{"op": "sum", "value": 3729838.369, "field": "consumption", "table": "t", "filters_text": "a"},
           {"op": "sum", "value": 92842.0, "field": "points", "table": "t", "filters_text": "a"}]
    d = derived.derive("What is consumption per delivery point?", res)
    assert d and d[0]["kind"] == "ratio" and abs(d[0]["ratio"] - 40.17) < 0.01


def test_no_derived_without_comparison_words():
    res = [{"op": "count", "value": 3, "table": "t"}, {"op": "count", "value": 5, "table": "t"}]
    assert derived.derive("How many records have X, and how many have Y?", res) == []


def test_dry_run_reports_auto_coverage(fams, tmp_path):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    r = subprocess.run([sys.executable, os.path.join(root, "scripts", "make_submission.py"), "--auto", "--dry-run"],
                       env={**os.environ, "GENAI_DATA": str(tmp_path)}, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "'auto': " in r.stdout


def test_reader_skips_prose_txt(tmp_path):
    p = tmp_path / "guide.txt"
    p.write_text("This is a guide.\nIt has sentences, commas, and no table.\nAnother line here.\n", encoding="utf-8")
    assert A.read_any(str(p)) == []


def test_family_without_readable_tables_fails_fast(fams, monkeypatch):
    calls = []
    monkeypatch.setattr(llm, "chat", lambda *a, **k: calls.append(1) or "{}")
    P = AutoProfile(["SRC_b3"])                     # solo una guía: ninguna tabla
    with pytest.raises(ValueError):
        answer.answer("Q", "How many?", P, source_ids=["SRC_b3"])
    assert not calls                                # no se llamó al modelo
