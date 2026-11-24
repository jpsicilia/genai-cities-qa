"""Une todo: pregunta -> plan (LLM) -> herramientas (Python) -> veredictos (LLM) -> texto (plantillas)
+ evidencia (Python)."""
import json
import os
import time

from pipeline import compose, executor, llm, planner, verdicts, writer
from tools import guides


def profile_source_ids(profile):
    c = profile.cfg
    ids = set(c.get("source_ids", [])) | {c.get("analysis_source")}
    for t in c["tables"].values():
        ids |= {t.get("source_id"), t.get("metadata_source_id")}
    return {i for i in ids if i}


def answer(qid, question, profile, verbose=False, source_ids=None):
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

    idx, gids = guides.guides_for(source_ids or profile_source_ids(profile))
    vlist = []
    try:
        for part in verdicts.yes_no_parts(question)[:3]:
            notes = idx.search(f"{part} {part} {question}", gids, k=3) if gids else []
            v = verdicts.ask(part, question, writer._facts(results), profile, budget, notes)
            if v:
                vlist.append(v)
        if os.environ.get("GENAI_WRITER", "template") == "llm":   # redactor viejo, para comparar
            text = llm.chat(writer.build_messages(question, results, profile, vlist), budget, max_tokens=300)
        else:
            text = compose.compose(question, results, vlist, profile, budget)
    except llm.BudgetExceeded:
        text = compose.compose(question, results, vlist, profile, llm.Budget(0, 0))
    text, wnotes = writer.verify(text, results, question, vlist)
    evidence = writer.evidence_lines(results, profile, vlist)
    md = writer.format_answer(qid, text, evidence)
    info = {"verdicts": vlist, "writer_notes": wnotes, "plan": plan, "results": results, "budget": repr(budget),
            "calls": budget.calls, "tokens": budget.tokens, "text": text, "evidence": evidence,
            "tools": [r.get("op") for r in results], "seconds": round(time.time() - t0, 1)}
    if verbose:
        print(json.dumps(plan, indent=1, ensure_ascii=False))
        for r in results:
            print("  ->", r.get("label"), "=>", r["display"], ("| notes: " + "; ".join(r["notes"])) if r.get("notes") else "")
    return md, info
