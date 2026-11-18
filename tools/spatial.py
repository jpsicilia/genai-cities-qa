"""Herramientas espaciales genéricas (GeoPandas/Shapely).

Convenciones (las fija cada perfil):
  - Las coordenadas nativas se conservan; solo se reproyecta para medir (metric_epsg).
  - GeoPandas reproyecta con orden x/y (always_xy).
  - No se reparan ni se descartan geometrías inválidas: se reportan.
  - Distancias euclidianas en metros; el radio incluye el borde (<=).
Cada herramienta devuelve value/display/evidence como las tabulares.
"""
import math

import numpy as np
import pandas as pd
from shapely import get_coordinates
from shapely.validation import explain_validity

from tools import tabular as T

TOL_M = 1e-6  # 1 micrómetro


def _fmt(x):
    return T.fmt2(x)


def _rows(gdf, id_field, ids):
    ids = [ids] if isinstance(ids, (str, int)) else list(ids)
    sub = gdf[gdf[id_field].isin(ids)]
    missing = [i for i in ids if i not in set(sub[id_field])]
    return sub, ids, missing


def areas(gdf, id_field, ids, metric_epsg, source_id=""):
    """Área plana (m²) de cada id en el CRS métrico. Si hay 2 ids: diferencia ids[0] - ids[1]."""
    sub, ids, missing = _rows(gdf, id_field, ids)
    m = sub.to_crs(metric_epsg)
    a = dict(zip(m[id_field], m.area))
    valid = dict(zip(sub[id_field], sub.is_valid))
    res = {"op": "areas", "value": a, "missing": missing}
    parts = [f"{i}: {_fmt(a[i])} m²" + ("" if valid.get(i, True) else " (INVALID geometry)") for i in ids if i in a]
    if a:
        big = max(a, key=a.get)
        res["largest"] = (big, a[big])
        parts.append(f"largest: {big}")
    if len(ids) == 2 and all(i in a for i in ids):
        res["difference"] = a[ids[0]] - a[ids[1]]
        parts.append(f"{ids[0]} minus {ids[1]} = {_fmt(res['difference'])} m²")
    res["display"] = "; ".join(parts) + (f"; not found: {missing}" if missing else "")
    res["evidence"] = [{"source_id": source_id, "locator": f"{id_field} in {ids}; geometry reprojected to EPSG:{metric_epsg}",
                        "claim": "; ".join(parts[:3])}]
    return res


def validity(gdf, id_field, source_id=""):
    bad = gdf[~gdf.is_valid]
    items = [(r[id_field], explain_validity(r.geometry)) for _, r in bad.iterrows()]
    shown = items[:10]
    disp = f"{len(items)} invalid of {len(gdf)}" + (": " + "; ".join(f"{i} ({why})" for i, why in shown) if items else "")
    return {"op": "validity", "value": len(items), "display": disp, "invalid": items,
            "evidence": [{"source_id": source_id, "locator": "shapely is_valid on native 2D geometry (no repair)",
                          "claim": disp[:300]}]}


def _anchor_dist(gdf, id_field, anchor, metric_epsg):
    m = gdf.to_crs(metric_epsg)
    a = m[m[id_field] == anchor]
    if a.empty:
        raise KeyError(f"anchor {anchor!r} not found in {id_field}")
    d = m.distance(a.geometry.iloc[0])
    return m, d, a.index[0]


def nearest(gdf, id_field, anchor, metric_epsg, source_id=""):
    m, d, ai = _anchor_dist(gdf, id_field, anchor, metric_epsg)
    d = d.drop(index=ai)
    j = d.idxmin()
    dmin = float(d.min())
    ties = m.loc[d[d == dmin].index, id_field].tolist()
    disp = f"nearest to {anchor}: {', '.join(map(str, ties))} at {_fmt(dmin)} m"
    return {"op": "nearest", "value": {"id": m.loc[j, id_field], "distance": dmin, "ties": ties}, "display": disp,
            "evidence": [{"source_id": source_id, "locator": f"{id_field} = {anchor!r}; Euclidean distance in EPSG:{metric_epsg}",
                          "claim": disp}]}


def within_radius(gdf, id_field, anchor, radius, metric_epsg, filters=None, source_id=""):
    """Registros a distancia <= radius del ancla (incluida). Con filters: cuántos de ellos cumplen y %."""
    m, d, _ = _anchor_dist(gdf, id_field, anchor, metric_epsg)
    sel = d <= radius + TOL_M  # borde incluido; TOL_M absorbe el error de reproyección (~1e-8 m)
    n = int(sel.sum())
    res = {"op": "within_radius", "value": n, "n_selected": n}
    disp = f"{n} records within {radius:g} m of {anchor} (anchor included)"
    if filters:
        k = int((sel & T.mask(gdf, filters)).sum())
        pct = 100 * k / n if n else None
        res.update({"n_match": k, "percent": pct})
        disp += f"; {k} of them match {T.describe(filters)} = {_fmt(pct)}%"
    res["display"] = disp
    res["evidence"] = [{"source_id": source_id,
                        "locator": f"{id_field} = {anchor!r}; distance <= {radius:g} m in EPSG:{metric_epsg}"
                                   + (f"; filter: {T.describe(filters)}" if filters else ""),
                        "claim": disp}]
    return res


def z_extent(gdf, id_field, ids, source_id="", show=None):
    """max(Z) - min(Z) de la geometría nativa 3D de cada id (sin interpretación de datum)."""
    sub, ids, missing = _rows(gdf, id_field, ids)
    out, parts = {}, []
    for _, r in sub.iterrows():
        z = get_coordinates(r.geometry, include_z=True)[:, 2]
        z = z[~np.isnan(z)]
        ext = float(z.max() - z.min()) if len(z) else None
        out[r[id_field]] = ext
        extra = "; ".join(f"{c}={r[c]}" for c in (show or []) if c in sub.columns)
        parts.append(f"{r[id_field]}: Z extent {_fmt(ext)} (min {z.min():.3f}, max {z.max():.3f})" + (f"; {extra}" if extra else ""))
    disp = " | ".join(parts) + (f" | not found: {missing}" if missing else "")
    return {"op": "z_extent", "value": out, "display": disp,
            "evidence": [{"source_id": source_id, "locator": f"{id_field} in {ids}; native Z coordinates", "claim": disp[:300]}]}


def symbol_radius(gdf, metric_epsg, source_id=""):
    """Radio equivalente sqrt(A/pi) de símbolos (círculos dibujados), en metros."""
    a = gdf.to_crs(metric_epsg).area
    r = np.sqrt(a / math.pi)
    disp = f"equivalent radius sqrt(area/pi): min {_fmt(r.min())} m, median {_fmt(r.median())} m, max {_fmt(r.max())} m over {len(r)} symbols"
    return {"op": "symbol_radius", "value": float(r.median()), "display": disp,
            "evidence": [{"source_id": source_id, "locator": f"symbol polygons reprojected to EPSG:{metric_epsg}", "claim": disp}]}


def key_audit(df_a, field_a, df_b, field_b, strip_prefix="", keep_prefix="", source_ids=("", "")):
    """Compara claves entre dos tablas. En B se filtran las que empiezan con keep_prefix y se les quita
    exactamente un strip_prefix inicial. Cuenta claves distintas: solo en A, solo en B, en ambas."""
    a = set(df_a[field_a].dropna().astype(str))
    b_raw = df_b[field_b].dropna().astype(str)
    if keep_prefix:
        b_raw = b_raw[b_raw.str.startswith(keep_prefix)]
    b = set(b_raw.str.slice(len(strip_prefix)) if strip_prefix else b_raw)
    res = {"both": len(a & b), "only_a": len(a - b), "only_b": len(b - a), "n_a": len(a), "n_b": len(b)}
    disp = (f"distinct keys: both {res['both']}; only in {field_a} (A) {res['only_a']}; "
            f"only in stripped {field_b} (B) {res['only_b']}")
    return {"op": "key_audit", "value": res, "display": disp, **res,
            "evidence": [{"source_id": source_ids[0], "locator": f"distinct {field_a}", "claim": f"{len(a)} keys"},
                         {"source_id": source_ids[1],
                          "locator": f"{field_b} starting with {keep_prefix!r}, leading {strip_prefix!r} removed",
                          "claim": disp}]}


def prefix_counts(df, field, prefixes, source_id=""):
    s = df[field].fillna("").astype(str)
    counts = {p: int(s.str.startswith(p).sum()) for p in prefixes}
    counts["other"] = len(s) - sum(counts.values())
    disp = "; ".join(f"{k}: {v}" for k, v in counts.items())
    return {"op": "prefix_counts", "value": counts, "display": disp,
            "evidence": [{"source_id": source_id, "locator": f"{field} prefixes {prefixes}", "claim": disp}]}


def record(df, id_field, ids, fields=None, source_id=""):
    """Lee uno o varios registros por id (para comparar entre tablas)."""
    sub, ids, missing = _rows(df, id_field, ids)
    cols = [c for c in (fields or df.columns) if c in sub.columns and c != "geometry"]
    recs = pd.DataFrame(sub[cols]).to_dict("records")
    disp = str(recs) + (f"; not found: {missing}" if missing else "")
    return {"op": "record", "value": recs, "display": disp,
            "evidence": [{"source_id": source_id, "locator": f"{id_field} in {ids}", "claim": disp[:300]}]}
