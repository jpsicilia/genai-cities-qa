"""Redacción determinista: plantillas por herramienta y explicación de la normalización."""
from pipeline import compose, llm


def R(**kw):
    base = {"table": "dcc", "filters_text": "all records", "display": ""}
    base.update(kw)
    return base


def test_count_and_percents_share_the_filter_once():
    f = "Condition = 'Poor'"
    res = [R(op="count", value=1122, total_rows=15962, filters_text=f, display="1122"),
           R(op="percent", numerator=1122, denominator=15962, filters_text=f, den_text="all rows", display="7.03%"),
           R(op="percent", numerator=1122, denominator=15015, filters_text=f, den_text="Condition is not null",
             display="7.47%")]
    txt = compose.compose("q", res, [], type("P", (), {"cfg": {}})(), llm.Budget(0, 0))
    assert txt.count(f) == 1 and "7.03% of 15962" in txt and "7.47% of 15015" in txt and "Condition is not null" in txt


def test_normalisation_explanation_from_spelling_split():
    res = [R(op="group_count", field="Street", value=[("griffith avenue", 1005)], display="griffith avenue: 1005",
             by_spelling={"GRIFFITH AVENUE": 1003, "Griffith Avenue": 2}),
           R(op="count", value=1003, total_rows=15962, filters_text="Street = 'GRIFFITH AVENUE'",
             filters=[{"field": "Street", "op": "eq", "value": "GRIFFITH AVENUE"}], display="1003")]
    txt = compose.compose("Explain why it is smaller", res, [], type("P", (), {"cfg": {}})(), llm.Budget(0, 0))
    assert "misses the 2 record(s) spelled 'Griffith Avenue'" in txt and "1005" in txt


def test_why_without_deterministic_explanation_asks_the_model(monkeypatch):
    calls = []

    def fake_chat(messages, budget, schema=None, max_tokens=800):
        calls.append(messages)
        return "**Because** the two fields come from different coding schemes."

    monkeypatch.setattr(llm, "chat", fake_chat)
    res = [R(op="count", value=7, total_rows=100, filters_text="status = 'Strassenbaum (A)'", display="7")]
    txt = compose.compose("Why do the two counts differ?", res, [], type("P", (), {"cfg": {}})(), llm.Budget())
    assert len(calls) == 1 and "Because the two fields" in txt and "*" not in txt


def test_record_sentence_skips_key_and_marks_blank():
    res = [R(op="lookup", table="dlr", id_field="Tree_code",
             value=[{"_id": 1, "Tree_code": 607, "Act_height": 15.0, "Site_name": "  ", "Age": 0}])]
    txt = compose.compose("What are its Act_height and Age?", res, [], type("P", (), {"cfg": {}})(), llm.Budget(0, 0))
    assert txt.startswith("DLR record Tree_code 607: Act_height 15; Age 0") and "Site_name blank" in txt
    assert txt.count("Tree_code") == 1


def test_verdicts_are_appended():
    res = [R(op="count", value=61, total_rows=15962, filters_text="Species = 'Suitable Planting Location'", display="61")]
    v = [{"verdict": "No", "reason": "The label marks a planting location, not a tree"}]
    txt = compose.compose("q?", res, v, type("P", (), {"cfg": {}})(), llm.Budget(0, 0))
    assert txt.endswith("No: The label marks a planting location, not a tree.")
