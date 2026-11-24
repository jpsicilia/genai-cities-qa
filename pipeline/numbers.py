"""Utilidades de números en texto: comparar lo que dice la respuesta con lo que calcularon las herramientas."""
import json
import re

NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")
SAFE_NUMS = {"0", "1", "2", "3"}
PREFIX_DISP_RE = re.compile(r"\s*\(by [^()]*prefix:[^()]*\)")


def canon(n):
    try:
        f = float(n)
        return str(int(f)) if f.is_integer() else f"{f:.2f}"
    except ValueError:
        return n


def nums(text):
    return {canon(n) for n in NUM_RE.findall(str(text).replace(",", ""))}


def required_tokens(results):
    """Números (y nombres del par óptimo) que la respuesta debe mencionar."""
    toks = set()
    for r in results:
        op = r.get("op")
        if op in ("lookup", "record", "columns", "metadata", "error"):
            continue
        if op == "prefix_counts":
            toks |= {canon(v) for k, v in r["value"].items() if k != "other"}
            continue
        disp = r["display"]
        if r.get("by_prefix"):  # "(by baumnummer prefix: BK_ 200, TLM3D_ 0)": el texto puede decir "none" por el 0
            disp = PREFIX_DISP_RE.sub("", disp)
            toks |= {canon(n) for n in r["by_prefix"].values() if n}
        toks |= nums(disp)
        if op == "best_combo" and isinstance(r.get("value"), dict):
            toks |= {n.lower() for n in r["value"]["names"]}
    return toks


def allowed_numbers(results, question):
    allowed = nums(question) | SAFE_NUMS
    for r in results:
        allowed |= nums(json.dumps({k: v for k, v in r.items() if k != "evidence"}, default=str))
    return allowed
