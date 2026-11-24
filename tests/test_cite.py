"""Cita de convenciones: términos desde lo calculado, solo guías de organizadores, sin repetir notas."""
from pipeline import cite, writer
from tools import guides as G

ANALYSIS = """Count records unless asked for distinct source keys. A null-only check differs from a trim-aware \
missing-text check. For these tasks blank text means empty after removing ordinary leading/trailing spaces.

The Poor-and-tall screening rule selects Condition exactly "Poor", and excludes Species exactly "Suitable Planting Location".

Report requested means and percentages to two decimals."""
META = "This dataset provides Tree data with columns Condition, Street, Height and Species and counts records."


def _idx():
    return G.GuideIndex(G.split_units(ANALYSIS, "SRC_an", "Analysis.md")
                        + G.split_units(META, "SRC_meta", "DCC_metadata.json notes", kind="meta"))


def test_terms_weight_filters_over_operations():
    spec, gen = cite.terms_for([{"op": "count", "filters": [{"op": "blank"}]}, {"op": "percent", "filters": []}])
    assert "blank" in spec and "null" in spec and gen == "count records percentages decimals"


def test_blank_count_cites_the_trim_aware_sentence():
    h = cite.convention(_idx(), [{"op": "count", "filters": [{"field": "Site", "op": "blank"}]}], {"SRC_an", "SRC_meta"})
    assert h["source_id"] == "SRC_an" and h["text"].startswith(("A null-only", "For these tasks blank"))


def test_question_words_do_not_pull_unused_rules_and_metadata_is_never_cited():
    # una cuenta simple (sin filtro con nombre) no debe citar la regla Poor-and-tall ni los metadatos
    # (corpus de prueba diminuto: los idf son bajos, por eso min_score=0; en el índice real pasan de 3)
    h = cite.convention(_idx(), [{"op": "count", "filters": [{"field": "Species", "op": "eq", "value": "x"}]}],
                        {"SRC_an", "SRC_meta"}, min_score=0)
    assert h["text"] == "Count records unless asked for distinct source keys."


def test_named_filter_label_finds_its_rule_and_exclude_skips_cited_text():
    res = [{"op": "count", "filters": [], "named_label": "Poor-and-tall screening rule"}]
    h = cite.convention(_idx(), res, {"SRC_an"})
    assert h["text"].startswith("The Poor-and-tall screening rule")
    h2 = cite.convention(_idx(), res, {"SRC_an"}, exclude={h["text"]})
    assert h2 is None or h2["text"] != h["text"]


def test_no_terms_or_no_guides_means_no_citation():
    assert cite.convention(_idx(), [{"op": "max"}], {"SRC_an"}) is None
    assert cite.convention(_idx(), [{"op": "count"}], set()) is None


def test_evidence_uses_convention_instead_of_generic_line():
    class P:
        cfg = {"analysis_source": "SRC_an"}

    res = [{"evidence": [{"source_id": "SRC_t", "locator": "filter: Site is blank", "claim": "12 of 99 records match"}]}]
    conv = {"source_id": "SRC_an", "file": "Analysis.md", "para": 1, "text": "A null-only check differs from a trim-aware check."}
    out = writer.evidence_lines(res, P(), [], conv=conv)
    assert out == ["- SRC_t | filter: Site is blank | 12 of 99 records match",
                   "- SRC_an | Analysis.md ¶1 | A null-only check differs from a trim-aware check."]
    assert not any("analysis conventions file" in x for x in out)
    # sin frase de convención y sin nota de veredicto, queda la línea genérica de siempre
    assert "analysis conventions file" in writer.evidence_lines(res, P(), [])[-1]


def test_expand_adds_synonyms_once_and_search_filters_kinds():
    q = G.expand("empty empty rows")
    assert q.count("null") == 1 and "blank" in q
    idx = _idx()
    assert all(h["kind"] == "guide" for h in idx.search("condition street height species", None, k=5, kinds={"guide"}))
    assert any(h["kind"] == "meta" for h in idx.search("condition street height species", None, k=5))
