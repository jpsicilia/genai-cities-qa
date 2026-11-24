from pipeline import verdicts, writer


def test_detect_yes_no_parts():
    q = ("How many rows are labelled Planting pit? Do any of those also have a Good status, "
         "and would that make them verified living plants?")
    parts = verdicts.yes_no_parts(q)
    assert len(parts) == 1 and parts[0].startswith("Do any")
    q2 = "What is the largest stored width and which rows reach it? Would we be justified in editing it?"
    assert verdicts.yes_no_parts(q2) == ["Would we be justified in editing it?"]
    q3 = "Give the total and explain why a search for ELM ROAD alone returns fewer rows."
    assert verdicts.yes_no_parts(q3) == []
    q4 = "How many are left, and does this replace a proper spatial join?"
    assert verdicts.yes_no_parts(q4) == ["Does this replace a proper spatial join?"]


def test_verdict_appended_when_missing():
    res = [{"op": "count", "label": "count", "display": "61"}]
    v = [{"part": "Would that make them confirmed trees?", "verdict": "No", "reason": "Labels are inventory categories"}]
    out, notes = writer.verify("There are 61 such rows.", res, "q?", v)
    assert "No: Labels are inventory categories." in out


def test_verdict_cites_the_chosen_guide_note(monkeypatch):
    import json
    from pipeline import llm

    def fake_chat(messages, budget, schema=None, max_tokens=800):
        assert "note" in schema["properties"] and "[2] Metadata" in messages[-1]["content"]
        return json.dumps({"verdict": "No", "reason": "Update dates are not observation dates", "note": "2"})

    monkeypatch.setattr(llm, "chat", fake_chat)

    class P:
        cfg = {"rules_for_llm": []}

    notes = [{"source_id": "SRC_a", "file": "Analysis.md", "para": 1, "text": "Counts are records."},
             {"source_id": "SRC_g", "file": "SourceGuide.md", "para": 3,
              "text": "Metadata resource/update dates are not per-tree observation dates."}]
    v = verdicts.ask("Could the portal's update date stand in for that?", "q", "facts", P(), llm.Budget(), notes)
    assert v["verdict"] == "No"
    assert v["evidence"] == {"source_id": "SRC_g", "locator": "SourceGuide.md ¶3",
                             "claim": "Metadata resource/update dates are not per-tree observation dates.",
                             "text": "Metadata resource/update dates are not per-tree observation dates."}


def test_evidence_lines_put_verdict_note_after_numbers():
    class P:
        cfg = {"analysis_source": "SRC_an"}

    res = [{"evidence": [{"source_id": "SRC_t", "locator": f"filter {i}", "claim": f"{i} records"} for i in range(4)]}]
    v = [{"evidence": {"source_id": "SRC_g", "locator": "SourceGuide.md ¶3", "claim": "dates are not observations"}}]
    out = writer.evidence_lines(res, P(), v)
    assert len(out) == 4 and out[2].startswith("- SRC_g | SourceGuide.md ¶3")
    assert not any("SRC_an" in x for x in out)   # con nota citada, no hace falta la línea genérica
