from pipeline import verdicts, writer


def test_detect_yes_no_parts():
    q = ("How many DCC rows are labelled Suitable Planting Location? Do any of those also have a Fair condition, "
         "and would that make them confirmed existing trees?")
    parts = verdicts.yes_no_parts(q)
    assert len(parts) == 1 and parts[0].startswith("Do any")
    q2 = "What is the stored maximum and which records attain it? Would we be justified in changing it?"
    assert verdicts.yes_no_parts(q2) == ["Would we be justified in changing it?"]
    q3 = "Give the count and explain why searching only GRIFFITH AVENUE gives a smaller number."
    assert verdicts.yes_no_parts(q3) == []
    q4 = "How many remain, and does this substitute for a boundary overlay?"
    assert verdicts.yes_no_parts(q4) == ["Does this substitute for a boundary overlay?"]


def test_verdict_appended_when_missing():
    res = [{"op": "count", "label": "count", "display": "61"}]
    v = [{"part": "Would that make them confirmed trees?", "verdict": "No", "reason": "Labels are inventory categories"}]
    out, notes = writer.verify("There are 61 such rows.", res, "q?", v)
    assert "No: Labels are inventory categories." in out
