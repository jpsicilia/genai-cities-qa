"""Armado y validación del archivo de entrega (mismo formato que SampleSubmission.md).

Formato por pregunta:
    ## <Test ID>
    <respuesta>
    ### Evidence
    - SOURCE_ID | locator | supported claim

Tamaño: Zindi no publicó un límite oficial; los participantes reportan 256 KiB como límite
práctico (un archivo calificado pesaba 249.995 bytes). Apuntamos a 240 KiB para tener margen.
"""
import re
from collections import Counter

HEADER = "# Submission\n\n"
FALLBACK_TEXT = "Not answered."
HARD_MAX = 256 * 1024
TARGET = 240 * 1024
NUM_OR_VERDICT = re.compile(r"\d|\b(yes|no|not|cannot)\b", re.I)


def fallback(qid, source_ids):
    sid = source_ids[0] if source_ids else "none"
    return {"id": qid, "text": FALLBACK_TEXT, "answered": False,
            "evidence": [f"- {sid} | Source_IDs | listed source"]}


def _clean_text(text):
    text = re.sub(r"(?m)^\s*#+\s*", "", str(text)).strip()   # sin encabezados dentro de la respuesta
    return text or FALLBACK_TEXT


def render(e):
    ev = [ln for ln in e.get("evidence") or [] if ln.startswith("- ")] or \
         ["- none | Source_IDs | no evidence"]
    return f"## {e['id']}\n\n{_clean_text(e['text'])}\n\n### Evidence\n" + "\n".join(ev) + "\n"


def assemble(entries):
    return HEADER + "\n".join(render(e) for e in entries)


def _clip_line(line, n=80):
    parts = line[2:].split(" | ", 2)
    if len(parts) < 3:
        return line
    sid, loc, claim = parts
    clip = lambda s: s if len(s) <= n else s[: n - 1].rstrip() + "…"  # noqa: E731
    return f"- {sid} | {clip(loc)} | {clip(claim)}"


def _shrink_one(e):
    """Un paso de compresión de una respuesta. Devuelve False si ya no se puede comprimir más."""
    ev = e["evidence"]
    if len(ev) > 2:
        ev.pop()
        return True
    long = [i for i, ln in enumerate(ev) if len(ln) > 130]
    if long:
        ev[long[0]] = _clip_line(ev[long[0]])
        return True
    sents = re.split(r"(?<=[.!?])\s+", e["text"].strip())
    drop = [i for i, s in enumerate(sents) if i > 0 and not NUM_OR_VERDICT.search(s)]
    if drop:
        del sents[drop[-1]]
        e["text"] = " ".join(sents)
        return True
    return False


def shrink(entries, max_bytes=TARGET):
    """Comprime las respuestas más largas (nunca quita números ni veredictos) hasta caber en max_bytes."""
    sizes = {i: len(render(e).encode()) for i, e in enumerate(entries)}
    total = len(HEADER.encode()) + sum(sizes.values()) + max(len(entries) - 1, 0)
    frozen = set()
    steps = 0
    while total > max_bytes:
        cand = [i for i, e in enumerate(entries) if e.get("answered") and i not in frozen]
        if not cand:
            break
        i = max(cand, key=sizes.get)
        if not _shrink_one(entries[i]):
            frozen.add(i)
            continue
        new = len(render(entries[i]).encode())
        total += new - sizes[i]
        sizes[i] = new
        steps += 1
    return total, steps


def validate(raw, expected_ids, max_bytes=HARD_MAX):
    """Errores de formato. raw: bytes del archivo. expected_ids: IDs en el orden de SampleSubmission."""
    errs = []
    if raw.startswith(b"\xef\xbb\xbf"):
        errs.append("tiene BOM al inicio")
    if b"\r" in raw:
        errs.append("tiene finales de línea CR/CRLF (Windows)")
    if not raw.endswith(b"\n"):
        errs.append("no termina en salto de línea")
    if len(raw) > max_bytes:
        errs.append(f"pesa {len(raw)} bytes, más que el máximo {max_bytes}")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as ex:
        return errs + [f"no es UTF-8 válido: {ex}"], {"bytes": len(raw)}
    if not text.startswith("# Submission\n"):
        errs.append("no empieza con '# Submission'")
    ids = []
    for part in re.split(r"(?m)^## ", text)[1:]:
        lines = part.split("\n")
        qid = lines[0].strip()
        ids.append(qid)
        body = "\n" + "\n".join(lines[1:])
        if "\n### Evidence\n" not in body:
            errs.append(f"{qid}: falta '### Evidence'")
            continue
        ans, ev = body.split("\n### Evidence\n", 1)
        if not ans.strip():
            errs.append(f"{qid}: respuesta vacía")
        bullets = [ln for ln in ev.split("\n") if ln.startswith("- ")]
        if not bullets:
            errs.append(f"{qid}: Evidence sin viñetas '- '")
        elif any(ln.count("|") < 2 for ln in bullets):
            errs.append(f"{qid}: viñeta sin el formato SOURCE_ID | locator | claim")
    dup = [i for i, c in Counter(ids).items() if c > 1]
    missing, extra = set(expected_ids) - set(ids), set(ids) - set(expected_ids)
    if dup:
        errs.append(f"IDs repetidos: {dup[:5]}")
    if missing:
        errs.append(f"faltan {len(missing)} IDs del Test")
    if extra:
        errs.append(f"sobran {len(extra)} IDs que no están en el Test")
    if not (dup or missing or extra) and ids != list(expected_ids):
        errs.append("el orden no coincide con SampleSubmission/Test")
    return errs, {"bytes": len(raw), "sections": len(ids)}
