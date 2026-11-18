from pipeline import writer


def test_verify_drops_invented_and_appends_missing():
    results = [{"op": "count", "label": "count | register", "display": "6326"},
               {"op": "count", "label": "count | register | pflanzjahr is null", "display": "405"}]
    text = "There are 6,326 records. About 12.5% of them are old. No, unknown years are not new trees."
    out, notes = writer.verify(text, results, "q?")
    assert "12.5" not in out and "6,326" in out and "405" in out and "No, unknown" in out
    assert len(notes) == 2
