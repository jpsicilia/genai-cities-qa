"""Carga genérica de fuentes tabulares de cualquier familia, sin perfil escrito a mano.

Cada archivo se convierte en una o varias tablas (pandas) con:
  - nombres de columna limpios (sin BOM ni espacios),
  - números convertidos solo cuando TODA la columna es numérica (coma decimal incluida) y no parece un código
    (ceros a la izquierda como '0000001' o '0087313759' se quedan como texto),
  - en hojas de cálculo: fila de encabezado detectada y columna _row con la fila real de Excel (para citar celdas),
  - en JSON: las listas de objetos anidadas (p. ej. addresses de un edificio) se vuelven tablas hijas con la
    clave del padre, y las listas de objetos dentro de metadatos (variables, fields) también son tablas.
Nada se repara ni se rellena: los nulos siguen nulos.
"""
import csv
import json
import os
import re

import pandas as pd

NUM_RE = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")
DEC_COMMA_RE = re.compile(r"^[+-]?\d+,\d+$")
LEADING_ZERO_RE = re.compile(r"^[+-]?0\d")
ID_NAME_RE = re.compile(r"(^|_)(id|uic|code|cod|no|nr|num|siren|siret|insee|zip|postcode|ref|uuid|guid)($|_)|"
                        r"(_id$|^id_|nummer$|numero$|number$)", re.I)
TABLE_EXT = {".csv", ".txt", ".json", ".geojson", ".gpkg", ".gml", ".xlsx", ".xlsm", ".ods"}
MAX_CHILD_DEPTH = 3


# ------------------------------------------------------------------ utilidades
def clean_name(c):
    return str(c).replace("﻿", "").strip()


def slug(s):
    s = re.sub(r"[^0-9a-zA-Z]+", "_", str(s).lower()).strip("_")
    return s or "t"


def col_letter(i):
    s, i = "", i + 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _is_idlike(name):
    return bool(ID_NAME_RE.search(str(name)))


def coerce_numeric(df):
    """Convierte a número las columnas de texto que son números de punta a punta (coma decimal incluida).
    No toca códigos con ceros a la izquierda ni columnas que se llaman como identificadores."""
    for c in df.columns:
        s = df[c]
        if pd.api.types.is_numeric_dtype(s) or c == "_row":
            continue
        v = s.dropna()
        if v.empty or not all(isinstance(x, str) for x in v.head(200)):
            continue
        v = v.astype(str).str.strip()
        v = v[v != ""]
        if v.empty:
            continue
        if _is_idlike(c) and v.str.fullmatch(r"\d+").all():
            continue                                   # códigos numéricos: se comparan como texto
        if v.str.match(LEADING_ZERO_RE).any() and not v.str.contains(r"[.,]").all():
            continue                                   # '0000001', '0087313759'
        dec = v.str.fullmatch(DEC_COMMA_RE.pattern)
        if dec.any() and (dec | v.str.fullmatch(r"[+-]?\d+")).all():
            conv = pd.to_numeric(s.astype(str).str.strip().str.replace(",", ".", regex=False)
                                 .replace("", None), errors="coerce")
        elif v.str.fullmatch(NUM_RE.pattern).all():
            conv = pd.to_numeric(s.astype(str).str.strip().replace("", None), errors="coerce")
        else:
            continue
        if conv.notna().sum() == len(v):
            df[c] = conv
    return df


# ------------------------------------------------------------------ texto delimitado
def sniff(path, nbytes=65536):
    with open(path, "rb") as fh:
        raw = fh.read(nbytes)
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            sample = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    lines = [ln for ln in sample.splitlines()[:30] if ln.strip()]
    counts = {d: [ln.count(d) for ln in lines[:20]] for d in (",", ";", "\t", "|")}
    # delimitador: el que aparece en todas las líneas con la cuenta más estable y alta
    best, score = ",", -1.0
    for d, cs in counts.items():
        if not cs or min(cs) == 0:
            continue
        sc = min(cs) - (max(cs) - min(cs)) * 0.5
        if sc > score:
            best, score = d, sc
    return best, enc, sample


def looks_tabular(path):
    """¿El .txt es una tabla (GTFS, LD2011...) o prosa (guías, readme)?"""
    delim, enc, sample = sniff(path)
    lines = [ln for ln in sample.splitlines()[:20] if ln.strip()]
    if len(lines) < 2:
        return False
    cs = [ln.count(delim) for ln in lines]
    return min(cs) >= 1 and max(cs) - min(cs) <= 1 and len(lines[0]) < 2000


def read_delimited(path, nrows=None):
    delim, enc, _ = sniff(path)
    df = pd.read_csv(path, sep=delim, dtype=str, encoding=enc, nrows=nrows, keep_default_na=False,
                     na_values=[""], on_bad_lines="skip", engine="c" if delim in ",;\t|" else "python")
    df.columns = [clean_name(c) for c in df.columns]
    return coerce_numeric(df), {"delimiter": delim, "encoding": enc}


# ------------------------------------------------------------------ hojas de cálculo
def _header_row(rows, max_scan=15):
    """Índice de la fila de encabezado: varias celdas de texto seguidas de filas con datos."""
    for i, row in enumerate(rows[:max_scan]):
        vals = [v for v in row if v not in (None, "")]
        if len(vals) < 2 or not all(isinstance(v, str) for v in vals):
            continue
        nxt = [v for v in (rows[i + 1] if i + 1 < len(rows) else []) if v not in (None, "")]
        if len(nxt) >= max(1, len(vals) // 2):
            return i
    return None


def _sheet_frames(name, rows):
    rows = [list(r) for r in rows]
    while rows and all(v in (None, "") for v in rows[-1]):
        rows.pop()
    if len(rows) < 3:
        return None
    h = _header_row(rows)
    if h is None:
        return None
    width = max(len(r) for r in rows)
    head = [clean_name(rows[h][j]) if j < len(rows[h]) and rows[h][j] not in (None, "") else f"col_{col_letter(j)}"
            for j in range(width)]
    seen = {}
    for j, c in enumerate(head):                      # encabezados repetidos: c, c.2, c.3
        seen[c] = seen.get(c, 0) + 1
        if seen[c] > 1:
            head[j] = f"{c}.{seen[c]}"
    body = [r + [None] * (width - len(r)) for r in rows[h + 1:]]
    df = pd.DataFrame(body, columns=head)
    df.insert(0, "_row", range(h + 2, h + 2 + len(df)))       # fila real de Excel (1 = primera)
    df = df.dropna(how="all", subset=[c for c in df.columns if c != "_row"])
    keep = [c for c in df.columns if c == "_row" or df[c].notna().any()]
    letters = {c: col_letter(j) for j, c in enumerate(head)}
    df = coerce_numeric(df[keep].copy())
    return df, {"sheet": name, "header_row": h + 1, "letters": {c: letters.get(c) for c in keep if c != "_row"}}


def read_xlsx(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    out = []
    for ws in wb.worksheets:
        fr = _sheet_frames(ws.title, ws.iter_rows(values_only=True))
        if fr:
            out.append(fr)
    return out


def read_ods(path):
    sheets = pd.read_excel(path, engine="odf", sheet_name=None, header=None)
    out = []
    for name, df in sheets.items():
        rows = [[None if (isinstance(v, float) and pd.isna(v)) else v for v in r] for r in df.itertuples(index=False)]
        fr = _sheet_frames(name, rows)
        if fr:
            out.append(fr)
    return out


# ------------------------------------------------------------------ JSON
def _records_of(obj):
    """La lista principal de registros de un JSON (lista, CKAN result/records, data, features) o None."""
    if isinstance(obj, list) and obj and all(isinstance(x, dict) for x in obj[:50]):
        return obj
    if isinstance(obj, dict):
        if obj.get("type") == "FeatureCollection" and isinstance(obj.get("features"), list):
            return [dict(f.get("properties") or {}, **({"id": f["id"]} if "id" in f and "id" not in
                                                        (f.get("properties") or {}) else {}))
                    for f in obj["features"]]
        for k in ("records", "result", "results", "data", "items"):
            if k in obj:
                r = _records_of(obj[k])
                if r is not None:
                    return r
    return None


def _flat(rec, max_level=1):
    """Aplana dicts (point.type) y deja las listas como están."""
    out = {}
    for k, v in rec.items():
        if isinstance(v, dict) and max_level > 0:
            for k2, v2 in _flat(v, max_level - 1).items():
                out[f"{k}.{k2}"] = v2
        else:
            out[k] = v
    return out


def _nested(series):
    v = series.dropna()
    return bool(len(v)) and isinstance(v.iloc[0], (list, dict))


def _guess_key(df):
    cands = [c for c in df.columns if c not in ("_row", "_layer") and not _nested(df[c])
             and df[c].notna().all() and df[c].is_unique]
    named = [c for c in cands if _is_idlike(c) or str(c).lower() in ("id", "key", "name")]
    return (named or cands or [None])[0]


def _children(records, parent_key, prefix, depth=1):
    """Tablas hijas: cada lista de objetos dentro de los registros, con la clave del padre."""
    out = {}
    if depth > MAX_CHILD_DEPTH or not records:
        return out
    list_fields = {k for r in records[:500] for k, v in r.items()
                   if isinstance(v, list) and v and all(isinstance(x, dict) for x in v[:20])}
    for f in sorted(list_fields):
        rows = []
        for r in records:
            for i, item in enumerate(r.get(f) or []):
                if isinstance(item, dict):
                    row = {"_parent": r.get(parent_key) if parent_key else None, "_i": i}
                    row.update(_flat({k: v for k, v in item.items() if not isinstance(v, list)}))
                    rows.append(row)
        if rows:
            df = coerce_numeric(pd.DataFrame(rows))
            name = f"{prefix}.{f}"
            if parent_key:
                df = df.rename(columns={"_parent": parent_key if parent_key not in df.columns else f"parent_{parent_key}"})
            out[name] = df
            sub = [x for r in records for x in (r.get(f) or []) if isinstance(x, dict)]
            out.update(_children(sub, None, name, depth + 1))
    return out


def _meta_lists(obj, prefix, depth=0):
    """Listas de objetos dentro de un JSON de metadatos (variables, fields...): tablas pequeñas citables."""
    out = {}
    if depth > MAX_CHILD_DEPTH:
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, list) and len(v) >= 2 and all(isinstance(x, dict) for x in v[:20]):
                rows = [_flat({kk: vv for kk, vv in x.items() if not isinstance(vv, (list, dict))}) for x in v]
                if rows and len(rows[0]) >= 2:
                    out[f"{prefix}.{k}"] = coerce_numeric(pd.DataFrame(rows))
            elif isinstance(v, (dict, list)):
                out.update(_meta_lists(v, f"{prefix}.{k}" if isinstance(v, dict) else prefix, depth + 1))
    return out


def read_json(path):
    """Devuelve {nombre_relativo: DataFrame}: '' = tabla principal; 'campo' = tabla hija."""
    with open(path, encoding="utf-8-sig") as fh:
        obj = json.load(fh)
    recs = _records_of(obj)
    out = {}
    if recs:
        main = coerce_numeric(pd.DataFrame([_flat(r) for r in recs]))
        list_cols = [c for c in main.columns if main[c].map(lambda x: isinstance(x, list)).any()]
        key = _guess_key(main.drop(columns=list_cols))
        out[""] = main.drop(columns=[c for c in list_cols
                                     if main[c].map(lambda x: isinstance(x, list) and x and isinstance(x[0], dict)).any()])
        for name, df in _children(recs, key, "").items():
            out[name.lstrip(".")] = df
    else:
        for name, df in _meta_lists(obj, "").items():
            out[name.lstrip(".")] = df
    return out


# ------------------------------------------------------------------ geodatos
def read_geo_attrs(path):
    import pyogrio
    out = {}
    try:
        layers = [ly[0] for ly in pyogrio.list_layers(path)]
    except Exception:  # noqa: BLE001
        layers = [None]
    for ly in layers:
        df = pyogrio.read_dataframe(path, layer=ly, read_geometry=False)
        df.columns = [clean_name(c) for c in df.columns]
        info = pyogrio.read_info(path, layer=ly)
        out[ly or ""] = (coerce_numeric(df), {"crs": info.get("crs"), "geometry_type": info.get("geometry_type"),
                                              "layer": ly})
    return out


# ------------------------------------------------------------------ punto de entrada
def read_any(path):
    """Lista de (sufijo, DataFrame, info) para un archivo; [] si no es tabular."""
    ext = os.path.splitext(path)[1].lower()
    if ext not in TABLE_EXT:
        return []
    if ext in (".csv", ".txt"):
        if ext == ".txt" and not looks_tabular(path):
            return []
        df, info = read_delimited(path)
        return [("", df, info)] if df.shape[1] >= 2 else []
    if ext in (".xlsx", ".xlsm"):
        fr = read_xlsx(path)
        return [(slug(info["sheet"]) if len(fr) > 1 else "", df, info) for df, info in fr]
    if ext == ".ods":
        fr = read_ods(path)
        return [(slug(info["sheet"]) if len(fr) > 1 else "", df, info) for df, info in fr]
    if ext in (".gpkg", ".gml"):
        res = read_geo_attrs(path)
        return [(slug(ly) if len(res) > 1 else "", df, {**info, "geo": True}) for ly, (df, info) in res.items()]
    if ext in (".json", ".geojson"):
        with open(path, encoding="utf-8-sig") as fh:
            head = fh.read(4096)
        if ext == ".geojson" or '"FeatureCollection"' in head:
            try:
                res = read_geo_attrs(path)
                (ly, (df, info)), = list(res.items())[:1]
                if df.shape[1] >= 1:
                    return [("", df, {**info, "geo": True})]
            except Exception:  # noqa: BLE001 — GeoJSON raro: se lee como JSON común
                pass
        return [(name, df, {}) for name, df in read_json(path).items() if df.shape[1] >= 2 and len(df)]
    return []


def sample_csv(path, n=2000):
    """Lectura rápida de una muestra (para describir tablas grandes en el prompt sin cargarlas enteras)."""
    df, info = read_delimited(path, nrows=n)
    return df, info


def is_csv_like(path):
    return os.path.splitext(path)[1].lower() in (".csv", ".txt")


def count_rows(path):
    n = 0
    with open(path, "rb") as fh:
        for buf in iter(lambda: fh.read(1 << 20), b""):
            n += buf.count(b"\n")
    return max(n - 1, 0)


__all__ = ["read_any", "read_delimited", "sample_csv", "coerce_numeric", "slug", "col_letter", "csv"]
