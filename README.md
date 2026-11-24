# genai-cities-qa

Solution for the **GenAI for Good Challenge: Cities Edition** (Phase 1 technical assessment on Zindi).
Answers city-data questions from the supplied frozen sources with **one small open generative model**
(default `qwen3:1.7b` via Ollama) plus deterministic tools.

## Design

```
question ─► profile_for(Source_IDs) ─► planner (LLM, JSON schema) ─► repair_plan (deterministic guards)
        ─► tools (tabular.py / spatial.py: pandas, GeoPandas) ─► yes/no verdicts (LLM, JSON) citing
           guide sentences retrieved with BM25 ─► answer text from deterministic templates (the LLM only
           explains "why" parts that do not follow from the data) ─► number guard ─► Evidence built by Python
```

* The model never computes numbers: it chooses tools and filters; Python computes, writes the facts and cites.
  (`GENAI_WRITER=llm` switches back to a free-text LLM writer for comparison.)
* Organiser guides are indexed (non-generative BM25) and linked to their sources through shared dataset URLs
  in `SourceManifest.csv`; verdicts cite the exact guide paragraph. The verdict query adds the filters that were
  actually applied and a few generic synonyms (empty → null/blank, remove → drop/exclude).
* Each answer also cites the guide sentence for the convention it used (`pipeline/cite.py`): the query is built
  only from the computed operations and filters (count, percentage, blank text, letter-case normalisation,
  named screening rule…), never from the question wording, and only organiser guides are cited.
* No hard-coded answers, no Test ID lookups, no training or tuning of model weights on Test material.
  Evaluation scripts build their own questions and skip any value that appears in Test questions.
* Budget per question: ≤ 15 model calls and ≤ 12,000 generated tokens (enforced in `pipeline/llm.py`).
  Model calls and tokens per question are logged in `runs/calls.jsonl`.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen3:1.7b
```

Place the challenge files in `data/` (`Test.csv`, `SampleSubmission.md`, `SourceManifest.csv`, `sources/`).

TODO before final submission: document the exact model checkpoint (`ollama show qwen3:1.7b`) and its total
parameter count, and system package versions.

## Regenerate the submission

```bash
python -u scripts/make_submission.py --out runs/submission.md
python scripts/validate_submission.py runs/submission.md
```

`make_submission.py` caches finished questions in `runs/cache.jsonl` and can be resumed after an interruption.

## Inspect sources of families without a profile

```bash
python -u scripts/dump_schemas.py --out runs/schemas.txt    # read-only; --all includes covered families
```

Prints, per family of Test questions, a compact schema of every source (columns, types, nulls, examples;
spreadsheet cells with coordinates; raster, point-cloud, XML, IFC and SQLite summaries). Optional packages give
more detail: `openpyxl`, `odfpy`, `pypdf`, `rasterio`, `laspy[lazrs]`.

## Tests

```bash
python -m pytest tests -q
```
