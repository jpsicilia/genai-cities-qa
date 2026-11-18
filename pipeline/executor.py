"""Ejecutor: corre el plan del LLM con las herramientas y arregla errores típicos de valores.

Red de seguridad determinista: si el modelo escribe "Poor" en vez de
"Poor (Low Vitality/Extensive Defects)", se corrige solo si la coincidencia es única.
"""
import difflib
import json
import re

import pandas as pd

from tools import loaders
from tools import spatial as S
from tools import tabular as T

CAT_OPS = ("eq", "ne", "in", "not_in")


def _repair_value(series, value, notes):
    cats = [str(x) for x in series.dropna().unique()]
    if len(cats) > 1000 or not isinstance(value, str) or value in cats:
        return value
    low = value.strip().lower()
    exact = [c for c in cats if c.lower() == low]
    pref = [c for c in cats if c.lower().startswith(low)]
    cand = exact or (pref if len(pref) == 1 else []) or difflib.get_close_matches(value, cats, n=1, cutoff=0.85)
    if cand:
        notes.append(f"value {value!r} -> {cand[0]!r}")
        return cand[0]
    return value


def _value_present(series, op, v):
    s = series.dropna().astype(str)
    if op == "eq":
        return (s == str(v)).any()
    if op == "startswith":
        return s.str.startswith(str(v)).any()
    if op == "contains":
        return s.str.contains(str(v), case=False, regex=False).any()
    return True


def _realign_field(df, f, notes, q=""):
    """Si el valor no existe en ese campo pero sí, exacto, en UNA otra columna de texto, mueve el filtro allí.
    También: valor que empieza con el nombre de una columna ('strasse X' -> strasse = 'X')."""
    if f["op"] not in ("eq", "startswith", "contains") or not isinstance(f.get("value"), str):
        return f
    v = f["value"].strip()
    for col in df.columns:
        if v.lower().startswith(col.lower() + " ") and len(v) > len(col) + 1:
            rest = v[len(col) + 1:].strip(" :=")
            if not pd.api.types.is_numeric_dtype(df[col]) and _value_present(df[col], f["op"], rest):
                notes.append(f"value {v!r} -> {col} = {rest!r}")
                return {**f, "field": col, "value": rest}
    numeric = pd.api.types.is_numeric_dtype(df[f["field"]])
    if numeric:
        try:
            float(v)
            return f
        except ValueError:
            pass
    elif _value_present(df[f["field"]], f["op"], f["value"]):
        return f
    hits = [c for c in df.columns if c != f["field"] and not pd.api.types.is_numeric_dtype(df[c])
            and _value_present(df[c], f["op"], f["value"])]
    if len(hits) > 1 and q:  # ambiguo: desempatar con la columna que nombra la pregunta
        named = [h for h in hits if re.search(rf"\b{re.escape(h.lower())}\b", q)]
        hits = named if len(named) == 1 else hits
    if len(hits) == 1:
        notes.append(f"value {f['value']!r} not in {f['field']!r} -> field {hits[0]!r}")
        return {**f, "field": hits[0]}
    return f


def _clean_filters(df, filters, notes):
    out = []
    for f in filters or []:
        f = dict(f)
        if f.get("field") not in df.columns:
            notes.append(f"dropped filter on unknown field {f.get('field')!r}")
            continue
        if f["op"] in CAT_OPS and not pd.api.types.is_numeric_dtype(df[f["field"]]):
            v = f.get("value")
            if isinstance(v, list):
                f["value"] = [_repair_value(df[f["field"]], x, notes) for x in v]
            else:
                f["value"] = _repair_value(df[f["field"]], v, notes)
        f = _realign_field(df, f, notes)
        out.append(f)
    return out


def _label(call):
    bits = [call["tool"], call.get("table", "")]
    if call.get("field") not in (None, "none"):
        bits.append(call["field"])
    if call.get("named_filter") not in (None, "none"):
        bits.append(f"[{call['named_filter']}]")
    if call.get("filters"):
        bits.append(T.describe(call["filters"]))
    if call.get("tool") == "percent":
        bits.append(f"denominator: {T.describe(call.get('denominator'))}")
    if call.get("positive_only"):
        bits.append("positive-only")
    return " | ".join(b for b in bits if b)


def _fields_used(call):
    fs = [f.get("field") for f in (call.get("filters") or []) + (call.get("denominator") or [])]
    if call.get("field") not in (None, "none"):
        fs.append(call["field"])
    return [f for f in fs if f]


def _guard_table(call, profile, notes):
    """Si los campos pedidos no están en la tabla elegida pero sí en otra, cambia de tabla."""
    used = _fields_used(call)
    alias = call.get("table") or profile.plan_tables()[0]
    if alias not in profile.cfg["tables"]:
        alias = profile.plan_tables()[0]
    df, _ = profile.table(alias)
    if not used or all(f in df.columns for f in used):
        return alias
    for other in profile.plan_tables():
        if other == alias:
            continue
        odf, _ = profile.table(other)
        if all(f in odf.columns for f in used):
            notes.append(f"table {alias!r} -> {other!r} (fields {used} live there)")
            return other
    return alias


def _guard_named_filter(call, alias, profile, notes):
    nf = call.get("named_filter")
    if nf in (None, "none"):
        return None
    if nf not in profile.cfg.get("named_filters", {}) or profile.cfg["named_filters"][nf].get("table") != alias:
        notes.append(f"dropped named filter {nf!r} (belongs to another table)")
        return None
    return nf


def _same(a, b):
    key = lambda fs: sorted(json.dumps(f, sort_keys=True) for f in fs or [])  # noqa: E731
    return key(a) == key(b)


def _guard_denominator(num, den, question, n_percent_calls, notes):
    q = (question or "").lower()
    if n_percent_calls == 1 and re.search(r"\bof all\b|\ball (dcc |dlr )?(rows|records)\b", q) and den:
        notes.append("denominator -> all rows (question says 'all')")
        return []
    if den and _same(num, den):
        fields = sorted({f["field"] for f in num})
        notes.append(f"denominator equal to numerator -> {fields} recorded (notnull)")
        return [{"field": f, "op": "notnull"} for f in fields]
    num_null = {f["field"] for f in num if f["op"] in ("null", "blank")}
    if any(f["field"] in num_null and f["op"] in ("notnull", "nonblank") for f in den or []):
        notes.append("denominator contradicted numerator -> all rows")
        return []
    return den


def _auto_mapping(df, field, profile, notes):
    """Media de un campo categórico sin mapping: usa el mapping del perfil que cubra sus valores."""
    if field is None or pd.api.types.is_numeric_dtype(df[field]):
        return None
    vals = set(df[field].dropna().astype(str))
    for name, mp in profile.cfg.get("mappings", {}).items():
        if vals and vals <= set(mp):
            notes.append(f"categorical mean of {field} -> mapping {name!r}")
            return mp
    return None


def _repair_id(series, val, notes):
    """Busca un id tal cual; si no está, prueba coincidencia única por prefijo/sufijo (p. ej. con o sin 'BK_')."""
    vals = series.dropna()
    if pd.api.types.is_numeric_dtype(vals):
        v = pd.to_numeric(val, errors="coerce")
        return v if pd.notna(v) else val
    sval = str(val).strip()
    if (vals.astype(str) == sval).any():
        return sval
    sv = vals.astype(str)
    cand = sv[sv.str.endswith(sval) | sv.apply(lambda x: sval.endswith(x))].unique()
    if len(cand) == 1:
        notes.append(f"id {sval!r} -> {cand[0]!r}")
        return cand[0]
    low = sv[sv.str.lower() == sval.lower()].unique()
    if len(low) == 1:
        notes.append(f"id {sval!r} -> {low[0]!r}")
        return low[0]
    return sval


def _ids(call):
    ids = call.get("ids")
    if ids in (None, [], ""):
        ids = [call["key"]] if call.get("key") not in (None, "", "none") else []
    return ids if isinstance(ids, list) else [ids]


def _service_count(profile):
    import re as _re
    cfg = profile.cfg["extra_sources"]["service_count"]
    sid = cfg["source_id"]
    with open(loaders.path_of(sid), encoding="utf-8") as fh:
        txt = fh.read()
    m = _re.search(rf'{cfg["attribute"]}="(\d+)"', txt)
    n = int(m.group(1)) if m else None
    return {"op": "service_count", "value": n, "display": f"{cfg['attribute']} = {n} ({cfg.get('description', '')})",
            "evidence": [{"source_id": sid, "locator": f"XML attribute {cfg['attribute']}", "claim": f"{n} features reported"}]}


GEO_TOOLS = {"areas", "validity", "nearest", "within_radius", "z_extent", "symbol_radius"}


def _run_geo(tool, call, profile, alias, tcfg, filters, notes):
    gdf, sid = profile.geo(alias)
    key = call.get("key_field") if call.get("key_field") not in (None, "none") else tcfg.get("key")
    epsg = profile.metric_epsg
    if tool == "areas":
        ids = [_repair_id(gdf[key], i, notes) for i in _ids(call)]
        return S.areas(gdf, key, ids, epsg, source_id=sid)
    if tool == "validity":
        return S.validity(gdf, key, source_id=sid)
    if tool in ("nearest", "within_radius"):
        anchor = _repair_id(gdf[key], call.get("anchor") or (_ids(call) or [None])[0], notes)
        if tool == "nearest":
            return S.nearest(gdf, key, anchor, epsg, source_id=sid)
        return S.within_radius(gdf, key, anchor, float(call.get("radius") or 0), epsg, filters or None, source_id=sid)
    if tool == "z_extent" and not gdf.has_z.any():
        if re.search(r"area|m²|m2|square met|footprint|larger|bigger", call.get("_q", "")):
            notes.append("z_extent on 2D layer + area wording -> areas")
            tool = "areas"
        else:
            return {"op": "z_extent", "value": None, "display": f"table {alias!r} has no Z coordinates",
                    "evidence": [{"source_id": sid, "locator": "geometry dimension", "claim": "2D geometry, no Z"}]}
    if tool == "areas":
        ids = [_repair_id(gdf[key], i, notes) for i in _ids(call)]
        return S.areas(gdf, key, ids, epsg, source_id=sid)
    if tool == "z_extent":
        ids = [_repair_id(gdf[key], i, notes) for i in _ids(call)]
        return S.z_extent(gdf, key, ids, source_id=sid, show=tcfg.get("z_show"))
    if tool == "symbol_radius":
        return S.symbol_radius(gdf, epsg, source_id=sid)
    raise ValueError(tool)


def run_call(call, profile, question="", n_percent_calls=0):
    notes = []
    tool = call["tool"]
    alias = _guard_table(call, profile, notes)
    tcfg = profile.cfg["tables"][alias]
    df, sid = profile.table(alias)
    field = None if call.get("field") in (None, "none") else call["field"]

    filters = _clean_filters(df, call.get("filters"), notes)
    nf = _guard_named_filter(call, alias, profile, notes)
    if nf:
        filters = profile.filters(nf) + filters
    call = {**call, "table": alias, "filters": filters, "named_filter": nf}

    if tool == "group_count" and field is None:
        tool = "count"
        notes.append("group_count without field -> count")

    if tool == "lookup" and call.get("key") in (None, "", "none"):
        for f in call["filters"]:
            if f.get("field") == tcfg.get("key"):
                call["key"] = f.get("value")
                notes.append("lookup key taken from filter")

    if tool in GEO_TOOLS:
        res = _run_geo(tool, {**call, "_q": (question or "").lower()}, profile, alias, tcfg, filters, notes)
    elif tool == "record":
        key = call.get("key_field") if call.get("key_field") not in (None, "none") else tcfg.get("key")
        ids = [_repair_id(df[key], i, notes) for i in _ids(call)]
        res = S.record(df, key, ids, source_id=sid)
    elif tool == "key_audit":
        b = call.get("table_b") if call.get("table_b") in profile.cfg["tables"] else None
        if b is None:
            raise ValueError("key_audit needs table_b")
        dfb, sidb = profile.table(b)
        res = S.key_audit(df, tcfg["key"], dfb, profile.cfg["tables"][b]["key"],
                          strip_prefix=call.get("strip_prefix") or "", keep_prefix=call.get("keep_prefix") or "",
                          source_ids=(sid, sidb))
    elif tool == "prefix_counts":
        res = S.prefix_counts(df, field or tcfg["key"], call.get("prefixes") or [], source_id=sid)
    elif tool == "service_count":
        res = _service_count(profile)
    elif tool == "count":
        res = T.count(df, filters, source_id=sid)
    elif tool == "percent":
        den = _clean_filters(df, call.get("denominator"), notes)
        den = _guard_denominator(filters, den, question, n_percent_calls, notes)
        res = T.percent(df, filters, den, source_id=sid)
        call["denominator"] = den
    elif tool == "mean":
        mp = None if call.get("mapping") in (None, "none") else profile.mapping(call["mapping"])
        fvals = set(df[field].dropna().astype(str)) if field else set()
        if mp and field and (not fvals or not fvals <= set(mp)):
            fits = [c for c in df.columns if not pd.api.types.is_numeric_dtype(df[c]) and len(df[c].dropna())
                    and set(df[c].dropna().astype(str)) <= set(mp)]
            if fits:
                notes.append(f"mapping does not fit {field!r} -> field {fits[0]!r}")
                field = fits[0]
        mp = mp or _auto_mapping(df, field, profile, notes)
        res = T.mean(df, field, filters, positive_only=bool(call.get("positive_only")), mapping=mp, source_id=sid)
    elif tool == "extreme":
        res = T.extreme(df, field, filters, id_field=tcfg.get("key"), source_id=sid,
                        show=[c for c in df.columns if c != tcfg.get("key")
                              and not pd.api.types.is_numeric_dtype(df[c])][:4])
    elif tool == "distinct":
        res = T.distinct(df, field or tcfg.get("key"), filters, source_id=sid)
    elif tool == "lookup":
        key = call.get("key")
        if pd.api.types.is_numeric_dtype(df[tcfg["key"]]):
            key = pd.to_numeric(key, errors="coerce")
        res = T.lookup(df, tcfg["key"], key, source_id=sid)
    elif tool == "group_count":
        norm = (field or "").lower() in {k.lower() for k in profile.cfg.get("normalisation", {})}
        res = T.group_count(df, field, filters, normalize=norm, top=5, source_id=sid)
    elif tool == "variants":
        res = T.variants(df, field or "Street", str(call.get("key", "")), source_id=sid)
    elif tool == "allocation":
        res = _allocation(profile, call.get("budget"))
    elif tool == "circle_area":
        res = T.circle_area_range(float(call.get("d_min", 0)), float(call.get("d_max", 0)))
    elif tool == "columns":
        cols = list(df.columns)
        res = {"op": "columns", "value": cols, "display": ", ".join(cols),
               "evidence": [{"source_id": sid, "locator": "table header", "claim": f"columns: {', '.join(cols)}"}]}
    elif tool == "metadata":
        res = _metadata(tcfg)
    else:
        raise ValueError(tool)
    res["label"] = _label(call)
    res["notes"] = notes
    return res


def _allocation(profile, budget):
    sc = profile.cfg["scenarios"]["allocation"]
    costs, csid = profile.table(sc["costs_table"])
    target, tsid = profile.table(sc["target_table"])
    budget = budget or sc.get("default_budget")
    items, ev = [], []
    for r in costs.itertuples(index=False):
        name, cost = getattr(r, sc["name_field"]), int(getattr(r, sc["cost_field"]))
        flt = profile.filters(sc["named_filter"], {"field": sc["target_field"], "op": "eq_norm", "value": name})
        n = T.count(target, flt)["value"]
        items.append({"name": name, "cost": cost, "value": n})
        ev.append({"source_id": tsid, "locator": f"filter: [{sc['named_filter']}] AND {sc['target_field']} "
                   f"= {name!r} (ignoring case)", "claim": f"{name}: {n} records"})
    res = T.best_combo(items, k=sc.get("k", 2), budget=budget, source_id=csid)
    res["evidence"] += ev
    return res


def _metadata(tcfg):
    sid = tcfg.get("metadata_source_id")
    if not sid:
        return {"op": "metadata", "value": None, "display": "no metadata", "evidence": []}
    meta = loaders.load_json(sid).get("result", {})
    keep = {k: meta.get(k) for k in ("title", "notes", "Date Range", "issued", "metadata_modified")}
    res_dates = [(r.get("format"), r.get("last_modified")) for r in meta.get("resources", [])]
    txt = "; ".join(f"{k}: {v}" for k, v in keep.items() if v) + f"; resource last_modified: {res_dates}"
    return {"op": "metadata", "value": keep, "display": txt,
            "evidence": [{"source_id": sid, "locator": "package metadata (title, notes, dates)",
                          "claim": txt[:300]}]}


def route(question, plan, profile):
    """Atajos deterministas para casos que el modelo chico confunde."""
    q = question.lower()
    sc = profile.cfg.get("scenarios", {}).get("allocation")
    m = re.search(r"(\d[\d,]*)\s*(?:hypothetical\s+)?(?:inspection\s+)?credits?", q)
    if sc and ("credit" in q) and not any(c.get("tool") == "allocation" for c in plan.get("calls", [])):
        budget = int(m.group(1).replace(",", "")) if m else sc.get("default_budget")
        return {"calls": [{"tool": "allocation", "table": sc["target_table"], "budget": budget}],
                "routed": "allocation"}
    return plan


def _dedupe_and_scope(calls, question, notes, aliases=("dcc", "dlr")):
    """Quita llamadas repetidas y las de una tabla que la pregunta no menciona."""
    q = question.lower()
    seen, out = set(), []
    for c in calls:
        k = json.dumps({x: c.get(x) for x in ("tool", "table", "table_b", "field", "filters", "key", "ids", "anchor",
                                              "radius", "denominator", "positive_only", "mapping", "named_filter",
                                              "key_field", "strip_prefix", "keep_prefix", "prefixes")},
                       sort_keys=True, default=str)
        if k not in seen:
            seen.add(k)
            out.append(c)
    mentioned = {t for t in aliases if re.search(rf"\b{t}\b", q)}
    if len(mentioned) == 1:
        scoped = [c for c in out if c.get("table") in mentioned or c.get("table_b") in mentioned
                  or c.get("tool") in ("allocation", "circle_area", "service_count")]
        if scoped and len(scoped) < len(out):
            notes.append(f"dropped calls outside {mentioned}")
            out = scoped
    if len(out) < len(calls):
        notes.append(f"{len(calls) - len(out)} call(s) removed")
    return out


def _tokens(text):
    return {t for t in re.split(r"[^0-9a-zäöüß]+", str(text).lower()) if len(t) >= 3}


def _grounded(f, q, qtok, profile):
    """Un filtro está 'anclado' si la pregunta menciona su campo, un sinónimo o parte de su valor."""
    field = f.get("field", "")
    if field.lower() in q:
        return True
    if any(syn in q for syn in profile.cfg.get("field_synonyms", {}).get(field, [])):
        return True
    v = f.get("value")
    vals = v if isinstance(v, list) else [v]
    for x in vals:
        if x is None:
            continue
        if isinstance(x, (int, float)) and str(x).replace(".0", "") in q:
            return True
        if _tokens(x) & qtok:
            return True
    return False


YEAR_RE = re.compile(r"(?:planting year|planted|pflanzjahr)[^.?;]*?(\d{4})\s*(?:or later|or after|onwards)"
                     r"|(?:planted|planting year|pflanzjahr)\s+(?:since|from|in or after)\s+(\d{4})")
MOST_RE = re.compile(r"\b(most common|most frequent|which [a-z ]{0,40}has the most|top)\b")


ID_RE = re.compile(r"[A-Za-z0-9]+(?:[_-][A-Za-z0-9]+)+")
ID_TOOLS = {"areas", "z_extent", "record", "nearest", "within_radius", "lookup"}
OF_THOSE_RE = re.compile(r"\bhow many of (those|them|these)\b")


def _ids_from_question(q_orig, series):
    keys = set(series.dropna().astype(str))
    seen, out = set(), []
    for tok in ID_RE.findall(q_orig):
        if tok in keys and tok not in seen:
            seen.add(tok)
            out.append(tok)
    return out


def _pos(f, q, profile):
    """Posición en la pregunta donde aparece el filtro (campo, sinónimo o valor)."""
    cands = [f.get("field", "").lower()] + profile.cfg.get("field_synonyms", {}).get(f.get("field"), [])
    v = f.get("value")
    if isinstance(v, str):
        cands += [v.lower()] + sorted(_tokens(v), key=len, reverse=True)
    pos = [q.find(c) for c in cands if c and q.find(c) >= 0]
    return min(pos) if pos else 10 ** 6


def repair_plan(calls, question, profile, notes):
    q_orig = question or ""
    q = q_orig.lower()
    qtok = _tokens(q)
    out = []
    for c in calls:
        c = dict(c)
        if c.get("table") in profile.cfg["tables"] and c.get("filters"):
            df = profile.table(c["table"])[0]
            c["filters"] = [_realign_field(df, f, notes, q) if f.get("field") in df.columns else f for f in c["filters"]]
        # ids escritos en la pregunta que existen como clave
        if c.get("tool") in ID_TOOLS and c.get("table") in profile.cfg["tables"]:
            tcfg = profile.cfg["tables"][c["table"]]
            key = c.get("key_field") if c.get("key_field") not in (None, "none") else tcfg.get("key")
            df = profile.table(c["table"])[0]
            if key in df.columns and not pd.api.types.is_numeric_dtype(df[key]):
                qids = _ids_from_question(q_orig, df[key])
                if c["tool"] in ("areas", "z_extent", "record") and qids:
                    have = [str(i) for i in (c.get("ids") or [])]
                    if set(qids) - set(have):
                        c["ids"] = qids
                        notes.append(f"ids from question: {qids}")
                elif c["tool"] in ("nearest", "within_radius") and qids and str(c.get("anchor")) not in qids:
                    c["anchor"] = qids[0]
                    notes.append(f"anchor from question: {qids[0]}")
        # media/extremo sin campo -> columna numérica nombrada en la pregunta
        if c.get("tool") in ("mean", "extreme") and c.get("field") in (None, "none") and c.get("table") in profile.cfg["tables"]:
            df = profile.table(c["table"])[0]
            syn = profile.cfg.get("field_synonyms", {})
            num = [col for col in df.columns if pd.api.types.is_numeric_dtype(df[col])
                   and (re.search(rf"\b{re.escape(col.lower())}\b", q) or any(x in q for x in syn.get(col, [])))]
            if num:
                c["field"] = num[0]
                notes.append(f"{c['tool']} field from question: {num[0]!r}")
        # filtros sin ancla en la pregunta -> fuera (solo los que escribió el modelo)
        for k in ("filters", "denominator"):
            if c.get(k):
                kept = [f for f in c[k] if _grounded(f, q, qtok, profile)]
                if len(kept) < len(c[k]):
                    notes.append(f"dropped ungrounded {k}: {[f.get('field') for f in c[k] if f not in kept]}")
                c[k] = kept
        # count con 'denominator' -> dos conteos (total y subconjunto)
        if c.get("tool") == "count" and c.get("denominator"):
            base = {**c, "denominator": []}
            sub = {**c, "filters": (c.get("filters") or []) + c["denominator"], "denominator": []}
            notes.append("count with denominator -> two counts")
            out += [base, sub]
            continue
        m = OF_THOSE_RE.search(q)
        if (m and c.get("tool") == "count" and len(c.get("filters") or []) >= 2
                and sum(x.get("tool") == "count" for x in calls) == 1):
            before = [f for f in c["filters"] if _pos(f, q, profile) < m.start()]
            if 0 < len(before) < len(c["filters"]):
                notes.append("'how many of those' -> total + subset counts")
                out += [{**c, "filters": before}, c]
                continue
        out.append(c)
    # año de plantación mencionado como umbral -> filtro en el campo de año del perfil
    yf = profile.cfg.get("year_field")
    m = YEAR_RE.search(q)
    if yf and m:
        year = int(m.group(1) or m.group(2))
        for c in out:
            if c.get("tool") in ("within_radius", "count", "percent") and not any(
                    f.get("field") == yf for f in c.get("filters") or []):
                if c["tool"] == "within_radius" or len(out) == 1:
                    c["filters"] = (c.get("filters") or []) + [{"field": yf, "op": "ge", "value": year}]
                    notes.append(f"added {yf} >= {year} from question")
    # 'most common' sin group_count -> convertir la primera llamada de conteo
    if MOST_RE.search(q) and not any(c.get("tool") == "group_count" for c in out):
        tables = {a: profile.table(a)[0] for a in profile.plan_tables()}
        for c in out:
            if c.get("tool") in ("count", "distinct"):
                df = tables.get(c.get("table"))
                used = {f.get("field") for f in c.get("filters") or []}
                syn = profile.cfg.get("field_synonyms", {})
                cands = [col for col in (df.columns if df is not None else []) if col not in used and (
                    col.lower() in q or any(x in q for x in syn.get(col, [])))]
                if cands:
                    c.update({"tool": "group_count", "field": cands[0]})
                    notes.append(f"'most common' -> group_count on {cands[0]!r}")
                    break
    return out


def execute(plan, profile, question=""):
    results = []
    plan_notes = []
    calls = _dedupe_and_scope(plan.get("calls", []), question, plan_notes, tuple(profile.plan_tables()))
    calls = repair_plan(calls, question, profile, plan_notes)[:5]
    n_pct = sum(c.get("tool") == "percent" for c in calls)
    for call in calls:
        try:
            results.append(run_call(call, profile, question, n_pct))
        except Exception as e:  # una llamada mala no tumba la pregunta entera
            results.append({"op": "error", "label": str(call), "display": f"ERROR {e!r}", "evidence": [], "notes": []})
    if results and plan_notes:
        results[0]["notes"] = plan_notes + results[0].get("notes", [])
    return results
