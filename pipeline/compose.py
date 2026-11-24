"""Redacción determinista: los hechos los escribe Python con plantillas, a partir de los resultados.

El LLM solo interviene para explicar un "why/explain" que no se deduce solo de los datos
(máximo 2 oraciones, sin números nuevos). Los veredictos Sí/No vienen del paso de veredictos.
"""
import math
import re

from pipeline import llm
from pipeline.verdicts import sentence as verdict_sentence

WHY_RE = re.compile(r"\b(why|explain|explanation|how come|what explains|account for)\b", re.I)
SKIP_FIELDS = {"_id", "FID", "geometry", "geometrie_gdo"}


def _tbl(r):
    t = str(r.get("table") or "")
    return t.upper() if 0 < len(t) <= 4 else t


CMP = {"gt": ">", "ge": "≥", "lt": "<", "le": "≤"}


def _fphrase(f):
    """Un filtro en palabras: 'a blank uuid_tlm3d (null or empty after trimming)', "Street = 'X'"."""
    fld, op, v = f.get("field"), f.get("op"), f.get("value")
    if op == "eq":
        return f"{fld} = {v!r}"
    if op == "ne":
        return f"{fld} other than {v!r}"
    if op in ("in", "not_in"):
        return f"{fld} {'in' if op == 'in' else 'not in'} " + ", ".join(repr(x) for x in (v or []))
    if op == "eq_norm":
        return f"{fld} = {v!r} (ignoring letter case and surrounding spaces)"
    if op == "startswith":
        return f"{fld} starting with {v!r}"
    if op == "contains":
        return f"{fld} containing {v!r}"
    if op == "null":
        return f"a null {fld}"
    if op == "notnull":
        return f"a recorded {fld} (not null)"
    if op == "blank":
        return f"a blank {fld} (null or empty after trimming)"
    if op == "nonblank":
        return f"a non-blank {fld} (after trimming)"
    if op in CMP:
        return f"{fld} {CMP[op]} {_num(v)}"
    return f"{fld} {op} {v!r}"


def _vp(r, filters=None):
    """Predicado verbal de los filtros: 'have X', 'pass the <regla> and have X'. None = todos los registros."""
    fl = r.get("filters") if filters is None else filters
    if fl is None:  # resultado sin filtros estructurados: se usa el texto tal cual
        ft = r.get("filters_text") or "all records"
        return None if ft == "all records" else f"match {ft}"
    if not fl:
        return None
    k = r.get("n_named", 0) if r.get("named_filter") else 0
    rest = " and ".join(_fphrase(f) for f in fl[k:])
    if k:
        label = r.get("named_label") or f"{r['named_filter']} screen"
        return f"pass the {label}" + (f" and have {rest}" if rest else "")
    return f"have {rest}"


def _where(r):
    vp = _vp(r)
    return f" that {vp}" if vp else ""


def _den_phrase(r):
    den = r.get("den_filters")
    return " and ".join(_fphrase(f) for f in den) if den else r.get("den_text", "")


def _plural(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


def _prefix_sentence(r):
    """Reparto por prefijo de la clave: si todo cae en un prefijo, lo dice en palabras."""
    by = r.get("by_prefix") or {}
    if not by:
        return ""
    key = r.get("prefix_key") or r.get("id_field") or "ID"
    nz = [p for p, n in by.items() if n]
    if len(nz) == 1 and len(by) > 1:
        zeros = " or ".join(p for p in by if p != nz[0])
        return f" By {key} prefix, all {by[nz[0]]} are {nz[0]} records and none are {zeros} records."
    return f" By {key} prefix: " + ", ".join(f"{p} {n}" for p, n in by.items()) + "."


def _num(x):
    if isinstance(x, float):
        return f"{x:g}" if x.is_integer() else f"{x:.2f}"
    return str(x)


def _fields_in_question(rec, question):
    q = (question or "").lower()
    named = [k for k in rec if k.lower() in q and k not in SKIP_FIELDS]
    rest = [k for k in rec if k not in named and k not in SKIP_FIELDS]
    return (named + rest)[:8]


def _record_sentence(r, question):
    recs = r.get("value") or []
    if not recs:
        return f"No {_tbl(r)} record matches the requested key."
    key = r.get("key_field") or r.get("id_field")
    out = []
    for rec in recs[:2]:
        vals = []
        for k in _fields_in_question(rec, question):
            if k == key:
                continue
            v = rec[k]
            if v is None or (isinstance(v, float) and math.isnan(v)):
                vals.append(f"{k} null")
            elif isinstance(v, str) and not v.strip():
                vals.append(f"{k} blank")
            else:
                vals.append(f"{k} {_num(v)}")
        head = f"{_tbl(r)} record {key} {_num(rec.get(key))}" if key in rec else f"{_tbl(r)} record"
        out.append(f"{head}: " + "; ".join(vals) + ".")
    return " ".join(out)


def fact(r, question=""):
    """Una oración por resultado, con los números exactos del resultado."""
    op, T = r.get("op"), _tbl(r)
    d = r.get("display", "")
    if op == "error":
        return "One requested value could not be computed from the supplied files."
    if op == "count":
        vp = _vp(r)
        if not vp:
            return f"The {T} table has {r['value']} records."
        return f"{r['value']} of the {r['total_rows']} {T} records {vp}." + _prefix_sentence(r)
    if op == "percent":
        den = r.get("den_filters") or []
        vp = _vp(r, [f for f in (r.get("filters") or []) if f not in den] if r.get("filters") is not None
                 else None) or "are counted"
        if r.get("den_text", "all rows") == "all rows":
            scope = f"all {r['denominator']} {T} rows"
        else:
            scope = f"the {r['denominator']} {T} records with {_den_phrase(r)}"
        return f"{r['numerator']} of {scope} {vp}, which is {d}."
    if op == "mean":
        rem = f", after removing {r['n_removed']} non-positive values" if r.get("kind") == "positive-only" else ""
        return f"The {r.get('kind', 'raw')} mean of {r.get('field')} is {d} over {r.get('n_used')} {T} records{_where(r)}{rem}."
    if op in ("max", "min"):
        if not r.get("n_hits"):
            return f"No {T} records{_where(r)} have a numeric {r.get('field')} value."
        key = r.get("id_field")
        ids = [str(x.get(key)) for x in (r.get("records") or []) if key in x][:5]
        word = "maximum" if op == "max" else "minimum"
        return (f"The {word} {r.get('field')} among {T} records{_where(r)} is {d}, reached by "
                f"{_plural(r.get('n_hits'), 'record')}"
                + (f": {key} {', '.join(ids)}" if ids else "") + ".")
    if op == "distinct":
        s = (f"{r.get('field')} in {T}: {r['n_rows']} rows, {r['n_distinct_nonnull']} distinct non-null values, "
             f"{r['n_null']} null")
        if r.get("n_values_repeated"):
            n = r["n_values_repeated"]
            s += (f"; {_plural(n, 'value')} {'occurs' if n == 1 else 'occur'} more than once, so deduplicating on "
                  f"this field would drop {_plural(r['rows_dropped_by_dedupe'], 'row')}")
        return s + "."
    if op in ("lookup", "record"):
        return _record_sentence(r, question)
    if op == "group_count":
        top = (r.get("value") or [(None, 0)])[0]
        if top[0] is None:
            return f"No {T} records{_where(r)} have a {r.get('field')} value."
        sp = r.get("by_spelling")
        if sp:  # etiqueta = la grafía más frecuente (value_counts va de mayor a menor), sin espacios extremos
            label = str(next(iter(sp))).strip()
            return (f"Ignoring letter case and surrounding spaces, the most frequent {r.get('field')} among {T} "
                    f"records{_where(r)} is {label!r} with {top[1]} records ("
                    + ", ".join(f"{k!r} {n}" for k, n in sp.items()) + ").")
        return f"The most frequent {r.get('field')} among {T} records{_where(r)} is {top[0]!r} with {top[1]} records."
    if op == "variants":
        parts = ", ".join(f"'{k}' {n}" for k, n in (r.get("by_spelling") or {}).items())
        return f"Ignoring letter case, {T} has {r['value']} records for this name" + (f": {parts}" if parts else "") + "."
    if op == "best_combo":
        v = r.get("value")
        if not v:
            return "No pair fits within the budget."
        s = (f"The best pair within {_num(r.get('budget'))} credits is {' + '.join(v['names'])}, costing {v['cost']} "
             f"credits and covering {v['covered']} records")
        if r.get("ties"):
            s += "; tied alternatives: " + "; ".join(" + ".join(t) for t in r["ties"])
        return s + "."
    if op == "circle_area":
        dmin, dmax = r.get("d", (None, None))
        return f"A circular crown with a diameter of {_num(dmin)} to {_num(dmax)} m covers {d}."
    return (d.rstrip(".") + ".") if d else ""


def normalisation_explanation(results):
    """Si hay un desglose por grafía y un conteo exacto de una de esas grafías, explica la diferencia."""
    for r in results:
        sp = r.get("by_spelling")
        if not sp or r.get("op") not in ("group_count", "variants"):
            continue
        for c in results:
            fl = c.get("filters") or []
            if c.get("op") == "count" and len(fl) == 1 and fl[0].get("op") == "eq" and fl[0].get("value") in sp:
                name, n = fl[0]["value"], c["value"]
                others = {k: v for k, v in sp.items() if k != name}
                if others:
                    miss = sum(others.values())
                    return [f"An exact search for {name!r} finds {n} because it misses the {_plural(miss, 'record')} "
                            "spelled " + " or ".join(repr(k) for k in others)
                            + f"; ignoring letter case and surrounding spaces merges {'it' if miss == 1 else 'them'}."]
    return []


def llm_explanation(question, facts, budget, profile):
    rules = "\n".join(f"- {x}" for x in profile.cfg.get("rules_for_llm", []))
    msgs = [{"role": "system", "content": (
        "Explain what the question asks to explain, in at most 2 short sentences (max 40 words), using only the "
        "facts and rules below. Do not repeat the facts and do not write any number that is not in the facts. "
        "Plain text only, no lists, no markdown.\n\nRULES:\n" + rules)},
        {"role": "user", "content": f"QUESTION: {question}\n\nFACTS:\n" + "\n".join(facts)}]
    try:
        txt = llm.chat(msgs, budget, max_tokens=90)
    except llm.BudgetExceeded:
        return []
    txt = re.sub(r"[*_#`>]+", "", txt).strip()
    return [txt] if txt else []


def _facts(results, question):
    """Oraciones de hechos; si un porcentaje repite el filtro de un conteo previo, se abrevia."""
    out, seen = [], set()
    for r in results:
        ft = r.get("filters_text")
        if r.get("op") == "percent" and ft in seen:
            if r.get("den_text", "all rows") == "all rows":
                out.append(f"That is {r['display']} of all {r['denominator']} {_tbl(r)} rows (denominator: all rows).")
            else:
                out.append(f"Using only the {r['denominator']} {_tbl(r)} records with {_den_phrase(r)} as the "
                           f"denominator, it is {r['display']}.")
            continue
        f = fact(r, question)
        if f:
            out.append(f)
        if r.get("op") in ("count", "percent"):
            seen.add(ft)
    return out


def compose(question, results, verdict_list, profile, budget):
    facts = _facts(results, question)
    expl = normalisation_explanation(results)
    if not expl and WHY_RE.search(question or ""):
        expl = llm_explanation(question, facts, budget, profile)
    verdicts = [verdict_sentence(v) for v in verdict_list or []]
    return " ".join(facts + expl + verdicts).strip()
