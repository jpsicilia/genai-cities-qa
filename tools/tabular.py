"""Herramientas tabulares genéricas.

Cada herramienta devuelve un dict con:
  - "value":    el resultado numérico (sin redondear)
  - "display":  el resultado formateado según las reglas (2 decimales, enteros)
  - "evidence": lista de {"source_id", "locator", "claim"} para la sección Evidence
El LLM nunca calcula: elige herramienta + parámetros; Python calcula y cita.

Formato de filtro: {"field": "Condition", "op": "eq", "value": "Dead"}
"""
import itertools

import pandas as pd

OP_TEXT = {
    "eq": "=", "ne": "≠", "in": "in", "not_in": "not in", "eq_norm": "= (case-insensitive, trimmed)",
    "startswith": "starts with", "contains": "contains", "null": "is null", "notnull": "is not null",
    "blank": "is blank (null/empty after trim)", "nonblank": "is nonblank after trim",
    "gt": ">", "ge": "≥", "lt": "<", "le": "≤",
}


# ------------------------------------------------------------------ helpers de texto
def _text(s: pd.Series) -> pd.Series:
    return s.fillna("").astype(str)


def norm_text(s: pd.Series) -> pd.Series:
    """Minúsculas + sin espacios en los extremos. No junta abreviaturas ni variantes."""
    return s.where(s.isna(), s.astype(str).str.strip().str.lower())


def is_blank(s: pd.Series) -> pd.Series:
    """Faltante trim-aware: null, o texto vacío tras quitar espacios de los extremos."""
    return s.isna() | _text(s).str.strip().eq("")


def fmt2(x) -> str:
    return "n/a" if x is None or pd.isna(x) else f"{x:.2f}"


# ------------------------------------------------------------------ filtros
def mask(df: pd.DataFrame, filters=None) -> pd.Series:
    m = pd.Series(True, index=df.index)
    for f in filters or []:
        col, op, v = df[f["field"]], f["op"], f.get("value")
        if op == "eq":
            c = col.eq(v)
        elif op == "ne":
            c = ~col.eq(v)
        elif op == "in":
            c = col.isin(v)
        elif op == "not_in":
            c = ~col.isin(v)
        elif op == "eq_norm":
            c = norm_text(col).eq(str(v).strip().lower())
        elif op == "startswith":
            c = _text(col).str.startswith(v)
        elif op == "contains":
            c = _text(col).str.contains(v, case=False, regex=False)
        elif op == "null":
            c = col.isna()
        elif op == "notnull":
            c = col.notna()
        elif op == "blank":
            c = is_blank(col)
        elif op == "nonblank":
            c = ~is_blank(col)
        elif op in ("gt", "ge", "lt", "le"):
            c = getattr(pd.to_numeric(col, errors="coerce"), op)(v)
        else:
            raise ValueError(f"operador desconocido: {op}")
        m &= c.fillna(False).astype(bool)
    return m


def describe(filters=None) -> str:
    if not filters:
        return "all records"
    parts = []
    for f in filters:
        v = "" if f["op"] in ("null", "notnull", "blank", "nonblank") else f" {f.get('value')!r}"
        parts.append(f"{f['field']} {OP_TEXT[f['op']]}{v}")
    return " AND ".join(parts)


def _ev(source_id, filters, claim, extra=""):
    loc = f"filter: {describe(filters)}" + (f"; {extra}" if extra else "")
    return {"source_id": source_id, "locator": loc, "claim": claim}


# ------------------------------------------------------------------ herramientas
def count(df, filters=None, source_id=""):
    n = int(mask(df, filters).sum())
    return {"op": "count", "value": n, "display": str(n), "total_rows": len(df),
            "evidence": [_ev(source_id, filters, f"{n} of {len(df)} records match")]}


def percent(df, num_filters, den_filters=None, source_id=""):
    """% = registros que cumplen num_filters dentro del denominador den_filters."""
    den = mask(df, den_filters)
    num = mask(df, num_filters) & den
    n, d = int(num.sum()), int(den.sum())
    val = 100 * n / d if d else None
    return {"op": "percent", "value": val, "display": f"{fmt2(val)}%", "numerator": n, "denominator": d,
            "evidence": [_ev(source_id, (den_filters or []) + (num_filters or []),
                             f"{n} / {d} = {fmt2(val)}%",
                             f"denominator: {describe(den_filters)} ({d} records)")]}


def mean(df, field, filters=None, positive_only=False, mapping=None, source_id=""):
    """Media de un campo. mapping traduce categorías a números (p. ej. borde inferior de banda)."""
    vals = df.loc[mask(df, filters), field]
    if mapping is not None:
        vals = vals.map(mapping)
    vals = pd.to_numeric(vals, errors="coerce").dropna()
    removed = 0
    if positive_only:
        removed = int((vals <= 0).sum())
        vals = vals[vals > 0]
    val = float(vals.mean()) if len(vals) else None
    how = ("mapped " if mapping else "") + ("positive-only " if positive_only else "raw ")
    return {"op": "mean", "value": val, "display": fmt2(val), "n_used": len(vals), "n_removed": removed,
            "evidence": [_ev(source_id, filters, f"{how}mean of {field} = {fmt2(val)} over {len(vals)} values"
                             + (f" ({removed} non-positive removed)" if positive_only else ""))]}


def extreme(df, field, filters=None, which="max", id_field=None, show=None, source_id=""):
    """Máximo/mínimo de un campo y TODOS los registros que lo alcanzan."""
    sub = df[mask(df, filters)]
    num = pd.to_numeric(sub[field], errors="coerce")
    val = num.max() if which == "max" else num.min()
    hits = sub[num.eq(val)]
    cols = [c for c in ([id_field] if id_field else []) + (show or []) if c]
    records = hits[cols].to_dict("records") if cols else []
    ids = hits[id_field].tolist() if id_field else []
    return {"op": which, "value": float(val), "display": f"{val:g}", "n_hits": len(hits), "records": records,
            "evidence": [_ev(source_id, filters, f"{which} {field} = {val:g}",
                             (f"{id_field} in {ids[:10]}" + (f" (+{len(ids) - 10} more)" if len(ids) > 10 else ""))
                             if id_field else "")]}


def distinct(df, field, filters=None, source_id=""):
    """Valores distintos, nulos, valores repetidos y filas que eliminaría un dedupe por ese campo."""
    s = df.loc[mask(df, filters), field]
    vc = s.value_counts(dropna=False)
    res = {"op": "distinct", "n_rows": len(s),
           "n_distinct_nonnull": int(s.nunique(dropna=True)),
           "n_distinct_incl_null": int(s.nunique(dropna=False)),
           "n_null": int(s.isna().sum()), "n_blank": int(is_blank(s).sum()),
           "n_values_repeated": int((vc > 1).sum()),
           "rows_dropped_by_dedupe": len(s) - int(s.nunique(dropna=False)),
           "top_repeated": vc[vc > 1].head(5).to_dict()}
    res["value"] = res["n_distinct_nonnull"]
    res["display"] = str(res["value"])
    res["evidence"] = [_ev(source_id, filters,
                           f"{res['n_rows']} rows, {res['n_distinct_nonnull']} distinct non-null {field}, "
                           f"{res['n_null']} null", f"field {field}")]
    return res


def lookup(df, key_field, key_value, fields=None, source_id=""):
    hits = df[df[key_field].eq(key_value)]
    rec = hits[fields].to_dict("records") if fields else hits.to_dict("records")
    return {"op": "lookup", "value": rec, "display": str(rec), "n_hits": len(hits),
            "evidence": [{"source_id": source_id, "locator": f"record {key_field} = {key_value!r}",
                          "claim": "; ".join(f"{k}={v}" for r in rec for k, v in r.items())}]}


def group_count(df, field, filters=None, normalize=False, top=5, source_id=""):
    """Ranking de conteos por valor de un campo (opcionalmente normalizado)."""
    s = df.loc[mask(df, filters), field]
    if normalize:
        s = norm_text(s)
    vc = s.value_counts(dropna=True)
    ranking = [(k, int(v)) for k, v in vc.head(top).items()]
    top_k = ranking[0] if ranking else (None, 0)
    return {"op": "group_count", "value": ranking, "display": f"{top_k[0]}: {top_k[1]}",
            "evidence": [_ev(source_id, filters, f"top {field}{' (normalised)' if normalize else ''}: "
                             f"{top_k[0]} with {top_k[1]} records")]}


def variants(df, field, normalized_value, source_id=""):
    """Grafías crudas que caen en un mismo valor normalizado, con su conteo."""
    sub = df.loc[norm_text(df[field]).eq(normalized_value.strip().lower()), field]
    vc = sub.value_counts(dropna=False)
    parts = {str(k): int(v) for k, v in vc.items()}
    return {"op": "variants", "value": int(vc.sum()), "display": str(int(vc.sum())), "by_spelling": parts,
            "evidence": [_ev(source_id, [{"field": field, "op": "eq_norm", "value": normalized_value}],
                             f"{int(vc.sum())} records: " + ", ".join(f"{k!r}={v}" for k, v in parts.items()))]}


def best_combo(items, k=2, budget=None, source_id=""):
    """Elige k ítems distintos que maximizan 'value' con suma de 'cost' ≤ budget. Devuelve empates."""
    feasible = []
    for combo in itertools.combinations(items, k):
        cost = sum(i["cost"] for i in combo)
        if budget is None or cost <= budget:
            feasible.append((sum(i["value"] for i in combo), cost, [i["name"] for i in combo]))
    if not feasible:
        return {"op": "best_combo", "value": None, "display": "no feasible combination", "evidence": []}
    best_val = max(f[0] for f in feasible)
    best = sorted([f for f in feasible if f[0] == best_val], key=lambda f: f[1])
    v, c, names = best[0]
    return {"op": "best_combo", "value": {"names": names, "covered": v, "cost": c},
            "display": f"{' + '.join(names)}: cost {c}, covers {v}", "ties": [b[2] for b in best[1:]],
            "evidence": [{"source_id": source_id, "locator": f"costs for {names}; budget {budget}",
                          "claim": f"{' + '.join(names)} cost {c} ≤ {budget} and cover {v}"}]}


def circle_area_range(d_min, d_max):
    import math
    lo, hi = math.pi * (d_min / 2) ** 2, math.pi * (d_max / 2) ** 2
    return {"op": "circle_area", "value": (lo, hi), "display": f"{fmt2(lo)} to {fmt2(hi)} m²",
            "evidence": []}
