"""Carga perfiles YAML y resuelve tablas y filtros con nombre."""
import os

import pandas as pd
import yaml

from . import loaders

PROFILES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "profiles")


class Profile:
    def __init__(self, name: str):
        with open(os.path.join(PROFILES_DIR, f"{name}.yaml"), encoding="utf-8") as fh:
            self.cfg = yaml.safe_load(fh)
        self.name = name
        self._attr_cache = {}

    def table(self, alias: str):
        """Devuelve (DataFrame sin geometría, source_id) de una tabla del perfil."""
        cfg = self.cfg["tables"][alias]
        sid = cfg["source_id"]
        if cfg.get("geo"):
            if alias not in self._attr_cache:
                g = loaders.load_geo(sid)
                self._attr_cache[alias] = pd.DataFrame(g.drop(columns=g.geometry.name))
            return self._attr_cache[alias], sid
        return loaders.load_table(sid), sid

    def geo(self, alias: str):
        """Devuelve (GeoDataFrame nativo, source_id)."""
        sid = self.cfg["tables"][alias]["source_id"]
        return loaders.load_geo(sid), sid

    def plan_tables(self):
        return [a for a, c in self.cfg["tables"].items() if c.get("plan", True)]

    @property
    def metric_epsg(self):
        return self.cfg.get("metric_epsg", 3857)

    def filters(self, *names_or_filters):
        """Combina filtros con nombre (str) y filtros sueltos (dict) en una sola lista."""
        out = []
        for x in names_or_filters:
            if isinstance(x, str):
                out.extend(self.cfg["named_filters"][x]["filters"])
            else:
                out.append(x)
        return out

    def mapping(self, name: str):
        return self.cfg["mappings"][name]


def all_profiles():
    return [f[:-5] for f in sorted(os.listdir(PROFILES_DIR)) if f.endswith(".yaml")]


def profile_for(source_ids):
    """Elige el perfil cuyas fuentes más se solapan con los Source_IDs de una pregunta."""
    best, score = None, 0
    for name in all_profiles():
        p = Profile(name)
        ids = set(p.cfg.get("source_ids", [])) | {t["source_id"] for t in p.cfg["tables"].values()}
        ids |= {t.get("metadata_source_id") for t in p.cfg["tables"].values()} | {p.cfg.get("analysis_source")}
        s = len(ids & set(source_ids))
        if s > score:
            best, score = p, s
    return best
