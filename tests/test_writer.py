from pipeline import writer


def test_verify_drops_invented_and_appends_missing():
    results = [{"op": "count", "label": "count | register", "display": "6326"},
               {"op": "count", "label": "count | register | pflanzjahr is null", "display": "405"}]
    text = "There are 6,326 records. About 12.5% of them are old. No, unknown years are not new trees."
    out, notes = writer.verify(text, results, "q?")
    assert "12.5" not in out and "6,326" in out and "405" in out and "No, unknown" in out
    assert len(notes) == 2


def test_prefix_zero_said_as_none_is_not_a_missing_number():
    from pipeline import numbers as N
    r = {"op": "count", "display": "200 (by baumnummer prefix: BK_ 200, TLM3D_ 0)", "by_prefix": {"BK_": 200, "TLM3D_": 0}}
    assert N.required_tokens([r]) == {"200"}
    out, notes = writer.verify("200 records. By baumnummer prefix, all 200 are BK_ records and none are TLM3D_ records.",
                               [r], "q")
    assert "Computed values" not in out and not notes
