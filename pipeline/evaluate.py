"""Evaluación reutilizable: plan (números de herramientas) + texto (números citados, veredictos, invenciones).

Cada caso:
  {"id", "q", "ref": plan de referencia, "verdicts": ["No", ...] (opcional), "text_check": bool (default True)}

Métricas:
  plan      -> todos los números del plan de referencia aparecen entre los resultados del plan del LLM
  text_nums -> esos números aparecen escritos en la respuesta final
  verdicts  -> cada Yes/No esperado aparece en la respuesta
  invented  -> números en la respuesta que no están ni en los resultados ni en la pregunta
"""
import json
import re

from pipeline import answer, executor, llm
from pipeline import numbers as N

NEG_RE = re.compile(r"\b(no|not|cannot|can't|doesn't|does not|isn't|is not|would not|wouldn't|"
                    r"should not|shouldn't|neither|nor|insufficient|unable)\b", re.I)
YES_RE = re.compile(r"\byes\b", re.I)


def check_text(text, ref_results, got_results, question, verdicts):
    tl = text.lower()
    tnums = N.nums(text)
    need = N.required_tokens(ref_results)
    missing = sorted(t for t in need if (t not in tnums if N.NUM_RE.fullmatch(t) else t not in tl))
    invented = sorted(tnums - N.allowed_numbers(got_results, question))
    vmiss = []
    for v in verdicts or []:
        if (v == "No" and not NEG_RE.search(text)) or (v == "Yes" and not YES_RE.search(text)):
            vmiss.append(v)
    return missing, invented, vmiss


def run(cases, profile, fake=False, show_md=False):
    if fake:
        plans = {c["q"]: c["ref"] for c in cases}

        def fake_chat(messages, budget, schema=None, max_tokens=800):
            budget.calls += 1
            if schema and "verdict" in schema.get("properties", {}):
                d = {"verdict": "No", "reason": "fake reason"}
                if "note" in schema["properties"]:
                    d["note"] = "1"
                return json.dumps(d)
            return json.dumps(plans[messages[-1]["content"]]) if schema else "(fake)"
        llm.chat = fake_chat

    tot = {"plan": 0, "text": 0, "text_n": 0, "verd": 0, "verd_n": 0, "invented": 0}
    for c in cases:
        md, info = answer.answer(c["id"], c["q"], profile)
        got = info["results"]
        ref = executor.execute(c["ref"], profile, c["q"])
        got_d, want_d = [r["display"] for r in got], [r["display"] for r in ref]
        plan_ok = all(w in got_d for w in want_d)
        tot["plan"] += plan_ok
        text = md.split("### Evidence")[0].split("\n", 2)[-1]
        line = f"\n{'✅' if plan_ok else '❌'} {c['id']} ({info['seconds']}s, {info['budget']})"
        if not fake:
            missing, invented, vmiss = check_text(text, ref, got, c["q"], c.get("verdicts"))
            if c.get("text_check", True):
                tot["text_n"] += 1
                tot["text"] += not missing
            tot["verd_n"] += len(c.get("verdicts") or [])
            tot["verd"] += len(c.get("verdicts") or []) - len(vmiss)
            tot["invented"] += len(invented)
            line += (f" | texto {'ok' if not missing else 'faltan ' + str(missing)}"
                     f" | veredicto {'ok' if not vmiss else 'falta ' + str(vmiss)}"
                     + (f" | inventados {invented}" if invented else ""))
        print(line + f"\nQ: {c['q']}")
        if not plan_ok:
            print(f"   esperado: {want_d}\n   obtenido: {got_d}\n   plan LLM: {json.dumps(info['plan'], ensure_ascii=False)}")
        notes = [n for r in got for n in r.get("notes", [])]
        if notes:
            print("   correcciones:", notes)
        if show_md or not fake:
            print("\n" + md)
    n = len(cases)
    print(f"\n=== plan {tot['plan']}/{n}", end="")
    if not fake:
        print(f" | texto con los números {tot['text']}/{tot['text_n']} | veredictos {tot['verd']}/{tot['verd_n']}"
              f" | números inventados {tot['invented']}", end="")
    print(" ===")
    return tot
