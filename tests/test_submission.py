"""Armado, compresión y validación del archivo de entrega."""
import re
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


def test_shrink_terminates_when_clipped_lines_stay_long():
    """Una línea de evidencia recortada a 80+80 sigue pasando de 130: antes el bucle no terminaba nunca."""
    import signal
    from pipeline import submission as S
    long_ev = "- SRC_x | " + "L" * 300 + " | " + "C" * 300
    entries = [{"id": f"q{i}", "text": "There are 5 records. " * 3, "answered": True,
                "evidence": [long_ev, long_ev]} for i in range(50)]
    signal.signal(signal.SIGALRM, lambda *a: (_ for _ in ()).throw(TimeoutError("shrink en bucle")))
    signal.alarm(10)
    try:
        total, _ = S.shrink(entries, max_bytes=1000)
    finally:
        signal.alarm(0)
    assert total > 1000                       # no cabe, pero termina
    assert all(len(ln) <= 200 for e in entries for ln in e["evidence"])


def test_shrink_reaches_target_with_many_long_answers():
    """Con ~440 respuestas largas el recorte de 80+80 no alcanza: los niveles más cortos lo bajan del tope."""
    from pipeline import submission as S
    ev = "- SRC_a9426f7d7b10 | filter: " + "Condition = 'Good (Normal Vitality. No Major Defects)' AND " * 3 + \
         " | " + "17 of 15962 records match and more words here " * 4
    entries = [{"id": f"{i:08x}", "text": f"There are {i} records with that value. That is 12.50% of all rows.",
                "answered": True, "evidence": [ev, ev, ev]} for i in range(440)]
    entries += [S.fallback(f"f{i:07x}", ["SRC_x"]) for i in range(160)]
    before = len(S.assemble(entries).encode())
    total, _ = S.shrink(entries)
    raw = S.assemble(entries).encode()
    assert before > S.TARGET >= len(raw) == total
    assert all(re.search(r"\d", e["text"]) for e in entries if e["answered"])      # los números se quedan
    assert all(ln.startswith("- SRC_a9426f7d7b10 | filter: ") for e in entries if e["answered"] for ln in e["evidence"])


def test_tidy_drops_sentences_that_answer_nothing():
    from pipeline import submission as S
    e = {"id": "q", "answered": True,
         "text": "In day, 31 rows with mnth = 7 have cnt = 5; 6; 7; 8; 9 (+26 more). "
                 "No records row with annee = 1999 was found. 12 of the 768 records have X6 = 3. "
                 "No: the counts are not bills.",
         "evidence": ["- SRC_a | filter: mnth = 7; field cnt | cnt = 5",
                      "- SRC_b | filter: annee = 1999 | no matching row",
                      "- SRC_c | filter: X6 = 3 | 12 of 768 records match"]}
    t = S.tidy(e)
    assert t["text"] == "12 of the 768 records have X6 = 3. No: the counts are not bills."
    assert t["evidence"] == ["- SRC_c | filter: X6 = 3 | 12 of 768 records match"]
    only = S.tidy({"id": "q", "answered": True, "text": "No t row with a = 'x' was found.",
                   "evidence": ["- SRC_b | filter: a = 'x' | no matching row"]})
    assert only["text"] == S.EMPTY_TEXT and only["evidence"]           # nunca una sección sin evidencia
    fb = S.fallback("q", ["SRC_z"])
    assert S.tidy(fb) is fb
    verdict = {"id": "q", "answered": True, "text": "No: no row of that kind was found.", "evidence": ["- S | a | b"]}
    assert S.tidy(verdict)["text"] == verdict["text"]                  # un veredicto 'No:' no se toca
