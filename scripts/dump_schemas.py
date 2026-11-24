"""Vuelca un esquema compacto de cada fuente que usan las preguntas de Test.csv SIN perfil todavía.

Para diseñar el perfil automático (familias nuevas) sin subir los datos: columnas, tipos, nulos y ejemplos;
hojas de cálculo con coordenadas de celda; rásteres; nubes de puntos; XML/IFC/SQLite; texto de guías y PDFs.
Solo lee: no modifica nada. Cada archivo tiene un tope de tamaño de salida y sus errores no cortan el resto.

Uso:
    python -u scripts/dump_schemas.py --out runs/schemas.txt          # familias sin perfil
    python -u scripts/dump_schemas.py --out runs/schemas.txt --all    # todas
Opcionales (más detalle si están instalados): openpyxl, odfpy, pypdf, rasterio, laspy[lazrs].
"""
import argparse
import collections
import csv
import json
import os
import re
import shutil
import sqlite3
import struct
import subprocess
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd  # noqa: E402

from tools import loaders, profiles  # noqa: E402

TEXT_EXT = {".md", ".txt", ".html", ".htm", ".xsd"}


# ------------------------------------------------------------------ utilidades
def human(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {u}"
        n /= 1024
    return f"{n:.1f} TB"


def clip(s, n=60):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def col_letter(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def table_summary(df, out, total_rows=None, max_cols=60):
    out.append(f"  filas{' (muestra)' if total_rows else ''}: {len(df)}" + (f" | filas totales: {total_rows}" if total_rows else "")
               + f" | columnas: {df.shape[1]}")
    for c in list(df.columns)[:max_cols]:
        s = df[c]
        nn = s.dropna()
        try:
            nun = nn.astype(str).nunique()
            ex = [clip(x, 40) for x in nn.astype(str).drop_duplicates().head(3)]
            blank = int(nn.astype(str).str.strip().eq("").sum())
        except Exception:  # noqa: BLE001  (listas/dicts anidados)
            nun, ex, blank = "?", [clip(x, 40) for x in nn.head(2)], 0
        out.append(f"   - {clip(c, 45)} [{s.dtype}] nulos={int(s.isna().sum())}" + (f" vacíos={blank}" if blank else "")
                   + f" distintos={nun} ej={ex}")
    if df.shape[1] > max_cols:
        out.append(f"   … y {df.shape[1] - max_cols} columnas más: {', '.join(map(str, list(df.columns)[max_cols:max_cols + 40]))}")


def count_lines(path):
    n = 0
    with open(path, "rb") as fh:
        for buf in iter(lambda: fh.read(1 << 20), b""):
            n += buf.count(b"\n")
    return n


def sniff(path):
    with open(path, "rb") as fh:
        raw = fh.read(65536)
    enc = "utf-8"
    try:
        sample = raw.decode("utf-8")
    except UnicodeDecodeError:
        enc, sample = "latin-1", raw.decode("latin-1")
    try:
        delim = csv.Sniffer().sniff(sample.split("\n", 20)[-2] if sample.count("\n") > 20 else sample,
                                    delimiters=",;\t|").delimiter
    except csv.Error:
        delim = ","
    first = sample.split("\n", 1)[0]
    if first.count(";") > first.count(delim):
        delim = ";"
    return delim, enc, sample


# ------------------------------------------------------------------ volcadores por formato
def dump_delimited(path, out):
    delim, enc, sample = sniff(path)
    lines = count_lines(path)
    df = pd.read_csv(path, sep=delim, nrows=3000, dtype=str, encoding=enc, encoding_errors="replace",
                     on_bad_lines="skip", engine="python" if delim not in ",;\t|" else "c")
    out.append(f"  delimitador={delim!r} codificación={enc} líneas={lines}")
    if df.shape[1] == 1 and len(sample) > 200 and sample.count(delim) < 3:
        return dump_text(path, out)
    table_summary(df, out, total_rows=max(lines - 1, 0))


def dump_text(path, out, limit=6000):
    with open(path, encoding="utf-8", errors="replace") as fh:
        txt = fh.read(limit + 1)
    if path.lower().endswith((".html", ".htm")):
        txt = re.sub(r"<script.*?</script>|<style.*?</style>", " ", txt, flags=re.S | re.I)
        txt = re.sub(r"<[^>]+>", " ", txt)
        txt = re.sub(r"[ \t]+", " ", txt)
    out.append("  texto:\n" + "\n".join("    " + ln for ln in txt[:limit].strip().splitlines() if ln.strip()))
    if len(txt) > limit:
        out.append("    … (recortado)")


def _structure(obj, depth=0, max_depth=3):
    pad = "  " * (depth + 2)
    if isinstance(obj, dict):
        lines = []
        for k, v in list(obj.items())[:30]:
            if isinstance(v, (dict, list)) and depth < max_depth:
                lines.append(f"{pad}{k}: {type(v).__name__}" + (f"[{len(v)}]" if isinstance(v, list) else ""))
                lines += _structure(v, depth + 1, max_depth)
            else:
                lines.append(f"{pad}{k}: {clip(v, 70)!s}")
        if len(obj) > 30:
            lines.append(f"{pad}… {len(obj) - 30} claves más")
        return lines
    if isinstance(obj, list) and obj:
        return [f"{pad}[0] →"] + _structure(obj[0], depth + 1, max_depth)
    return []


def dump_json(path, out, size):
    if size > 80 * 2 ** 20:
        with open(path, encoding="utf-8", errors="replace") as fh:
            out.append("  (JSON grande: solo el comienzo) " + clip(fh.read(1500), 1500))
        return
    with open(path, encoding="utf-8") as fh:
        obj = json.load(fh)
    if isinstance(obj, dict) and obj.get("type") == "FeatureCollection":
        feats = obj.get("features", [])
        gt = collections.Counter((f.get("geometry") or {}).get("type") for f in feats[:5000])
        out.append(f"  GeoJSON: {len(feats)} features | geometrías: {dict(gt)} | crs: {obj.get('crs')}")
        props = pd.json_normalize([f.get("properties") or {} for f in feats[:3000]])
        table_summary(props, out, total_rows=len(feats))
        return
    df = loaders._to_df(obj)
    out.append("  estructura:")
    out += _structure(obj)[:80]
    if df is not None and len(df.columns) > 1:
        out.append("  tabla encontrada:")
        table_summary(df.head(3000), out, total_rows=len(df))


def dump_geo(path, out):
    import pyogrio
    try:
        layers = pyogrio.list_layers(path)
    except Exception:  # noqa: BLE001
        layers = [[None, None]]
    for name, gtype in list(layers)[:6]:
        info = pyogrio.read_info(path, layer=name)
        out.append(f"  capa={name!r} geometría={info.get('geometry_type') or gtype} features={info.get('features')} "
                   f"crs={info.get('crs')} bounds={info.get('total_bounds')}")
        df = pyogrio.read_dataframe(path, layer=name, max_features=2000, read_geometry=False)
        table_summary(df, out, total_rows=info.get("features"))


def dump_xlsx(path, out, max_rows=40, max_cols=20):
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    for ws in wb.worksheets[:12]:
        out.append(f"  hoja {ws.title!r}: {ws.max_row} filas × {ws.max_column} columnas")
        for r_i, row in enumerate(ws.iter_rows(max_row=max_rows, max_col=max_cols), 1):
            cells = []
            for c in row:
                if c.value not in (None, ""):
                    fmt = getattr(c, "number_format", "General")
                    cells.append(f"{c.coordinate}={clip(c.value, 38)!s}" + (f" [{fmt}]" if fmt not in ("General", None)
                                                                              and isinstance(c.value, (int, float)) else ""))
            if cells:
                out.append(f"    r{r_i}: " + " | ".join(cells))


def dump_ods(path, out, max_rows=40, max_cols=20):
    sheets = pd.read_excel(path, engine="odf", sheet_name=None, header=None, nrows=max_rows)
    for name, df in list(sheets.items())[:12]:
        out.append(f"  hoja {name!r}: (primeras {len(df)} filas leídas) × {df.shape[1]} columnas")
        for r_i, row in df.iloc[:, :max_cols].iterrows():
            cells = [f"{col_letter(j)}{r_i + 1}={clip(v, 38)}" for j, v in enumerate(row) if pd.notna(v) and str(v) != ""]
            if cells:
                out.append(f"    r{r_i + 1}: " + " | ".join(cells))


def dump_pdf(path, out):
    try:
        from pypdf import PdfReader
        rd = PdfReader(path)
        out.append(f"  páginas: {len(rd.pages)}")
        txt = "\n".join((p.extract_text() or "") for p in rd.pages[:2])
    except ImportError:
        if not shutil.which("pdftotext"):
            out.append("  (instala pypdf para ver el texto)")
            return
        txt = subprocess.run(["pdftotext", "-l", "2", "-layout", path, "-"], capture_output=True, text=True).stdout
    out.append("  texto (pág. 1-2):\n" + "\n".join("    " + clip(ln, 160) for ln in txt.splitlines()[:60] if ln.strip()))


def dump_tif(path, out):
    try:
        import numpy as np
        import rasterio
        from rasterio.enums import Resampling
        with rasterio.open(path) as ds:
            out.append(f"  {ds.width}×{ds.height} px | bandas={ds.count} | dtype={ds.dtypes[0]} | crs={ds.crs} | "
                       f"nodata={ds.nodata} | res={ds.res} | bounds={tuple(round(b, 3) for b in ds.bounds)}")
            a = ds.read(1, out_shape=(min(ds.height, 600), min(ds.width, 600)), resampling=Resampling.nearest,
                        masked=True)
            v = a.compressed()
            if v.size and np.issubdtype(v.dtype, np.integer) and len(np.unique(v)) <= 60:
                u, c = np.unique(v, return_counts=True)
                out.append("  valores (muestra reducida): " + ", ".join(f"{a_}:{b_}" for a_, b_ in zip(u, c)))
            elif v.size:
                out.append(f"  muestra: min={v.min():.3f} max={v.max():.3f} media={v.mean():.3f}")
    except ImportError:
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = None
        with Image.open(path) as im:
            tags = {k: im.tag_v2.get(k) for k in (33550, 33922, 34737, 42113) if k in im.tag_v2}
            out.append(f"  (sin rasterio) {im.size[0]}×{im.size[1]} px | modo={im.mode} | escala={tags.get(33550)} | "
                       f"tiepoint={tags.get(33922)} | nodata={tags.get(42113)} | crs_txt={clip(tags.get(34737), 120)}")


def dump_las(path, out):
    with open(path, "rb") as fh:
        h = fh.read(375)
    if h[:4] != b"LASF":
        out.append("  no es LAS/LAZ")
        return
    ver = f"{h[24]}.{h[25]}"
    fmt = h[104] & 0x3F
    npts = struct.unpack("<I", h[107:111])[0]
    if h[24] == 1 and h[25] >= 4 and len(h) >= 255:
        npts = struct.unpack("<Q", h[247:255])[0] or npts
    sc = struct.unpack("<3d", h[131:155])
    mx = struct.unpack("<6d", h[179:227])
    out.append(f"  LAS {ver} | formato de punto {fmt}{' (comprimido LAZ)' if h[104] & 0x80 else ''} | puntos={npts} | "
               f"escala={sc} | X[{mx[1]:.2f},{mx[0]:.2f}] Y[{mx[3]:.2f},{mx[2]:.2f}] Z[{mx[5]:.2f},{mx[4]:.2f}]")
    try:
        import laspy
        with laspy.open(path) as f:
            out.append(f"  dimensiones: {list(f.header.point_format.dimension_names)} | crs: {clip(f.header.parse_crs(), 120)}")
            pts = next(f.chunk_iterator(200000))
            cls = collections.Counter(map(int, pts.classification))
            out.append(f"  clases (primeros {len(pts)} puntos): {dict(sorted(cls.items()))}")
    except Exception as e:  # noqa: BLE001
        out.append(f"  (detalle por punto no disponible: {type(e).__name__}; instala laspy[lazrs])")


def dump_xml(path, out, size):
    with open(path, "rb") as fh:
        head = fh.read(min(size, 2 * 2 ** 20)).decode("utf-8", errors="replace")
    tags = collections.Counter(re.findall(r"<([A-Za-z_][\w:.-]*)", head))
    out.append(f"  etiquetas más frecuentes (primeros 2 MB): {dict(tags.most_common(25))}")
    out.append("  comienzo:\n    " + clip(head, 2500))


def dump_zip(path, out):
    with zipfile.ZipFile(path) as z:
        for i in z.infolist()[:60]:
            out.append(f"   - {i.filename} ({human(i.file_size)})")


def dump_ifc(path, out):
    head, ents = [], collections.Counter()
    with open(path, encoding="utf-8", errors="replace") as fh:
        for ln in fh:
            if len(head) < 25:
                head.append(ln.rstrip())
            m = re.search(r"=\s*(IFC[A-Z0-9]+)\(", ln)
            if m:
                ents[m.group(1)] += 1
    out.append("  cabecera:\n" + "\n".join("    " + clip(h, 160) for h in head))
    out.append(f"  entidades ({sum(ents.values())}): {dict(ents.most_common(40))}")


def dump_sqlite(path, out):
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        tabs = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view') ORDER BY name")]
        for t in tabs[:30]:
            cols = [f"{r[1]}:{r[2]}" for r in con.execute(f'PRAGMA table_info("{t}")')]
            n = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            out.append(f"   - {t}: {n} filas | {', '.join(cols[:25])}")
    finally:
        con.close()


def dump_image(path, out):
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    with Image.open(path) as im:
        out.append(f"  imagen {im.size[0]}×{im.size[1]} px | modo={im.mode}")


def dump_source(sid, man, max_kb):
    path = loaders.path_of(sid)
    ext = os.path.splitext(path)[1].lower()
    size = os.path.getsize(path) if os.path.exists(path) else 0
    row = man.loc[sid]
    out = [f"\n=== {sid} | {row['File']} | {human(size)} | {clip(row['Publisher'], 80)}",
           f"  derivación: {clip(row.get('Derivation', ''), 220)}"]
    if not os.path.exists(path):
        out.append("  (archivo no encontrado)")
        return out
    organiser = "organis" in str(row["Publisher"]).lower()
    try:
        if ext in (".csv",) or (ext == ".txt" and not organiser):
            dump_delimited(path, out)
        elif ext in TEXT_EXT:
            dump_text(path, out)
        elif ext == ".json":
            dump_json(path, out, size)
        elif ext in (".geojson", ".gpkg", ".gml", ".shp"):
            dump_geo(path, out)
        elif ext in (".xlsx", ".xlsm"):
            dump_xlsx(path, out)
        elif ext == ".ods":
            dump_ods(path, out)
        elif ext == ".pdf":
            dump_pdf(path, out)
        elif ext in (".tif", ".tiff"):
            dump_tif(path, out)
        elif ext in (".las", ".laz"):
            dump_las(path, out)
        elif ext == ".xml":
            dump_xml(path, out, size)
        elif ext == ".zip":
            dump_zip(path, out)
        elif ext == ".ifc":
            dump_ifc(path, out)
        elif ext in (".sqlite", ".db", ".gpkg-journal"):
            dump_sqlite(path, out)
        elif ext in (".jpg", ".jpeg", ".png"):
            dump_image(path, out)
        else:
            out.append("  (formato sin volcador)")
    except ImportError as e:
        out.append(f"  (falta un paquete opcional: {e.name}; pip install {e.name})")
    except Exception as e:  # noqa: BLE001
        out.append(f"  ERROR {type(e).__name__}: {clip(e, 200)}")
    txt = "\n".join(out)
    wide = ext in (".xlsx", ".xlsm", ".ods") or (organiser and ext in TEXT_EXT)   # hojas y guías: doble tope
    cap = max_kb * 1024 * (2 if wide else 1)
    if len(txt.encode()) > cap:
        txt = txt.encode()[:cap].decode("utf-8", errors="ignore") + "\n  … (recortado por tamaño)"
    return [txt]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="runs/schemas.txt")
    ap.add_argument("--all", action="store_true", help="incluir también las familias que ya tienen perfil")
    ap.add_argument("--max-kb", type=int, default=6, help="tope de salida por archivo (KB)")
    a = ap.parse_args()

    man = loaders.manifest()
    test = pd.read_csv(os.path.join(loaders.DATA, "Test.csv"))
    fams = collections.OrderedDict()
    for _, r in test.iterrows():
        sids = json.loads(r["Source_IDs"])
        if not a.all and profiles.profile_for(sids) is not None:
            continue
        pubs = sorted({str(man.loc[s, "Publisher"]) for s in sids if s in man.index
                       and "organis" not in str(man.loc[s, "Publisher"]).lower()})
        key = (r["Domain"], " / ".join(pubs)[:120] or "(solo organizadores)")
        f = fams.setdefault(key, {"qs": [], "sids": []})
        f["qs"].append(r["Question"])
        f["sids"] += [s for s in sids if s not in f["sids"]]

    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    done, n_src = set(), sum(len(f["sids"]) for f in fams.values())
    k = 0
    with open(a.out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(f"# Esquemas de fuentes | familias: {len(fams)} | preguntas: {sum(len(f['qs']) for f in fams.values())}\n")
        for (dom, pubs), f in sorted(fams.items(), key=lambda kv: -len(kv[1]["qs"])):
            fh.write(f"\n\n######## FAMILIA {dom} | {pubs} | preguntas: {len(f['qs'])}\n")
            for q in f["qs"][:3]:
                fh.write(f"  Q: {clip(q, 220)}\n")
            fh.write(f"  fuentes: {', '.join(f['sids'])}\n")
            for sid in f["sids"]:
                k += 1
                if sid in done or sid not in man.index:
                    continue
                done.add(sid)
                print(f"[{k}/{n_src}] {sid} {man.loc[sid, 'File']}", file=sys.stderr, flush=True)
                fh.write("\n".join(dump_source(sid, man, a.max_kb)) + "\n")
                fh.flush()
    print(f"listo: {len(done)} fuentes en {len(fams)} familias -> {a.out} ({human(os.path.getsize(a.out))})")


if __name__ == "__main__":
    main()
