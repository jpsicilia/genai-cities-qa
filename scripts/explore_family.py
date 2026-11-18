"""Explora una familia (Domain) del Test: fuentes, esquemas y preguntas.
Uso: python scripts/explore_family.py urban_greenery > salida.txt
"""
import sys, json, os, zipfile
import pandas as pd

DOMAIN = sys.argv[1] if len(sys.argv) > 1 else "urban_greenery"
DATA = os.path.expanduser("~/proyectos/genai-cities-qa/data")
pd.set_option("display.width", 200)

test = pd.read_csv(f"{DATA}/Test.csv")
man = pd.read_csv(f"{DATA}/SourceManifest.csv").set_index("Source_ID")
sub = test[test["Domain"] == DOMAIN]
ids = sorted({s for x in sub["Source_IDs"] for s in json.loads(x)})

def to_df(obj):
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        return pd.json_normalize(obj)
    if isinstance(obj, dict):
        if obj.get("type") == "FeatureCollection":
            print("  CRS:", obj.get("crs"), "| geom:", obj["features"][0].get("geometry", {}).get("type"))
            return pd.json_normalize([f.get("properties", {}) for f in obj["features"]])
        for k in ("records", "result", "data", "features"):
            if k in obj:
                d = to_df(obj[k])
                if d is not None:
                    return d
    return None

def describe(df):
    print(f"  shape: {df.shape}")
    print(df.dtypes.to_string())
    print("\n  head(3):\n" + df.head(3).to_string()[:3000])
    for c in df.columns:
        nun = df[c].nunique(dropna=False)
        if nun <= 25:
            print(f"\n  [{c}] value_counts:\n" + df[c].value_counts(dropna=False).to_string())
        else:
            print(f"\n  [{c}] {nun} distintos, {df[c].isna().sum()} nulos")
    num = df.select_dtypes("number")
    if not num.empty:
        print("\n  describe numérico:\n" + num.describe().to_string())

print(f"=== {DOMAIN}: {len(sub)} preguntas, {sub['Case_ID'].nunique()} casos ===")
for sid in ids:
    r = man.loc[sid]
    path = os.path.join(DATA, r["File"])
    ext = path.rsplit(".", 1)[-1].lower()
    print(f"\n\n######## {sid} | {r['File']} | {r['Bytes']} bytes | {r['Publisher']}")
    try:
        if ext == "csv":
            describe(pd.read_csv(path, low_memory=False))
        elif ext in ("json", "geojson"):
            obj = json.load(open(path, encoding="utf-8"))
            df = to_df(obj)
            if df is not None:
                describe(df)
            else:
                print("  (no tabular) tipo:", type(obj).__name__,
                      "| claves:", list(obj)[:30] if isinstance(obj, dict) else len(obj))
                print(json.dumps(obj, ensure_ascii=False)[:2500])
        elif ext == "md":
            print(open(path, encoding="utf-8").read())
        elif ext == "zip":
            print("  ZIP:", zipfile.ZipFile(path).namelist())
        else:
            print("  (formato no manejado) primeros bytes:", open(path, "rb").read(400))
    except Exception as e:
        print("  ERROR:", repr(e))

print(f"\n\n######## LAS {len(sub)} PREGUNTAS (por caso)")
for case, g in sub.sort_values("Case_ID").groupby("Case_ID"):
    print(f"\n=== Caso {case} ===")
    for _, q in g.iterrows():
        print(f"\n[{q['ID']}] {q['Source_IDs']}\nQ: {q['Question']}")
        ctx = q.get("Context")
        if isinstance(ctx, str) and ctx.strip():
            print("Context:", ctx[:600])
