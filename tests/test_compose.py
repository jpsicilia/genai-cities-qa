"""Redacción determinista: plantillas por herramienta y explicación de la normalización."""
from pipeline import compose, llm


def R(**kw):
    base = {"table": "dcc", "filters_text": "all records", "display": ""}
    base.update(kw)
    return base


POOR = {"field": "Condition", "op": "eq", "value": "Poor"}
NOTNULL = {"field": "Condition", "op": "notnull"}
P0 = type("P", (), {"cfg": {}})()


def test_count_and_percents_share_the_filter_once():
    f = "Condition = 'Poor'"
    res = [R(op="count", value=120, total_rows=1600, filters_text=f, filters=[POOR], display="120"),
           R(op="percent", numerator=120, denominator=1600, filters_text=f, filters=[POOR], den_text="all rows",
             den_filters=[], display="7.50%"),
           R(op="percent", numerator=120, denominator=1500, filters_text=f, filters=[POOR],
             den_text="Condition is not null", den_filters=[NOTNULL], display="8.00%")]
    txt = compose.compose("q", res, [], P0, llm.Budget(0, 0))
    assert txt.startswith("120 of the 1600 DCC records have Condition = 'Poor'.")
    assert "That is 7.50% of all 1600 DCC rows (denominator: all rows)." in txt
    assert "Using only the 1500 DCC records with a recorded Condition (not null) as the denominator, it is 8.00%." in txt
    assert txt.count(f) == 1


def test_percent_alone_names_its_denominator_and_drops_repeated_condition():
    res = [R(op="percent", numerator=120, denominator=1500, filters_text="Condition is not null AND Condition = 'Poor'",
             filters=[NOTNULL, POOR], den_text="Condition is not null", den_filters=[NOTNULL], display="8.00%")]
    txt = compose.compose("q", res, [], P0, llm.Budget(0, 0))
    assert txt == ("120 of the 1500 DCC records with a recorded Condition (not null) have Condition = 'Poor', "
                   "which is 8.00%.")


def test_blank_count_with_prefix_split_reads_as_a_sentence():
    res = [R(op="count", table="inventory", value=700, total_rows=1500, display="700",
             filters=[{"field": "uuid_tlm3d", "op": "blank"}], filters_text="uuid_tlm3d is blank (null/empty after trim)",
             by_prefix={"BK_": 700, "TLM3D_": 0}, prefix_key="baumnummer")]
    txt = compose.compose("q", res, [], P0, llm.Budget(0, 0))
    assert txt == ("700 of the 1500 inventory records have a blank uuid_tlm3d (null or empty after trimming). "
                   "By baumnummer prefix, all 700 are BK_ records and none are TLM3D_ records.")


def test_named_filter_is_named_once_by_its_label():
    tall = [{"field": "Condition", "op": "eq", "value": "Poor"}, {"field": "Height", "op": "in", "value": ["Over 25m"]}]
    res = [R(op="count", value=37, total_rows=1600, display="37", filters=tall + [{"field": "Street", "op": "nonblank"}],
             filters_text="x", named_filter="poor_tall", n_named=2, named_label="Poor-and-tall screening rule")]
    txt = compose.compose("q", res, [], P0, llm.Budget(0, 0))
    assert txt == ("37 of the 1600 DCC records pass the Poor-and-tall screening rule and have a non-blank Street "
                   "(after trimming).")


def test_normalisation_explanation_from_spelling_split():
    res = [R(op="group_count", field="Street", value=[("elm road", 52)], display="elm road: 52",
             filters=[], by_spelling={"ELM ROAD": 50, "Elm Road": 2}),
           R(op="count", value=50, total_rows=1600, filters_text="Street = 'ELM ROAD'",
             filters=[{"field": "Street", "op": "eq", "value": "ELM ROAD"}], display="50")]
    txt = compose.compose("Explain why it is smaller", res, [], type("P", (), {"cfg": {}})(), llm.Budget(0, 0))
    assert txt.startswith("Ignoring letter case and surrounding spaces, the most frequent Street among DCC records is "
                          "'ELM ROAD' with 52 records ('ELM ROAD' 50, 'Elm Road' 2).")
    assert "misses the 2 records spelled 'Elm Road'; ignoring letter case and surrounding spaces merges them." in txt


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
    res = [R(op="count", value=9, total_rows=1600, filters_text="Species = 'Planting pit'", display="9")]
    v = [{"verdict": "No", "reason": "The label marks a planting location, not a tree"}]
    txt = compose.compose("q?", res, v, type("P", (), {"cfg": {}})(), llm.Budget(0, 0))
    assert txt.endswith("No: The label marks a planting location, not a tree.")
