"""Tests de herramientas espaciales con geometría sintética de respuesta conocida (no usan datos del Test)."""

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import MultiPolygon, Point, Polygon

from tools import spatial as S

EPSG = 2056
X0, Y0 = 2683000.0, 1248000.0  # Zúrich en LV95


def to4326(geoms, **cols):
    return gpd.GeoDataFrame(cols, geometry=geoms, crs=EPSG).to_crs(4326)


@pytest.fixture
def pts():
    # A en el origen; B a 30 m; C a 75 m exactos (borde); D a 75.5 m
    return to4326([Point(X0, Y0), Point(X0 + 30, Y0), Point(X0, Y0 + 75), Point(X0 + 75.5, Y0)],
                  id=["A", "B", "C", "D"], year=[1990, 2005, 2010, None])


def test_nearest(pts):
    r = S.nearest(pts, "id", "A", EPSG)
    assert r["value"]["id"] == "B" and abs(r["value"]["distance"] - 30) < 0.01


def test_radius_includes_boundary_and_anchor(pts):
    r = S.within_radius(pts, "id", "A", 75, EPSG)
    assert r["value"] == 3  # A, B, C (C justo en el borde)


def test_radius_with_filter(pts):
    r = S.within_radius(pts, "id", "A", 75, EPSG, [{"field": "year", "op": "ge", "value": 2000}])
    assert r["n_match"] == 2 and abs(r["percent"] - 200 / 3) < 1e-9


def test_areas_and_difference():
    sq10 = Polygon([(X0, Y0), (X0 + 10, Y0), (X0 + 10, Y0 + 10), (X0, Y0 + 10)])
    sq5 = Polygon([(X0 + 50, Y0), (X0 + 55, Y0), (X0 + 55, Y0 + 5), (X0 + 50, Y0 + 5)])
    g = to4326([MultiPolygon([sq10]), MultiPolygon([sq5])], k=["big", "small"])
    r = S.areas(g, "k", ["big", "small"], EPSG)
    assert abs(r["value"]["big"] - 100) < 0.05 and abs(r["difference"] - 75) < 0.05
    assert r["largest"][0] == "big"


def test_validity_reports_without_repair():
    bowtie = Polygon([(X0, Y0), (X0 + 10, Y0 + 10), (X0 + 10, Y0), (X0, Y0 + 10)])
    ok = Polygon([(X0, Y0), (X0 + 1, Y0), (X0 + 1, Y0 + 1)])
    g = to4326([bowtie, ok], k=["bad", "good"])
    r = S.validity(g, "k")
    assert r["value"] == 1 and r["invalid"][0][0] == "bad"


def test_z_extent():
    tri = Polygon([(8.5, 47.3, 430.0), (8.50001, 47.3, 431.5), (8.5, 47.30001, 433.25)])
    g = gpd.GeoDataFrame({"k": ["t"], "h": [20.0]}, geometry=[MultiPolygon([tri])], crs=4979)
    r = S.z_extent(g, "k", ["t"], show=["h"])
    assert abs(r["value"]["t"] - 3.25) < 1e-9 and "h=20.0" in r["display"]


def test_symbol_radius():
    c = Point(X0, Y0).buffer(0.13, quad_segs=256)
    r = S.symbol_radius(to4326([c]), EPSG)
    assert abs(r["value"] - 0.13) < 0.002


def test_key_audit_and_prefixes():
    reg = pd.DataFrame({"baumnummer": ["AA-1", "AA-2", "nn-3"]})
    inv = pd.DataFrame({"baumnummer": ["BK_AA-1", "BK_AA-9", "TLM3D_EB-1", "BK_BK_X"]})
    r = S.key_audit(reg, "baumnummer", inv, "baumnummer", strip_prefix="BK_", keep_prefix="BK_")
    assert (r["both"], r["only_a"], r["only_b"]) == (1, 2, 2)  # 'BK_BK_X' -> 'BK_X' (solo un prefijo)
    p = S.prefix_counts(inv, "baumnummer", ["BK_", "TLM3D_"])
    assert p["value"] == {"BK_": 3, "TLM3D_": 1, "other": 0}
