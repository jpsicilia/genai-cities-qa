"""Valida un archivo de entrega antes de subirlo a Zindi.
Uso: python scripts/validate_submission.py runs/submission.md [--max-bytes 262144]
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

from pipeline import submission as SUB  # noqa: E402
from tools import loaders  # noqa: E402


def expected_ids():
    sample = os.path.join(loaders.DATA, "SampleSubmission.md")
    if os.path.exists(sample):
        with open(sample, encoding="utf-8") as fh:
            return re.findall(r"^## (\S+)\s*$", fh.read(), re.M)
    return list(pd.read_csv(os.path.join(loaders.DATA, "Test.csv"))["ID"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--max-bytes", type=int, default=SUB.HARD_MAX)
    a = ap.parse_args()
    with open(a.path, "rb") as fh:
        raw = fh.read()
    errs, stats = SUB.validate(raw, expected_ids(), a.max_bytes)
    print(f"{stats.get('sections', '?')} secciones | {stats['bytes']:,} bytes ({stats['bytes'] / 1024:.0f} KiB)")
    if errs:
        print(f"{len(errs)} problemas:")
        for e in errs[:30]:
            print("  -", e)
        sys.exit(1)
    print("OK ✅ listo para subir")
