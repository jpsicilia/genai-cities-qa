"""Planificador: el LLM lee la pregunta y devuelve un plan JSON de llamadas a herramientas.

El esquema JSON se pasa a Ollama (salida estructurada): el modelo no puede inventar
herramientas, tablas, campos ni operadores fuera de las listas permitidas.
Herramientas, tablas y ejemplos salen del perfil de la familia.
"""
import json

import pandas as pd

from tools.tabular import OP_TEXT

TOOLS = {
    "count": "number of records matching filters",
    "percent": "percentage of records matching filters within a denominator ('denominator' filters; empty = all rows)",
    "mean": "mean of 'field' over matching records (positive_only=true only if asked; mapping for band lower edges)",
    "extreme": "max of numeric 'field' and ALL records reaching it",
    "distinct": "distinct non-null values, nulls, repeated values and dedupe losses of 'field'",
    "lookup": "read one record by the table key ('key')",
    "record": "read records by 'ids' using 'key_field' (default: table key); use to compare rows across tables",
    "group_count": "ranking of values of 'field' by record count among matching records",
    "variants": "total for a street ignoring case, split by raw spelling ('key' = street name)",
    "allocation": "best pair of streets from the cost table under 'budget' credits",
    "circle_area": "area range of a circle with diameter between d_min and d_max metres",
    "columns": "list the columns of the table (to check if a field exists)",
    "metadata": "dataset metadata: dates, notes, description",
    "areas": "planar area in m² of features 'ids' (projected); largest; difference ids[0]-ids[1]",
    "validity": "which geometries of the table are invalid and why (no repair)",
    "nearest": "nearest other record to 'anchor' and its distance in metres",
    "within_radius": "records within 'radius' metres of 'anchor' (anchor included); with filters: how many match and %",
    "z_extent": "vertical extent max(Z)-min(Z) of the native 3D geometry of 'ids', with height attributes",
    "symbol_radius": "equivalent radius of the drawn symbol circles in metres",
    "key_audit": "compare keys of 'table' with 'table_b' after keeping 'keep_prefix' and removing 'strip_prefix' in table_b",
    "prefix_counts": "count values of 'field' starting with each of 'prefixes'",
    "service_count": "feature count reported by the publisher's service response",
}


def _table_summary(alias, df, cfg, max_cats=40):
    lines = [f"TABLE {alias} ({len(df)} rows, key={cfg.get('key')}). {cfg.get('description', '')}", "  Columns:"]
    for c in df.columns:
        s = df[c]
        if s.isna().all():
            lines.append(f"  - {c}: always null")
        elif pd.api.types.is_numeric_dtype(s):
            lines.append(f"  - {c}: number (min {s.min():g}, max {s.max():g}, {int(s.isna().sum())} null)")
        else:
            vals = s.dropna().unique()
            if len(vals) <= max_cats:
                lines.append(f"  - {c}: one of {json.dumps(sorted(map(str, vals)), ensure_ascii=False)}")
            else:
                ex = json.dumps([str(v) for v in vals[:3]], ensure_ascii=False)
                lines.append(f"  - {c}: text ({len(vals)} distinct), e.g. {ex}")
    return "\n".join(lines)


def tool_names(profile):
    return profile.cfg.get("tools") or list(TOOLS)


def build_schema(profile, columns):
    filt = {"type": "object",
            "properties": {"field": {"type": "string", "enum": columns},
                           "op": {"type": "string", "enum": list(OP_TEXT)},
                           "value": {}},
            "required": ["field", "op"]}
    tables = profile.plan_tables()
    call = {"type": "object",
            "properties": {
                "tool": {"type": "string", "enum": tool_names(profile)},
                "table": {"type": "string", "enum": tables},
                "table_b": {"type": "string", "enum": tables},
                "field": {"type": "string", "enum": columns + ["none"]},
                "key_field": {"type": "string", "enum": columns + ["none"]},
                "filters": {"type": "array", "items": filt},
                "named_filter": {"type": "string", "enum": list(profile.cfg.get("named_filters", {})) + ["none"]},
                "denominator": {"type": "array", "items": filt},
                "positive_only": {"type": "boolean"},
                "mapping": {"type": "string", "enum": list(profile.cfg.get("mappings", {})) + ["none"]},
                "key": {}, "anchor": {}, "ids": {"type": "array"},
                "radius": {"type": "number"}, "budget": {"type": "number"},
                "d_min": {"type": "number"}, "d_max": {"type": "number"},
                "strip_prefix": {"type": "string"}, "keep_prefix": {"type": "string"},
                "prefixes": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["tool", "table"]}
    return {"type": "object", "properties": {"calls": {"type": "array", "items": call, "maxItems": 5}},
            "required": ["calls"]}


EXAMPLES = [  # por defecto (Dublín); un perfil puede traer los suyos en 'examples'
    ("What share of DCC rows are Good, over all rows and over rows with a recorded condition?",
     {"calls": [
         {"tool": "percent", "table": "dcc", "filters": [{"field": "Condition", "op": "eq", "value": "Good (Normal Vitality. No Major Defects)"}], "denominator": []},
         {"tool": "percent", "table": "dcc", "filters": [{"field": "Condition", "op": "eq", "value": "Good (Normal Vitality. No Major Defects)"}], "denominator": [{"field": "Condition", "op": "notnull"}]}]}),
    ("For Dundrum-Sandyford in DLR, give the record count and the raw and positive-only mean Act_height.",
     {"calls": [
         {"tool": "count", "table": "dlr", "filters": [{"field": "Location", "op": "eq", "value": "Dundrum-Sandyford"}]},
         {"tool": "mean", "table": "dlr", "field": "Act_height", "filters": [{"field": "Location", "op": "eq", "value": "Dundrum-Sandyford"}], "positive_only": False},
         {"tool": "mean", "table": "dlr", "field": "Act_height", "filters": [{"field": "Location", "op": "eq", "value": "Dundrum-Sandyford"}], "positive_only": True}]}),
    ("How many Herbert Park records are there ignoring case, and how are they split by spelling?",
     {"calls": [{"tool": "variants", "table": "dcc", "field": "Street", "key": "herbert park"}]}),
    ("Which DLR records have the largest Act_spread?",
     {"calls": [{"tool": "extreme", "table": "dlr", "field": "Act_spread"}]}),
    ("Show me DLR record Tree_code 1234.",
     {"calls": [{"tool": "lookup", "table": "dlr", "key": 1234}]}),
    ("Using band lower edges, what is the mean height of Fair DCC trees?",
     {"calls": [{"tool": "mean", "table": "dcc", "field": "Height", "mapping": "dcc_height_lower_edge",
                 "filters": [{"field": "Condition", "op": "eq", "value": "Fair (Reduced Vitality/Some Defects)"}]}]}),
]


def examples(profile):
    ex = profile.cfg.get("examples")
    return [(e["q"], e["plan"]) for e in ex] if ex else EXAMPLES


def build_messages(question, profile, tables):
    ctx = "\n\n".join(_table_summary(a, df, profile.cfg["tables"][a]) for a, (df, _) in tables.items())
    nf = "\n".join(f"  - {k}: {v.get('table')} -> " + "; ".join(
        f"{f['field']} {f['op']} {f.get('value', '')}" for f in v["filters"]) for k, v in
        profile.cfg.get("named_filters", {}).items()) or "  (none)"
    tools = "\n".join(f"  - {k}: {TOOLS[k]}" for k in tool_names(profile))
    system = (
        "You plan data lookups. Never compute numbers yourself: choose tools and exact filters.\n"
        "Use exact category values from the column lists. Use op 'null' for 'recorded as null/missing' and "
        "'blank' for 'blank/empty text after trimming'. Use 'eq_norm' for names ignoring case. "
        "Use 'startswith' for 'starts with'. Plan one call per number the question asks for. "
        "Only set 'named_filter' when the question names that screen. For a percentage of ALL rows use an empty "
        "denominator; for 'rows with a recorded X' use denominator [X notnull]. Pick the table that has the fields. "
        "Copy identifiers (ids, anchor) exactly as written in the question. "
        "If the question only asks for judgement and no number, use the 'columns' or 'metadata' tool.\n\n"
        f"TOOLS:\n{tools}\n\nNAMED FILTERS:\n{nf}\n\n{ctx}"
    )
    msgs = [{"role": "system", "content": system}]
    for q, plan in examples(profile):
        msgs += [{"role": "user", "content": q}, {"role": "assistant", "content": json.dumps(plan, ensure_ascii=False)}]
    msgs.append({"role": "user", "content": question})
    return msgs
