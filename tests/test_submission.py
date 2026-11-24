"""Armado, compresión y validación del archivo de entrega."""
from pipeline import submission as SUB

IDS = ["a-1", "b-2", "c-3"]


def entries():
    long_ev = [f"- SRC_x | filter {i} {'x' * 120} | claim {i} {'y' * 120}" for i in range(4)]
    return [
        {"id": "a-1", "answered": True, "evidence": long_ev,
         "text": "There are 61 rows. This sentence only adds colour. No: labels are categories. Extra filler words here."},
        SUB.fallback("b-2", ["SRC_b"]),
        {"id": "c-3", "answered": True, "text": "## Heading\nThe mean is 8.27.", "evidence": ["- SRC_c | f | 8.27"]},
    ]


def test_assembled_file_is_valid():
    doc = SUB.assemble(entries())
    errs, stats = SUB.validate(doc.encode(), IDS)
    assert errs == [] and stats["sections"] == 3
    assert doc.startswith("# Submission\n\n## a-1\n\n") and "\n## Heading" not in doc


def test_shrink_reaches_budget_without_losing_numbers_or_verdicts():
    es = entries()
    before = len(SUB.assemble(es).encode())
    total, steps = SUB.shrink(es, before - 500)
    doc = SUB.assemble(es)
    assert total == len(doc.encode()) and total <= before - 500 and steps > 0
    assert "61 rows" in doc and "No: labels are categories" in doc and "8.27" in doc
    assert len(es[0]["evidence"]) <= 2


def test_validator_catches_common_problems():
    good = SUB.assemble(entries()).encode()
    assert any("BOM" in e for e in SUB.validate(b"\xef\xbb\xbf" + good, IDS)[0])
    assert any("CR" in e for e in SUB.validate(good.replace(b"\n", b"\r\n"), IDS)[0])
    assert any("faltan" in e for e in SUB.validate(good, IDS + ["d-4"])[0])
    assert any("orden" in e for e in SUB.validate(good, ["c-3", "b-2", "a-1"])[0])
    assert any("máximo" in e for e in SUB.validate(good, IDS, max_bytes=100)[0])
    broken = good.replace(b"### Evidence\n- SRC_c | f | 8.27", b"### Evidence\nno bullets")
    assert any("viñetas" in e for e in SUB.validate(broken, IDS)[0])
