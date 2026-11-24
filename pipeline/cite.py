"""Cita de convenciones: la frase de la guía de la familia que respalda CÓMO se calculó la respuesta.

Reemplaza la línea genérica "analysis conventions file" por una ubicación verificable (archivo ¶n).
La consulta sale SOLO de las operaciones y filtros que de verdad se usaron. No usa la pregunta: sus
palabras arrastraban frases de reglas que no se aplicaron (p. ej. la regla Poor-and-tall en una pregunta
que solo nombra "Suitable Planting Location"). Búsqueda léxica (BM25), no generativa: no gasta presupuesto.
"""
OP_TERMS = {
    "count": "count records", "group_count": "count records", "variants": "letter case normalisation",
    "percent": "percentages decimals", "mean": "means average decimals", "distinct": "distinct keys",
    "lookup": "literal IDs", "record": "literal IDs", "areas": "areas metres planar",
    "within_radius": "radius boundary distance metres", "nearest": "distance metres",
    "z_extent": "height extents", "validity": "invalid geometries repair", "circle_area": "circular crown diameter",
    "best_combo": "costs cap", "key_audit": "identifiers", "prefix_counts": "identifiers",
}
FILTER_TERMS = {"blank": "blank text empty trim null missing", "nonblank": "blank text empty trim null missing",
                "null": "null missing", "notnull": "null missing", "eq_norm": "letter case normalisation"}
MIN_SCORE = 3.0      # la consulta solo trae palabras de convención: un puntaje bajo ya es pertinente


def terms_for(results):
    """Palabras de convención según lo que se calculó. Devuelve (específicas, generales): las de filtros,
    normalización, mapeos y filtros con nombre pesan doble; las de la operación ("count records"), simple."""
    spec, gen = [], []
    for r in results or []:
        gen.append(OP_TERMS.get(r.get("op"), ""))
        for f in r.get("filters") or []:
            spec.append(FILTER_TERMS.get(f.get("op"), ""))
        if r.get("by_spelling"):
            spec.append("letter case normalisation")
        if r.get("kind") == "band lower-edge":
            spec.append("lower-edge band")
        elif r.get("kind") == "positive-only":
            spec.append("positive zero")
        if r.get("named_label"):
            spec.append(r["named_label"])
    return " ".join(t for t in spec if t), " ".join(t for t in gen if t)


def convention(idx, results, allowed, exclude=(), min_score=MIN_SCORE):
    """Mejor frase de guía (solo guías de organizadores, no metadatos) para lo calculado, o None.

    exclude: textos ya citados (p. ej. por un veredicto) para no repetir la misma frase."""
    if not allowed or idx is None:
        return None
    spec, gen = terms_for(results)
    if not (spec or gen):
        return None
    for h in idx.search(f"{spec} {spec} {gen}", allowed, k=4, kinds={"guide"}):
        if h["score"] >= min_score and h["text"] not in exclude:
            return h
    return None
