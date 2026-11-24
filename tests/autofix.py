"""Réplicas sintéticas (pequeñas) de familias reales, con sus mismas rarezas de formato.

Solo se copian nombres de columnas y formatos vistos en el volcado de esquemas; los valores son inventados.
"""
import csv
import json
import os

FAMILIES = {}


def _w(path, text, enc="utf-8"):
    with open(path, "w", encoding=enc, newline="") as fh:
        fh.write(text)


def build(root):
    """Crea data/ con SourceManifest.csv, Test.csv y sources/. Devuelve {familia: [source_ids]}."""
    src = os.path.join(root, "sources")
    os.makedirs(src, exist_ok=True)
    rows, fams = [], {}

    def add(fam, sid, name, pub, text=None, enc="utf-8", writer=None):
        path = os.path.join(src, f"{sid}__{name}")
        if writer:
            writer(path)
        else:
            _w(path, text, enc)
        rows.append([sid, f"sources/{sid}__{name}", pub])
        fams.setdefault(fam, []).append(sid)

    # --- bicis: day.csv + hour.csv + guía
    day = ["instant,dteday,season,yr,mnth,holiday,weekday,workingday,weathersit,temp,casual,registered,cnt"]
    for i in range(1, 9):
        y = 0 if i <= 4 else 1
        day.append(f"{i},201{1 + y}-01-0{i if i <= 4 else i - 4},1,{y},1,0,{i % 7},{1 if i % 7 not in (0, 6) else 0},"
                   f"1,0.{30 + i},{10 * i},{100 * i},{110 * i}")
    add("bike", "SRC_b1", "day.csv", "Fanaee / UCI", "\n".join(day) + "\n")
    hour = ["instant,dteday,season,yr,mnth,hr,holiday,weekday,workingday,weathersit,temp,casual,registered,cnt"]
    k = 1
    for d in ("2012-02-28", "2012-02-29"):
        for h in range(24):
            if d == "2012-02-29" and h == 3:
                continue
            hour.append(f"{k},{d},1,1,2,{h},0,2,1,1,0.2,{h},{2 * h},{3 * h}")
            k += 1
    add("bike", "SRC_b2", "hour.csv", "Fanaee / UCI", "\n".join(hour) + "\n")
    add("bike", "SRC_b3", "SourceGuide.txt", "Challenge organisers",
        "Bike guide\nThe yr code 0 means 2011 and 1 means 2012. Count records, not bikes.\n")

    # --- Toulouse: el mismo dato en CSV (; y BOM) y JSON
    tl = [("2020", 1000, 1000, 1200, -200), ("2021", 2500, 1500, 1700, -200), ("2022", 4200, 1700, 2000, -300)]
    add("toulouse", "SRC_t1", "records.csv", "Mairie de Toulouse",
        "﻿type;annee;solde_net_cumule;solde_net_annuel;plantes_annuel;abattus_annuel\n"
        + "".join(f"observation;{a};{b};{c};{d};{e}\n" for a, b, c, d, e in tl))
    add("toulouse", "SRC_t2", "records.json", "Mairie de Toulouse",
        json.dumps([{"type": "observation", "annee": a, "solde_net_cumule": b, "solde_net_annuel": c,
                     "plantes_annuel": d, "abattus_annuel": e} for a, b, c, d, e in tl]))

    # --- Durban: dos libros xlsx (encabezado en la fila 1) + catálogo CKAN sin registros
    def xlsx_el(path):
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Sheet1"
        ws.append(["Year", "Maximum kVA", "Energy (kWh) sold", "Percent loss (%)", "Number of customers"])
        ws.append(["2006/2007", 1500000, 9000000000, 0.0533, 500000])
        ws.append(["2007/2008", 1510000, 9100000000.5, 0.0501, 510000])
        ws.append(["2008/2009", 1520000, 9200000000.25, 0.0508, 525000])
        wb.save(path)

    def xlsx_fbe(path):
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Year", "Average FBE claims per year"])
        for y, v in (("08/09", 50000), ("09/10", 52000), ("10/11", 54321.123456)):
            ws.append([y, v])
        wb.save(path)
    add("durban", "SRC_d1", "electricity-use.xlsx", "eThekwini / Durban EDGE", writer=xlsx_el)
    add("durban", "SRC_d2", "fbe-claims.xlsx", "eThekwini / Durban EDGE", writer=xlsx_fbe)
    add("durban", "SRC_d3", "CatalogueRecord.json", "eThekwini / Durban EDGE",
        json.dumps({"title": "Electricity", "notes": "Usage", "resources": [
            {"name": "use 1978-2019", "format": "XLSX"}, {"name": "claims", "format": "XLSX"}]}))

    # --- electricidad UCI: ; y coma decimal
    el = ["timestamp;MT_003;MT_162;MT_200"]
    for i, (h, m) in enumerate([(6, 45), (7, 0), (7, 15), (8, 0)]):
        el.append(f"2012-01-16 {h:02d}:{m:02d}:00;0;{150 + i},5;{400 + i},25")
    add("electricity", "SRC_e1", "EightClients.csv", "Trindade / UCI", "\n".join(el) + "\n")

    # --- Montréal: latin-1, coma decimal entre comillas, código con ceros a la izquierda
    add("montreal", "SRC_m1", "outremont.csv", "Ville de Montréal",
        'EMP_NO,ARROND_NOM,Rue,Essence_latin,DHP,Emplacement\n'
        '"0000001","Outremont","DUNLOP","ACER PLATANOIDES","12,00","façade"\n'
        '"0000002","Outremont","DUNLOP","TILIA AMERICANA","0,00","côté"\n'
        '"0000003","Outremont","HARTLAND","ACER PLATANOIDES","86,50","façade"\n', enc="latin-1")

    # --- RNB: JSON con listas anidadas
    add("rnb", "SRC_r1", "Records.json", "Référentiel National des Bâtiments (RNB)", json.dumps([
        {"rnb_id": "AAAA1111", "status": "constructed", "point": {"type": "Point", "coordinates": [3.1, 50.6]},
         "addresses": [{"id": "a1", "ban_id": "x-1", "source": "BAN", "street": "Rue A"},
                       {"id": "a2", "ban_id": None, "source": "bdnb", "street": "Rue A"}],
         "ext_ids": [{"id": "bdnb-1", "source": "bdnb"}]},
        {"rnb_id": "BBBB2222", "status": "constructed", "point": {"type": "Point", "coordinates": [3.2, 50.7]},
         "addresses": [{"id": "b1", "ban_id": "x-2", "source": "BAN", "street": "Rue B"}],
         "ext_ids": [{"id": "bdtopo-9", "source": "bdtopo"}, {"id": "bdnb-2", "source": "bdnb"}]}]))

    # --- Berlín: dos capas hermanas (columnas casi iguales)
    def layer(path, n0, street):
        feats = []
        for i in range(4):
            props = {"gisid": f"{n0}_{i}", "gattung": "Tilia" if i < 2 + street else "Acer",
                     "art_bot": "Tilia cordata" if i < 2 + street else "Acer platanoides",
                     "pflanzjahr": str(1990 + i), "baumhoehe": 10.0 + i, "bezirk": "Mitte"}
            if street:
                props["strname"] = "Rochstraße"
            feats.append({"type": "Feature", "properties": props,
                          "geometry": {"type": "Point", "coordinates": [391000 + 10 * i, 5819600 + 5 * i]}})
        _w(path, json.dumps({"type": "FeatureCollection", "features": feats,
                             "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::25833"}}}))
    add("berlin", "SRC_g1", "anlagenbaeume.geojson", "Berlin Senatsverwaltung", writer=lambda p: layer(p, "p", 0))
    add("berlin", "SRC_g2", "strassenbaeume.geojson", "Berlin Senatsverwaltung", writer=lambda p: layer(p, "s", 1))

    # --- el mismo experimento en CSV y en libro Excel (columnas X/Y; la hoja trae filas vacías al final)
    cols = ["X1", "X5", "X6", "Y1"]
    vals = [(0.9, 7, 2, 11.5), (0.9, 7, 3, 12.25), (0.8, 3.5, 2, 9.75), (0.8, 3.5, 3, 8.5), (0.7, 3.5, 4, 7.0)]
    add("tsanas", "SRC_x1", "data.csv", "Tsanas / UCI",
        ",".join(cols) + "\n" + "".join(f"{a:.2f},{b:.2f},{c},{d:.2f}\n" for a, b, c, d in vals))

    def xlsx_book(path):
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Φύλλο1"
        ws.append(cols)
        for r in vals:
            ws.append(list(r))
        for _ in range(3):
            ws.append([None] * len(cols))
        wb.save(path)
    add("tsanas", "SRC_x2", "ENB_data.xlsx", "Tsanas / UCI", writer=xlsx_book)

    # --- metadatos UCI con lista de variables
    add("uci_meta", "SRC_u1", "Metadata.json", "UCI", json.dumps(
        {"status": 200, "data": {"name": "Energy", "variables": [
            {"name": "X1", "role": "Feature", "description": "Relative Compactness", "units": None},
            {"name": "Y1", "role": "Target", "description": "Heating Load", "units": None}]}}))

    with open(os.path.join(root, "SourceManifest.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Source_ID", "File", "Publisher", "Source_URL", "Attribution", "Derivation"])
        for sid, f, pub in rows:
            w.writerow([sid, f, pub, "", "", ""])
    with open(os.path.join(root, "Test.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["ID", "Case_ID", "Domain", "Question", "Context", "Source_IDs"])
        for i, (fam, sids) in enumerate(fams.items()):
            w.writerow([f"q{i}", "c", "x", f"question about {fam}", "", json.dumps(sids)])
    FAMILIES.clear()
    FAMILIES.update(fams)
    return fams
