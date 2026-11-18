"""Une todo: pregunta -> plan (LLM) -> herramientas (Python) -> respuesta (LLM) + evidencia (Python)."""
import json
import time

from pipeline import executor, llm, planner, verdicts, writer


def answer(qid, question, profile, verbose=False):
    t0 = time.time()
    budget = llm.Budget()
    tables = {a: profile.table(a) for a in profile.plan_tables()}
    columns = sorted({c for df, _ in tables.values() for c in df.columns})

    raw_plan = llm.chat(planner.build_messages(question, profile, tables), budget,
                        schema=planner.build_schema(profile, columns), max_tokens=600)
    try:
        plan = json.loads(raw_plan)
    except json.JSONDecodeError:
        plan = {"calls": []}
    plan = executor.route(question, plan, profile)
    results = executor.execute(plan, profile, question)

    vlist = []
    for part in verdicts.yes_no_parts(question)[:3]:
        v = verdicts.ask(part, question, writer._facts(results), profile, budget)
        if v:
            vlist.append(v)

    text = llm.chat(writer.build_messages(question, results, profile, vlist), budget, max_tokens=400)
    text, wnotes = writer.verify(text, results, question, vlist)
    md = writer.format_answer(qid, text, writer.evidence_lines(results, profile))
    info = {"verdicts": vlist, "writer_notes": wnotes, "plan": plan, "results": results, "budget": repr(budget), "seconds": round(time.time() - t0, 1)}
    if verbose:
        print(json.dumps(plan, indent=1, ensure_ascii=False))
        for r in results:
            print("  ->", r.get("label"), "=>", r["display"], ("| notes: " + "; ".join(r["notes"])) if r.get("notes") else "")
    return md, info
