"""Veredictos: cada subpregunta de sí/no ("Does...?", "Should...?", "Could...?") recibe una respuesta
explícita Yes/No con una razón, en JSON obligatorio. Así la parte conceptual no se pierde.
"""
import json
import re

from pipeline import llm

AUX = r"(does|do|did|is|are|was|were|can|could|should|would|will|has|have|may|might|must|shall)"
YN_START = re.compile(rf"^\s*(and |but |so |then |if so, |otherwise, )?{AUX}\b", re.I)
YN_INNER = re.compile(rf"(?:\b(?:and|or|but)\s+|[:;]\s*)\b{AUX}\s+(that|this|these|those|it|they|we|i|the|its|their|there|any|zero)\b", re.I)

SCHEMA = {"type": "object",
          "properties": {"verdict": {"type": "string", "enum": ["Yes", "No"]},
                         "reason": {"type": "string"}},
          "required": ["verdict", "reason"]}


def yes_no_parts(question):
    """Devuelve las oraciones (o cláusulas finales) de la pregunta que se contestan con sí/no."""
    parts = []
    for snt in re.split(r"(?<=[.?!])\s+", question.strip()):
        if not snt.endswith("?"):
            continue
        if YN_START.search(snt):
            parts.append(snt.strip())
            continue
        m = YN_INNER.search(snt)
        if m:
            parts.append(snt[m.start(1):].strip().capitalize())
    return parts


def _clip(text, n):
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def ask(part, question, facts, profile, budget, notes=None):
    """notes: frases de las guías (BM25). El modelo elige cuál respalda su veredicto y Python la cita."""
    notes = notes or []
    rules = "\n".join(f"- {x}" for x in profile.cfg.get("rules_for_llm", []))
    system = ("You judge what frozen city datasets can and cannot support. Answer the yes/no question with "
              "'Yes' or 'No' and ONE short reason (max 25 words) based on the data rules and computed results. "
              "Datasets are cautious records: answer No when the question asks whether a label, code, count, model "
              "or snapshot proves, certifies, measures or establishes something the rules say it does not. "
              "Do not put new numbers in the reason.\n\nDATA RULES:\n" + rules)
    user = f"FULL QUESTION: {question}\n\nCOMPUTED RESULTS:\n{facts}\n\nYES/NO QUESTION TO ANSWER: {part}"
    schema = json.loads(json.dumps(SCHEMA))
    if notes:
        user += ("\n\nSOURCE NOTES (pick the number of the note that supports your verdict, or 'none'):\n"
                 + "\n".join(f"[{i}] {_clip(n['text'], 300)}" for i, n in enumerate(notes, 1)))
        schema["properties"]["note"] = {"type": "string", "enum": [str(i) for i in range(1, len(notes) + 1)] + ["none"]}
        schema["required"].append("note")
    raw = llm.chat([{"role": "system", "content": system}, {"role": "user", "content": user}], budget,
                   schema=schema, max_tokens=120)
    try:
        d = json.loads(raw)
        v = {"part": part, "verdict": d["verdict"], "reason": d.get("reason", "").strip()}
    except (json.JSONDecodeError, KeyError):
        return None
    sel = str(d.get("note", "none"))
    if sel.isdigit() and 1 <= int(sel) <= len(notes):
        n = notes[int(sel) - 1]
        v["evidence"] = {"source_id": n["source_id"], "locator": f"{n['file']} ¶{n['para']}",
                         "claim": _clip(n["text"], 150)}
    return v


def sentence(v):
    reason = v["reason"].rstrip(".")
    return f"{v['verdict']}: {reason}."
