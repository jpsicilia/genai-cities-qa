"""Perfil automático: para preguntas cuyas fuentes no tienen un perfil escrito a mano.

Arma, a partir de los Source_IDs de la pregunta, lo mismo que un perfil YAML le da al planificador y al
ejecutor: tablas con alias, clave, descripción y columnas; reglas (frases de las guías de la familia).
  - Las representaciones repetidas del mismo dato (GML / GeoJSON / GPKG, CSV / JSON) se reducen a una.
  - Si dos capas comparten casi todas las columnas, se agrega una tabla 'combined' (con _layer) para
    preguntas del tipo "combinando ambas capas".
  - Los CSV grandes se describen con una muestra y se cargan enteros solo si una herramienta los usa.
  - Para cada pregunta se eligen las tablas más pertinentes (focus), así el prompt no crece sin control.
"""
import os
import re
from collections import Counter

import pandas as pd

from tools import autoload as A
from tools import guides, loaders
from tools.profiles import Profile

BIG_CSV_BYTES = 25 * 2 ** 20
EXT_PREF = [".csv", ".txt", ".xlsx", ".xlsm", ".ods", ".geojson", ".gpkg", ".json", ".gml"]
TOKEN_RE = re.compile(r"[a-z0-9äöüßéèàçñ]+")
STOP = guides.STOP | {"many", "much", "give", "which", "what", "record", "records", "row", "rows", "file", "data",
                      "number", "value", "values", "total", "please", "use", "using", "supplied", "table"}

# cómo llaman las preguntas a cada formato ("in the CSV", "the workbook"): va a la descripción y al focus
FMT = {".csv": "CSV file", ".txt": "text table", ".xlsx": "Excel workbook", ".xlsm": "Excel workbook",
       ".ods": "ODS spreadsheet", ".json": "JSON file", ".geojson": "GeoJSON file", ".gpkg": "GeoPackage",
       ".gml": "GML file"}
_BOOK = {"workbook", "spreadsheet", "excel", "sheet"}
FMT_TOKENS = {".csv": {"csv"}, ".txt": {"txt"}, ".xlsx": _BOOK | {"xlsx"}, ".xlsm": _BOOK | {"xlsm"},
              ".ods": _BOOK | {"ods"}, ".json": {"json"}, ".geojson": {"geojson"},
              ".gpkg": {"geopackage", "gpkg"}, ".gml": {"gml"}}

AUTO_TOOLS = ["count", "percent", "sum", "mean", "extreme", "distinct", "group_count", "value", "columns"]

AUTO_EXAMPLES = [  # estructura, no nombres: el esquema JSON obliga a usar las tablas y columnas reales
    {"q": "How many orders have status 'late', and what share of all orders is that?",
     "plan": {"calls": [
         {"tool": "count", "table": "orders", "filters": [{"field": "status", "op": "eq", "value": "late"}]},
         {"tool": "percent", "table": "orders", "filters": [{"field": "status", "op": "eq", "value": "late"}],
          "denominator": []}]}},
    {"q": "What were the sales in 2019 and in 2021? Give the percentage change from 2019.",
     "plan": {"calls": [
         {"tool": "value", "table": "yearly", "field": "sales", "filters": [{"field": "year", "op": "eq", "value": 2019}]},
         {"tool": "value", "table": "yearly", "field": "sales", "filters": [{"field": "year", "op": "eq", "value": 2021}]}]}},
    {"q": "Total rentals in 2012, and the mean temperature on working days?",
     "plan": {"calls": [
         {"tool": "sum", "table": "daily", "field": "rentals", "filters": [{"field": "yr", "op": "eq", "value": 2012}]},
         {"tool": "mean", "table": "daily", "field": "temp", "filters": [{"field": "workingday", "op": "eq", "value": 1}]}]}},
    {"q": "Which brand is most common among red cars, and which car has the lowest price?",
     "plan": {"calls": [
         {"tool": "group_count", "table": "cars", "field": "brand", "filters": [{"field": "colour", "op": "eq", "value": "red"}]},
         {"tool": "extreme", "table": "cars", "field": "price", "which": "min"}]}},
]


def _orig(path):
    """Nombre original del archivo, sin el prefijo SRC_xxx__."""
    return os.path.basename(path).split("__", 1)[-1]


def _stem(path):
    return os.path.splitext(_orig(path))[0]


def _ext(path):
    return os.path.splitext(path or "")[1].lower()


def _tokens(s):
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(s))
    return [t for t in TOKEN_RE.findall(s.lower()) if t not in STOP and len(t) > 1]


class AutoProfile(Profile):
    """Perfil construido al vuelo. Misma interfaz que Profile (cfg, table, geo, plan_tables...)."""

    def __init__(self, source_ids):
        self.name = "auto"
        self.source_ids = [s for s in source_ids]
        self._attr_cache = {}
        self._t = {}            # alias -> {sid, path, info, df (o None si diferida), sample, kind}
        self._focus = None
        self.cfg = {"tables": {}, "tools": list(AUTO_TOOLS), "examples": AUTO_EXAMPLES, "rules_for_llm": [],
                    "source_ids": list(source_ids), "auto": True}
        self._build()

    # -------------------------------------------------------------- construcción
    def _register(self, alias, sid, path, df, info, lazy=False):
        a, k = alias, 2
        while a in self._t:
            a, k = f"{alias}_{k}", k + 1
        self._t[a] = {"sid": sid, "path": path, "info": info, "df": None if lazy else df,
                      "sample": df, "lazy": lazy}
        return a

    def _build(self):
        try:
            man = loaders.manifest()
        except OSError:
            return
        regs = []
        for sid in self.source_ids:
            if sid not in man.index:
                continue
            path = loaders.path_of(sid)
            if not os.path.exists(path) or "organis" in str(man.at[sid, "Publisher"]).lower() and \
                    path.lower().endswith((".md", ".txt")):
                continue
            stem = A.slug(_stem(path))
            try:
                if A.is_csv_like(path) and os.path.getsize(path) > BIG_CSV_BYTES:
                    if path.lower().endswith(".txt") and not A.looks_tabular(path):
                        continue
                    sample, info = A.sample_csv(path)
                    info = {**info, "rows": A.count_rows(path), "sampled": True}
                    regs.append((stem, "", sid, path, sample, info, True))
                    continue
                for suffix, df, info in A.read_any(path):
                    part = {"part": suffix} if suffix and not info.get("sheet") else {}
                    regs.append((stem, suffix, sid, path, df, {**info, **part, "rows": len(df)}, False))
            except Exception as e:  # noqa: BLE001 — un archivo raro no debe tumbar la pregunta
                regs.append((stem, "error", sid, path, pd.DataFrame(), {"error": f"{type(e).__name__}: {e}"}, False))
        # representaciones repetidas: mismo nombre, mismas columnas y mismas filas -> una sola
        kept, seen = [], {}
        for stem, suffix, sid, path, df, info, lazy in sorted(
                regs, key=lambda r: EXT_PREF.index(os.path.splitext(r[3])[1].lower())
                if os.path.splitext(r[3])[1].lower() in EXT_PREF else 99):
            if suffix == "error" or df is None or df.shape[1] < 2:
                continue
            cols = frozenset(c for c in df.columns if c not in ("id", "gml_id", "_row", "fid"))
            sig = (stem, suffix, cols, info.get("rows"))
            if sig in seen:
                seen[sig].setdefault("alternatives", []).append(sid)
                continue
            seen[sig] = info
            kept.append((f"{stem}_{A.slug(suffix)}" if suffix else stem, sid, path, df, info, lazy))
        # nombres repetidos con datos distintos (GRDF: dos records.csv): se distinguen por su primera columna
        bases = Counter(b for b, *_ in kept)
        for base, sid, path, df, info, lazy in kept:
            alias = base
            if bases[base] > 1:
                first = next((c for c in df.columns if not str(c).startswith("_")), "t")
                alias = f"{base}_{A.slug(first)}"
            self._register(alias, sid, path, df, info, lazy)
        self._add_combined()
        for a, t in self._t.items():
            df = t["sample"]
            self.cfg["tables"][a] = {"source_id": t["sid"], "key": A._guess_key(df) if not t["lazy"] else None,
                                     "description": self._describe(a), "plan": True,
                                     "geo": False}

    def _add_combined(self):
        """Capas hermanas -> tabla combinada con _layer. Hermanas = columnas casi iguales Y la misma clave con
        valores disjuntos (árboles de parque y de calle). Si las claves se pisan (day/hour, fotos anuales de los
        mismos edificios) no son capas de un mismo registro y no se combinan."""
        al = [a for a, t in self._t.items() if not t["lazy"] and len(t["sample"]) and "sheet" not in t["info"]]
        done = set()
        for i, a in enumerate(al):
            group = [a]
            da = self._t[a]["sample"]
            ca = set(da.columns) - {"id", "gml_id", "_row", "fid"}
            ka = A._guess_key(da)
            for b in al[i + 1:]:
                db = self._t[b]["sample"]
                cb = set(db.columns) - {"id", "gml_id", "_row", "fid"}
                if b in done or len(ca & cb) / max(len(ca | cb), 1) < 0.8 or len(ca & cb) < 3:
                    continue
                if not ka or A._guess_key(db) != ka:
                    continue
                if set(da[ka].astype(str)) & set(db[ka].astype(str)):
                    continue
                group.append(b)
            if len(group) >= 2 and not done & set(group):
                done |= set(group)
                frames = [self._t[g]["sample"].assign(_layer=g) for g in group]
                df = pd.concat(frames, ignore_index=True, sort=False)
                self._register("combined", self._t[group[0]]["sid"], None, df, {"rows": len(df), "combined_of": group})

    def _file_of(self, sid):
        try:
            return _orig(loaders.path_of(sid))
        except (KeyError, OSError):
            return sid

    def _describe(self, alias):
        """Lo que el planificador necesita para elegir tabla: de qué archivo y formato sale ("in the CSV",
        "the workbook"), hoja o parte, y si hay otras copias del mismo dato."""
        t = self._t[alias]
        info, bits = t["info"], []
        if t.get("path"):
            src = f"from {_orig(t['path'])}" + (f" ({FMT[_ext(t['path'])]})" if _ext(t["path"]) in FMT else "")
            if info.get("part"):
                src += f", part '{info['part']}'"
            bits.append(src)
        if info.get("sheet"):
            bits.append(f"sheet '{info['sheet']}' (header on row {info.get('header_row')}; _row = Excel row)")
        if info.get("combined_of"):
            bits.append("all records of " + " + ".join(info["combined_of"]) + "; _layer tells which")
        if info.get("sampled"):
            bits.append(f"large file, {info.get('rows')} rows")
        if info.get("alternatives"):
            bits.append("same data also supplied as " + ", ".join(self._file_of(s) for s in info["alternatives"]))
        return "; ".join(bits)

    # -------------------------------------------------------------- interfaz de Profile
    def table(self, alias):
        t = self._t[alias]
        if t["df"] is None:                       # carga diferida del CSV grande
            t["df"], _ = A.read_delimited(t["path"])
            self.cfg["tables"][alias]["key"] = A._guess_key(t["df"])
        return t["df"], t["sid"]

    def geo(self, alias):
        return loaders.load_geo(self._t[alias]["sid"]), self._t[alias]["sid"]

    def plan_tables(self):
        return list(self._focus) if self._focus else list(self._t)

    def info(self, alias):
        return self._t[alias]["info"]

    def combined_sources(self, alias):
        """[(source_id, capa, filas)] de las capas de una tabla combinada, salvo la primera (ya citada)."""
        grp = self._t[alias]["info"].get("combined_of") or []
        return [(self._t[g]["sid"], g, len(self._t[g]["sample"])) for g in grp[1:]]

    def sample(self, alias):
        """La tabla entera si ya está cargada; si no, la muestra (para describirla en el prompt)."""
        t = self._t[alias]
        return t["df"] if t["df"] is not None else t["sample"]

    @property
    def metric_epsg(self):
        return 3857

    # -------------------------------------------------------------- foco por pregunta
    def _table_tokens(self, alias):
        t = self._t[alias]
        if "tokens" in t:
            return t["tokens"]
        df = t["sample"].head(5000)
        toks = Counter()
        for x in _tokens(alias):
            toks[x] += 3
        for x in FMT_TOKENS.get(_ext(t.get("path")), ()):     # "in the CSV" / "the workbook"
            toks[x] += 3
        for x in _tokens(_stem(t["path"])) if t.get("path") else ():
            toks[x] += 3
        for c in df.columns:
            for x in _tokens(c):
                toks[x] += 2
            s = df[c]
            if not pd.api.types.is_numeric_dtype(s):
                vals = s.dropna().astype(str)
                if 0 < vals.nunique() <= 60:
                    for v in vals.unique()[:60]:
                        for x in _tokens(v):
                            toks[x] += 1
        t["tokens"] = toks
        t["values"] = {str(c) for c in df.columns} | {
            v for c in df.columns if not pd.api.types.is_numeric_dtype(df[c])
            for v in df[c].dropna().astype(str).unique()[:5000]}
        return toks

    def focus(self, question, k=3):
        """Elige las k tablas más pertinentes para la pregunta (nombres, columnas y valores que menciona)."""
        q = set(_tokens(question))
        q |= {w[:-3] + "y" if w.endswith("ily") else w[:-2] for w in q if w.endswith("ly") and len(w) > 4}
        raw = set(re.findall(r"[A-Za-z0-9_./:-]{3,}", question or ""))
        scores = []
        for a, t in self._t.items():
            toks = self._table_tokens(a)
            s = sum(min(toks[x], 3) for x in q if x in toks)
            exact = sum(1 for r in raw if r in t["values"])
            scores.append((s + 3 * exact, -len(t["sample"].columns), a))
        scores.sort(reverse=True)
        self._focus = [a for s, _, a in scores[:k]] if scores else None
        return self._focus

    # -------------------------------------------------------------- notas de las guías
    def notes_for(self, question, k=6):
        idx, gids = guides.guides_for(self.source_ids)
        if not gids:
            return []
        hits = idx.search(guides.expand(question), gids, k=k, kinds={"guide"})
        return [h["text"] for h in hits]


def has_tables(source_ids):
    """¿Hay al menos una fuente tabular entre los Source_IDs? (rápido: solo mira extensiones)"""
    try:
        man = loaders.manifest()
    except OSError:
        return False
    for sid in source_ids:
        if sid in man.index:
            f = str(man.at[sid, "File"]).lower()
            if os.path.splitext(f)[1] in A.TABLE_EXT and "organis" not in str(man.at[sid, "Publisher"]).lower():
                return True
    return False

