"""Carga de fuentes del challenge a partir del SourceManifest.

Todo se resuelve por Source_ID, nunca por nombre de archivo a mano.
Las tablas se cachean: NO modificar los DataFrames devueltos (usar máscaras/copias).
"""
import json
import os
from functools import lru_cache

import pandas as pd

DATA = os.environ.get("GENAI_DATA", os.path.expanduser("~/proyectos/genai-cities-qa/data"))


@lru_cache(maxsize=1)
def manifest() -> pd.DataFrame:
    return pd.read_csv(os.path.join(DATA, "SourceManifest.csv")).set_index("Source_ID")


def path_of(source_id: str) -> str:
    return os.path.join(DATA, manifest().loc[source_id, "File"])


def _to_df(obj):
    """Encuentra la lista de registros dentro de JSON tipo CKAN, GeoJSON o lista simple."""
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        return pd.json_normalize(obj)
    if isinstance(obj, dict):
        if obj.get("type") == "FeatureCollection":
            return pd.json_normalize([f.get("properties", {}) for f in obj["features"]])
        for k in ("records", "result", "data", "features"):
            if k in obj:
                d = _to_df(obj[k])
                if d is not None:
                    return d
    return None


@lru_cache(maxsize=16)
def load_json(source_id: str):
    with open(path_of(source_id), encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache(maxsize=16)
def load_table(source_id: str) -> pd.DataFrame:
    """Devuelve la fuente como tabla. Soporta CSV (utf-8 o latin-1), JSON CKAN y GeoJSON."""
    path = path_of(source_id)
    ext = path.rsplit(".", 1)[-1].lower()
    if ext == "csv":
        try:
            return pd.read_csv(path, low_memory=False)
        except UnicodeDecodeError:
            return pd.read_csv(path, low_memory=False, encoding="latin-1")
    if ext in ("json", "geojson"):
        df = _to_df(load_json(source_id))
        if df is None:
            raise ValueError(f"{source_id}: el JSON no contiene una tabla de registros")
        return df
    raise ValueError(f"{source_id}: formato .{ext} todavía no soportado")


@lru_cache(maxsize=8)
def load_geo(source_id: str):
    """GeoDataFrame con geometría nativa (sin reparar). Cacheado: no modificar."""
    import geopandas as gpd
    return gpd.read_file(path_of(source_id))
