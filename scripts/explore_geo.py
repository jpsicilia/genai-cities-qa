"""Explora la GEOMETRÍA de fuentes vectoriales: CRS, tipos, Z, validez, extensión y ejemplos.
Uso: python scripts/explore_geo.py SRC_xxx SRC_yyy ... > salida.txt
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import geopandas as gpd  # noqa: E402
from shapely.validation import explain_validity  # noqa: E402

from tools import loaders  # noqa: E402

for sid in sys.argv[1:]:
    path = loaders.path_of(sid)
    print(f"\n######## {sid} | {os.path.basename(path)}")
    try:
        g = gpd.read_file(path)
    except Exception as e:
        print("  ERROR leyendo:", repr(e))
        continue
    print("  filas:", len(g), "| CRS:", g.crs)
    print("  tipos:", g.geom_type.value_counts(dropna=False).to_dict())
    print("  has_z:", g.has_z.value_counts().to_dict(), "| vacías:", int(g.is_empty.sum()), "| nulas:", int(g.geometry.isna().sum()))
    print("  extensión (bounds):", [round(v, 6) for v in g.total_bounds])
    inval = g[~g.is_valid]
    print("  inválidas:", len(inval))
    for i, r in inval.head(5).iterrows():
        ident = {c: r[c] for c in g.columns if c in ("baumnummer", "objectid", "objid")}
        print("    ", ident, "->", explain_validity(r.geometry))
    first = g.geometry.iloc[0]
    print("  primera geometría (recorte):", first.wkt[:300])
    if g.geom_type.isin(["Polygon", "MultiPolygon"]).any():
        for epsg in (2056, 3857):
            try:
                a = g.to_crs(epsg).area
                print(f"  área en EPSG:{epsg}: min {a.min():.3f} | mediana {a.median():.3f} | max {a.max():.3f}")
            except Exception as e:
                print(f"  área EPSG:{epsg} ERROR:", repr(e))
