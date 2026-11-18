"""Redactor: el LLM escribe la respuesta con los números YA calculados.
La sección Evidence la arma Python, no el modelo (así nunca sale mal formateada).
"""
import re

from pipeline import numbers as N
from pipeline.verdicts import sentence as _vsentence


def _facts(results):
    lines = []
    for i, r in enumerate(results, 1):
        extra = []
        for k in ("total_rows", "numerator", "denominator", "n_used", "n_removed", "n_hits", "by_spelling",
                  "n_null", "n_blank", "n_values_repeated", "rows_dropped_by_dedupe", "records", "ties"):
            if k in r and r[k] not in (None, [], {}):
                extra.append(f"{k}={r[k]}")
        lines.append(f"[{i}] {r.get('label', '')}\n    RESULT: {r['display']}" + (f"\n    details: {', '.join(extra)}" if extra else ""))
    return "\n".join(lines)


def build_messages(question, results, profile, verdict_list=None):
    rules = "\n".join(f"- {x}" for x in profile.cfg.get("rules_for_llm", []))
    system = (
        "You answer questions about frozen city datasets for a city analyst. Write in English.\n"
        "Use ONLY the computed results below. Never calculate anything yourself: no new percentages, sums, "
        "differences or ratios that are not already in the results. Copy numbers exactly as given "
        "(2 decimals for means/percentages/areas, integers for counts). Never invent names. If a result is an ERROR "
        "or missing, say that this part could not be computed. Answer every part of the question in order. "
        "For yes/no or 'could/should/does it establish' parts, answer explicitly (Yes/No) and give a one-sentence "
        "reason grounded in the rules or results. State denominators when giving percentages. Be concise: "
        "3-6 sentences, no headings, no evidence list.\n\n"
        f"DATA RULES:\n{rules}"
    )
    user = f"QUESTION: {question}\n\nCOMPUTED RESULTS:\n{_facts(results)}"
    if verdict_list:
        user += "\n\nDECIDED YES/NO ANSWERS (state each explicitly, same verdict):\n" + "\n".join(
            f"- {v['part']} -> {v['verdict']}: {v['reason']}" for v in verdict_list)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def evidence_lines(results, profile, max_lines=8):
    seen, out = set(), []
    for r in results:
        for e in r.get("evidence", []):
            line = f"- {e['source_id']} | {e['locator']} | {e['claim']}"
            if e["source_id"] and line not in seen:
                seen.add(line)
                out.append(line)
    a = profile.cfg.get("analysis_source")
    if a:
        out.append(f"- {a} | Analysis conventions | scope, counting, blank/null and rounding rules applied")
    return out[:max_lines]


def format_answer(qid, answer_text, evidence):
    return f"## {qid}\n\n{answer_text.strip()}\n\n### Evidence\n" + "\n".join(evidence) + "\n"


def verify(text, results, question, verdict_list=None):
    """Guardia de números: quita oraciones con números inventados y agrega los resultados que faltan."""
    notes = []
    allowed = N.allowed_numbers(results, question)
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    kept = []
    for snt in sentences:
        bad = N.nums(snt) - allowed
        if bad:
            notes.append(f"dropped sentence with invented numbers {sorted(bad)}")
        else:
            kept.append(snt)
    out = " ".join(kept).strip()
    have, tl = N.nums(out), out.lower()
    missing = []
    for r in results:
        need = N.required_tokens([r])
        if any((t not in have) if N.NUM_RE.fullmatch(t) else (t not in tl) for t in need):
            missing.append(r)
    for v in verdict_list or []:
        word = re.compile(r"\byes\b" if v["verdict"] == "Yes" else
                          r"\b(no|not|cannot|can't|doesn't|isn't|wouldn't|shouldn't)\b", re.I)
        if not word.search(out):
            out = (out + " " + _vsentence(v)).strip()
            notes.append(f"appended verdict {v['verdict']}")
    if missing:
        facts = "; ".join(f"{r.get('label', r['op'])}: {r['display']}" for r in missing)
        out = (out + "\n\nComputed values: " + facts).strip()
        notes.append(f"appended {len(missing)} computed value(s)")
    return out, notes
