"""Índice de las guías de los organizadores: frases citables con su ubicación exacta.

1. Una guía es un archivo de texto (.md / .txt) cuyo Publisher en el manifest dice "organisers".
2. Cada guía se vincula a su familia por las URLs de dataset que comparte con otras fuentes del
   manifest. Se ignoran las URLs de licencias, porque esas las comparten casi todas.
3. Cada guía se parte en párrafos y frases; cada frase guarda archivo y número de párrafo (¶).
4. BM25 (búsqueda léxica, NO generativa: no gasta presupuesto del modelo) devuelve las frases
   más parecidas a una subpregunta, solo dentro de las guías de esa pregunta.
"""
import math
import os
import re
from collections import Counter
from functools import lru_cache

from tools import loaders

LIC_RE = re.compile(r"creativecommons|nationalarchives|opendefinition|licen|open-data-registry", re.I)
URL_RE = re.compile(r"https?://[^\s|;,]+")
TOKEN_RE = re.compile(r"[a-z0-9äöüßéèàçñ]+")
SENT_RE = re.compile(r"(?<=[.!?;])\s+(?=[A-Z0-9(\"'“])")
STOP = set("""a an and are as at be been but by can could did do does for from had has have how if in into
is it its of on or our should so than that the their them then there these this those to was we were what
when which who will with would you your i me my any all just also may might must only own same such""".split())
GUIDE_EXT = (".md", ".txt")


# ------------------------------------------------------------------ manifest
def _urls(*texts):
    out = set()
    for t in texts:
        for u in URL_RE.findall(str(t)):
            u = u.rstrip(".)")
            if not LIC_RE.search(u):
                out.add(u)
    return out


def guide_ids(man):
    """Source_IDs de las guías (texto escrito por los organizadores)."""
    if "Publisher" not in man.columns or "File" not in man.columns:
        return []
    pub = man["Publisher"].astype(str).str.contains("organis", case=False)
    ext = man["File"].astype(str).str.lower().str.endswith(GUIDE_EXT)
    return list(man.index[pub & ext])


META_RE = re.compile(r"metadata|catalogue|catalog", re.I)


def meta_ids(man):
    """Source_IDs de metadatos del publicador en JSON (catálogos CKAN): su campo 'notes' es citable."""
    if "File" not in man.columns:
        return []
    f = man["File"].astype(str)
    return list(man.index[f.str.lower().str.endswith(".json") & f.str.contains(META_RE)])


def note_ids(man):
    return guide_ids(man) + [m for m in meta_ids(man) if m not in set(guide_ids(man))]


def meta_text(obj):
    """Texto descriptivo de un JSON de catálogo: result.notes (CKAN) o notes/description/abstract."""
    if isinstance(obj, dict):
        res = obj.get("result") if isinstance(obj.get("result"), dict) else obj
        parts = [res.get(k) for k in ("notes", "description", "abstract") if isinstance(res.get(k), str)]
        return "\n\n".join(p for p in parts if p.strip())
    return ""


def link_guides(man):
    """{note_id: {source_ids de su familia}} según URLs de dataset compartidas."""
    cols = [c for c in ("Source_URL", "Attribution") if c in man.columns]
    urls = {sid: _urls(*(man.at[sid, c] for c in cols)) for sid in man.index}
    return {g: {sid for sid, u in urls.items() if sid != g and urls[g] & u} for g in note_ids(man)}


# ------------------------------------------------------------------ texto -> frases con ubicación
def _is_heading(line):
    s = line.strip()
    return s.startswith("#") or (0 < len(s) < 60 and not re.search(r"[.!?:;]$", s) and not URL_RE.search(s))


def split_units(text, source_id, file_name, kind="guide"):
    """Párrafos numerados (sin contar títulos) y sus frases. kind: "guide" (organizadores) o "meta"."""
    units, para = [], 0
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [ln for ln in block.strip().splitlines() if ln.strip()]
        while lines and _is_heading(lines[0]):
            lines = lines[1:]
        body = " ".join(ln.strip() for ln in lines).strip()
        if not body:
            continue
        para += 1
        for sent in SENT_RE.split(body):
            sent = sent.strip()
            if len(sent) >= 12:
                units.append({"source_id": source_id, "file": file_name, "para": para, "text": sent, "kind": kind})
    return units


# ------------------------------------------------------------------ BM25
def _stem(t):
    if len(t) > 4 and t.endswith("ies"):
        return t[:-3] + "y"
    if len(t) > 4 and t.endswith("es") and t[-3] in "sxz":
        return t[:-2]
    if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
        return t[:-1]
    return t


def tokenize(s):
    return [_stem(t) for t in TOKEN_RE.findall(str(s).lower()) if t not in STOP and len(t) > 1]


# sinónimos genéricos de consulta (inglés común en guías de datos): "empty" debe encontrar "nulls",
# "remove" debe encontrar "drop"/"exclude". Solo se expande la consulta, nunca el texto de la guía.
SYN = {
    "empty": "blank null missing", "blank": "empty null missing", "missing": "null blank empty",
    "null": "blank empty missing", "remove": "drop exclude", "drop": "remove exclude",
    "exclude": "remove drop", "delete": "remove drop", "invalid": "defect repair", "unknown": "null missing",
    "average": "mean", "mean": "average", "share": "percentage", "percent": "percentage",
}


def expand(query):
    """Agrega una vez los sinónimos de cada término de la consulta que esté en SYN."""
    extra = []
    for t in dict.fromkeys(tokenize(query)):
        extra += SYN.get(t, "").split()
    return query + (" " + " ".join(extra) if extra else "")


class GuideIndex:
    def __init__(self, units):
        self.units = units
        self.docs = [tokenize(u["text"]) for u in units]
        self.tf = [Counter(d) for d in self.docs]
        self.N = len(units)
        self.avgdl = (sum(map(len, self.docs)) / self.N) if self.N else 1.0
        # frases que son casi puras URLs (atribución) valen poco como evidencia de un veredicto
        self.weight = [0.5 if sum(map(len, URL_RE.findall(u["text"]))) >= 0.3 * len(u["text"]) else 1.0
                       for u in units]
        df = Counter(t for d in self.docs for t in set(d))
        self.idf = {t: math.log(1 + (self.N - n + 0.5) / (n + 0.5)) for t, n in df.items()}

    def search(self, query, allowed_sources=None, k=3, k1=1.5, b=0.75, kinds=None):
        q = tokenize(query)
        hits = []
        for i, u in enumerate(self.units):
            if allowed_sources is not None and u["source_id"] not in allowed_sources:
                continue
            if kinds is not None and u.get("kind", "guide") not in kinds:
                continue
            tf, dl, s = self.tf[i], len(self.docs[i]), 0.0
            for t in q:
                f = tf.get(t)
                if f:
                    s += self.idf[t] * f * (k1 + 1) / (f + k1 * (1 - b + b * dl / self.avgdl))
            s *= self.weight[i]
            if s > 0:
                hits.append((s, i))
        hits.sort(key=lambda x: (-x[0], x[1]))
        return [{**self.units[i], "score": round(s, 3)} for s, i in hits[:k]]


# ------------------------------------------------------------------ índice por defecto (datos reales)
@lru_cache(maxsize=1)
def default_index():
    try:
        man = loaders.manifest()
    except OSError:
        return GuideIndex([]), {}
    units, metas = [], set(meta_ids(man))
    for g in note_ids(man):
        try:
            path = loaders.path_of(g)
            name = os.path.basename(path).split("__", 1)[-1]
            if g in metas:
                text, name = meta_text(loaders.load_json(g)), f"{name} notes"
            else:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
        except (OSError, ValueError):
            continue
        if text:
            units += split_units(text, g, name, kind="meta" if g in metas else "guide")
    return GuideIndex(units), link_guides(man)


def guides_for(source_ids):
    """Índice y guías relevantes: las citadas en Source_IDs y las vinculadas a esas fuentes."""
    idx, links = default_index()
    sids = set(source_ids or [])
    return idx, {g for g, fam in links.items() if g in sids or fam & sids}


def locator(unit):
    return f"{unit['file']} ¶{unit['para']}"
