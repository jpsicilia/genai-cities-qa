"""Genera la entrega completa desde Test.csv.

- Orden del archivo: el de data/SampleSubmission.md (si existe) o el de Test.csv. Orden de corrida: por familia
  (mismas fuentes seguidas), para armar cada perfil automático una sola vez.
- Cada pregunta: se elige el perfil por sus Source_IDs. Con perfil -> pipeline completo.
  Sin perfil (familias que todavía no soportamos) -> respuesta corta de respaldo.
- Caché en runs/cache.jsonl: se puede cortar con Ctrl+C y reanudar sin repetir preguntas.
- Registro por pregunta (llamadas al modelo, tokens generados, herramientas, segundos) en runs/calls.jsonl,
  como pidió el staff ("log which calls each question uses").
- Pasada de tamaño: comprime las respuestas más largas hasta quedar bajo --max-bytes (240 KiB).
- Valida el formato al final.

Uso:
  python -u scripts/make_submission.py --dry-run                 # cuántas preguntas cubre cada perfil, sin correr nada
  python -u scripts/make_submission.py --limit 5                 # prueba corta
  python -u scripts/make_submission.py                           # todo lo soportado (reanuda desde la caché)
  python -u scripts/make_submission.py --domain urban_greenery --pause 3   # pausa de 3 s entre preguntas (calor)
  python -u scripts/make_submission.py --no-run                  # solo re-armar el .md desde la caché
  python -u scripts/make_submission.py --ids <ID> --refresh      # rehacer preguntas puntuales
  python -u scripts/make_submission.py --auto --dry-run          # cobertura con el perfil automático
  python -u scripts/make_submission.py --auto --domain transport --limit 10   # probar familias sin perfil
"""
import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from functools import lru_cache

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

from pipeline import answer as A  # noqa: E402
from pipeline import submission as SUB  # noqa: E402
from tools import loaders  # noqa: E402
from tools.autoprofile import AutoProfile, has_tables  # noqa: E402
from tools.profiles import profile_for  # noqa: E402


def sample_order():
    path = os.path.join(loaders.DATA, "SampleSubmission.md")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return re.findall(r"^## (\S+)\s*$", fh.read(), re.M)


def by_family(qids, sids):
    """Orden de corrida: las preguntas de una misma familia (mismas fuentes) seguidas, cada familia donde aparece
    por primera vez y, dentro de ella, el orden original. El Test viene barajado (63 conjuntos de fuentes en
    589 tramos); así el perfil automático se arma una vez por familia y no una vez por pregunta.
    El archivo final se arma igual en el orden de SampleSubmission."""
    first = {}
    for i, q in enumerate(qids):
        first.setdefault(tuple(sorted(sids[q])), i)
    return sorted(qids, key=lambda q: first[tuple(sorted(sids[q]))])


def load_cache(path):
    cache = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            for ln in fh:
                if ln.strip():
                    d = json.loads(ln)
                    cache[d["id"]] = d
    return cache


class _Auto:
    name = "auto"


AUTO = _Auto()


@lru_cache(maxsize=2)
def auto_profile(sids):
    """Un perfil automático por familia; las preguntas de la misma familia lo reutilizan."""
    return AutoProfile(list(sids))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="runs/submission.md")
    ap.add_argument("--cache", default="runs/cache.jsonl")
    ap.add_argument("--log", default="runs/calls.jsonl")
    ap.add_argument("--domain")
    ap.add_argument("--ids", nargs="*")
    ap.add_argument("--limit", type=int, help="máximo de preguntas NUEVAS a correr en esta sesión")
    ap.add_argument("--refresh", action="store_true", help="rehacer las seleccionadas aunque estén en la caché")
    ap.add_argument("--no-run", action="store_true", help="no correr el modelo; solo armar desde la caché")
    ap.add_argument("--dry-run", action="store_true", help="solo mostrar la cobertura por perfil")
    ap.add_argument("--pause", type=float, default=0.0, help="segundos de pausa entre preguntas")
    ap.add_argument("--max-bytes", type=int, default=SUB.TARGET)
    ap.add_argument("--auto", action="store_true",
                    help="perfil automático para las preguntas sin perfil escrito a mano (fuentes tabulares)")
    args = ap.parse_args()

    test = pd.read_csv(os.path.join(loaders.DATA, "Test.csv")).set_index("ID")
    order = sample_order() or list(test.index)
    sids = {q: json.loads(test.at[q, "Source_IDs"]) for q in order}
    prof = {q: profile_for(sids[q]) for q in order}
    if args.auto:
        for q in order:
            if prof[q] is None and has_tables(sids[q]):
                prof[q] = AUTO                                     # se construye al llegar a la pregunta

    cov = Counter((p.name if p else "(sin perfil)") for p in prof.values())
    print("cobertura por perfil:", dict(cov))
    if args.dry_run:
        return

    os.makedirs(os.path.dirname(args.cache) or ".", exist_ok=True)
    cache = load_cache(args.cache)
    selected = [q for q in order if prof[q] is not None
                and (not args.domain or test.at[q, "Domain"] == args.domain)
                and (not args.ids or q in args.ids)]
    todo = by_family([q for q in selected if args.refresh or q not in cache or not cache[q].get("answered")], sids)
    if args.limit is not None:
        todo = todo[: args.limit]
    if args.no_run:
        todo = []
    print(f"seleccionadas {len(selected)} | en caché {sum(q in cache for q in selected)} | a correr ahora {len(todo)}")

    t_start, errors_in_row = time.time(), 0
    try:
        with open(args.cache, "a", encoding="utf-8") as cf:
            for k, q in enumerate(todo, 1):
                p, t0 = prof[q], time.time()
                rec = {"id": q, "domain": test.at[q, "Domain"], "profile": p.name}
                try:
                    if p is AUTO:
                        p = auto_profile(tuple(sorted(sids[q])))
                    _, info = A.answer(q, test.at[q, "Question"], p, source_ids=sids[q])
                    rec.update(answered=True, text=info["text"], evidence=info["evidence"], calls=info["calls"],
                               tokens=info["tokens"], tools=info["tools"], seconds=info["seconds"])
                    errors_in_row = 0
                except Exception as ex:  # noqa: BLE001 - una pregunta mala no tumba la corrida
                    # solo los fallos de conexión con Ollama cuentan para cortar; un archivo raro no
                    errors_in_row = errors_in_row + 1 if re.search(r"connect|refused|ollama", repr(ex), re.I) else 0
                    rec.update(answered=False, error=repr(ex)[:300], seconds=round(time.time() - t0, 1))
                    if errors_in_row >= 3:
                        print("\n3 errores seguidos: ¿está corriendo Ollama? Corto aquí. Último error:", rec["error"])
                        cf.write(json.dumps(rec, ensure_ascii=False) + "\n")
                        cache[q] = rec
                        break
                cf.write(json.dumps(rec, ensure_ascii=False) + "\n")
                cf.flush()
                cache[q] = rec
                el = time.time() - t_start
                eta = el / k * (len(todo) - k)
                print(f"[{k}/{len(todo)}] {q[:8]} {p.name:<7} {'ok ' if rec['answered'] else 'ERR'} "
                      f"{rec.get('seconds', 0):>5}s calls={rec.get('calls', '-')} tokens={rec.get('tokens', '-')} "
                      f"| faltan ~{eta / 60:.0f} min")
                if args.pause:
                    time.sleep(args.pause)
    except KeyboardInterrupt:
        print("\nCortado con Ctrl+C: lo hecho quedó en la caché. Armo el archivo con lo que hay.")

    entries = []
    for q in order:
        c = cache.get(q)
        if c and c.get("answered"):
            entries.append({"id": q, "text": c["text"], "evidence": list(c["evidence"]), "answered": True})
        else:
            entries.append(SUB.fallback(q, sids[q]))
    total, steps = SUB.shrink(entries, args.max_bytes)
    doc = SUB.assemble(entries)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(doc)

    with open(args.log, "w", encoding="utf-8") as lf:
        for q in order:
            c = cache.get(q, {})
            lf.write(json.dumps({"id": q, "profile": c.get("profile"), "answered": bool(c.get("answered")),
                                 "model_calls": c.get("calls", 0), "generated_tokens": c.get("tokens", 0),
                                 "tools": c.get("tools", []), "seconds": c.get("seconds")}, ensure_ascii=False) + "\n")

    raw = doc.encode("utf-8")
    errs, stats = SUB.validate(raw, order)
    ans = [e for e in entries if e["answered"]]
    avg = sum(len(SUB.render(e).encode()) for e in ans) / len(ans) if ans else 0
    print(f"\nrespondidas {len(ans)}/{len(order)} | respaldo {len(order) - len(ans)} | "
          f"{stats['bytes']:,} bytes ({stats['bytes'] / 1024:.0f} KiB) | promedio por respuesta {avg:.0f} bytes"
          + (f" | compresión: {steps} pasos" if steps else ""))
    print("validación:", "OK ✅" if not errs else f"{len(errs)} problemas ❌")
    for e in errs[:20]:
        print("  -", e)
    print("archivo:", args.out, "| registro:", args.log)


if __name__ == "__main__":
    main()
