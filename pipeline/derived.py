"""Cálculos derivados deterministas: cambio, cambio porcentual y razón entre dos números ya calculados.

El modelo nunca hace aritmética: planifica una llamada por número (p. ej. el valor de 2007/2008 y el de
2018/2019) y, si la pregunta pide una comparación, Python calcula aquí la diferencia y el cambio
porcentual (base = el primero, salvo que la pregunta diga otra cosa) o la razón. Cada derivado es un
resultado más: pasa por la plantilla, por la guardia de números y por los veredictos como cualquier otro.
"""
import math
import re

CHANGE_RE = re.compile(r"percent(age)?[- ]?(point)?s? change|% change|\bchange[sd]?\b|\bgr[eo]w(th)?\b|increase|decrease|"
                       r"declin|\bdrop|\brise\b|\brose\b|\bfell\b|went (up|down)|how much (more|less|higher|lower|"
                       r"bigger|smaller|larger|shorter|longer)|\bdifference\b|\bdiffer\b|\bcompare|\bvs\.?\b|versus",
                       re.I)
PCT_RE = re.compile(r"percent|%|relative|growth|rate", re.I)
RATIO_RE = re.compile(r"\bratio\b|divided by|\bper\b(?! cent)|\btimes (as|more|higher|larger)|"
                      r"as a (share|percentage|proportion) of", re.I)
SCALAR_OPS = ("count", "sum", "mean", "value", "percent", "max", "min")


def _scalar(r):
    v = r.get("value")
    if r.get("op") not in SCALAR_OPS or isinstance(v, (list, dict, tuple)) or v is None:
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else v


def _label(r):
    ft = r.get("filters_text") or "all records"
    return ft if ft != "all records" else (r.get("table") or "all records")


def _kind(r):
    return (r.get("op"), r.get("field") if r.get("op") not in ("count", "percent") else None, r.get("table"))


def fmt_num(x):
    """Formato fijo para derivados: 2 decimales desde 1; si es menor, 4 cifras significativas."""
    if x is None:
        return "n/a"
    if float(x).is_integer() and abs(x) < 1e15:
        return f"{x:.0f}"
    return f"{x:.2f}" if abs(x) >= 1 else f"{x:.4g}"


def _fmt(x, pct=False):
    if x is None:
        return "n/a"
    if not pct and float(x).is_integer():
        return f"{x:+.0f}"
    return f"{x:+.2f}"


def derive(question, results):
    """Lista de resultados 'derived' (posiblemente vacía)."""
    q = question or ""
    sc = [(r, _scalar(r)) for r in results]
    sc = [(r, v) for r, v in sc if v is not None]
    out = []
    if len(sc) < 2:
        return out
    # emparejar por tipo: (value, campo) con (value, mismo campo); count con count; sum con sum...
    groups = {}
    for r, v in sc:
        groups.setdefault(_kind(r), []).append((r, v))
    pairs = []
    for items in groups.values():
        for (ra, va), (rb, vb) in zip(items, items[1:]):
            pairs.append((ra, va, rb, vb))
    if not pairs and len(sc) == 2:                        # dos números de distinto tipo: igual se comparan
        (ra, va), (rb, vb) = sc
        pairs.append((ra, va, rb, vb))
    if CHANGE_RE.search(q):
        for ra, va, rb, vb in pairs:
            diff = vb - va
            pp = ra.get("op") == "percent" and rb.get("op") == "percent"
            pct = (100 * diff / va) if va else None
            unit = " percentage points" if pp else ""
            disp = f"change {_fmt(diff)}{unit}" + (f" ({pct:+.2f}% relative to the first)" if pct is not None else "")
            out.append({"op": "derived", "kind": "change", "a": _label(ra), "b": _label(rb), "va": va, "vb": vb,
                        "diff": diff, "pct": pct, "pp": pp, "field": ra.get("field"), "table": ra.get("table"),
                        "display": disp, "evidence": []})
    if RATIO_RE.search(q) and len(sc) >= 2 and not out:
        (ra, va), (rb, vb) = sc[0], sc[1]
        if vb:
            ratio = va / vb
            out.append({"op": "derived", "kind": "ratio", "a": _label(ra), "b": _label(rb), "va": va, "vb": vb,
                        "ratio": ratio, "fa": ra.get("field"), "fb": rb.get("field"),
                        "display": f"ratio {fmt_num(ratio)}" + (f" ({100 * ratio:.2f}%)" if PCT_RE.search(q) else ""),
                        "as_pct": bool(PCT_RE.search(q)),
                        "evidence": []})
    return out
