"""Humo: el volcado de esquemas corre de punta a punta sobre una carpeta de datos mínima."""
import csv
import json
import os
import subprocess
import sys


def test_dump_schemas_smoke(tmp_path):
    src = tmp_path / "sources"
    src.mkdir()
    (src / "SRC_x1__trips.txt").write_text("trip_id,bikes_allowed\nT1,1\nT2,\n", encoding="utf-8")
    (src / "SRC_x2__Guide.md").write_text("# Guide\n\nCount records.\n", encoding="utf-8")
    with open(tmp_path / "SourceManifest.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Source_ID", "File", "Publisher", "Derivation"])
        w.writerow(["SRC_x1", "sources/SRC_x1__trips.txt", "Transit agency", "orig"])
        w.writerow(["SRC_x2", "sources/SRC_x2__Guide.md", "Challenge organisers", "notes"])
    with open(tmp_path / "Test.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["ID", "Case_ID", "Domain", "Question", "Context", "Source_IDs"])
        w.writerow(["q1", "c", "transport", "Is a bicycle allowed?", "", json.dumps(["SRC_x1", "SRC_x2"])])
    out = tmp_path / "schemas.txt"
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    r = subprocess.run([sys.executable, os.path.join(root, "scripts", "dump_schemas.py"), "--out", str(out)],
                       env={**os.environ, "GENAI_DATA": str(tmp_path)}, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    txt = out.read_text(encoding="utf-8")
    assert "FAMILIA transport | Transit agency" in txt and "bikes_allowed [str] nulos=1" in txt and "Count records." in txt
