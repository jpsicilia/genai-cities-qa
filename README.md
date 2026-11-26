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

## Model

One generative model: **Qwen3-1.7B** as the Ollama tag `qwen3:1.7b` (architecture qwen3, quantization Q4_K_M,
Apache-2.0 licence). Parameter count: `ollama show` reports **2.0B** in total; the Qwen model card lists 1.7B
(1.4B non-embedding). Both are under the challenge's 3B cap; the challenge asks for the total, so 2.0B is the
figure to quote. Settings set by the code (they override Ollama's defaults of temperature 0.6, top_p 0.95):
`think=False`, temperature 0, `num_ctx` 8192. No fine-tuning. BM25 retrieval over the organiser guides is non-generative and written in plain Python.

## Results (25 Nov 2026)

| What | Result |
|---|---|
| Zindi public leaderboard | **0.1098**, rank 127 (212 active teams; the top teams scored about 0.97) |
| Questions answered | 438 / 600: 68 with hand-written profiles (Dublin, Zürich), 370 with the automatic profile |
| Not answered | 162: 100 from families with no tabular source, 62 from formats not read (GTFS zip, LAZ/GeoTIFF, SQLite graph) |
| Dublin holdout (own questions, not Test) | plan 15/20, numbers in text 14/19, Yes/No verdicts 10/10, invented numbers 0 |

The public score only covers part of the test set until the competition closes.

What the score taught:

* **Source-specific tools are what scores.** The hand-written profiles (Dublin, Zürich) answer well. The
  automatic profile reads almost any table, but a 1.7B model cannot plan the multi-step questions of the Test
  (joins between files, service calendars, formulas, comparisons of two geometries), so most of its answers miss
  the numbers and score only on the Yes/No part. The leaderboard top (~0.97) points to dedicated solvers per
  dataset family, with the model only choosing among them.
* **A development set must look like the Test.** Our own 18 simple questions on the automatic profile reached
  18/18; the real Test questions were far harder. Simple questions measured the plumbing, not the task.
* **Deterministic numbers hold up.** The model never computes: Python computes, writes and cites, and a number
  guard rejects any number that does not come from a tool. No evaluation found an invented number.

## Limitations

* **Formats not read.** GTFS feeds inside zip files, LiDAR point clouds (LAZ) and rasters (GeoTIFF), and the
  SQLite road graph are not loaded, so their 62 Test questions get the fallback answer. PDF and HTML documents are
  used only through the guide index, not as data.
* **Multi-step questions.** The automatic profile gives the model generic tools (count, sum, mean, value,
  extreme, group counts). Questions that need joins between files, service calendars, times past midnight,
  geometry comparisons or chained formulas are beyond what a 1.7B planner composes from those tools; they need
  dedicated solvers.
* **Hand-written profiles are dataset-specific.** `profiles/dublin.yaml` and `profiles/zurich.yaml` help only when
  the same datasets come back; new datasets go through the automatic profile.
* **Holdout gold is private.** `scripts/eval_holdout.py` needs `scripts/gold_dublin.py`, which is kept out of the
  repository so the holdout stays a clean measurement. The other evaluation scripts run on public inputs.
* **Small evaluation sets.** 20 holdout and 18 automatic-profile questions; with a 1.7B model a prompt change
  moves ±2 cases, so changes were judged by the cause of each failure, not by totals.

## Regenerate the submission

```bash
python -u scripts/make_submission.py --out runs/submission.md
python scripts/validate_submission.py runs/submission.md
```

`make_submission.py` caches finished questions in `runs/cache.jsonl` and can be resumed after an interruption.
When the file is assembled, sentences that answer nothing are removed ("No … row … was found.", value lists ending in "(+N more)") together with the evidence that only supported them; then the longest answers are trimmed step by step (fewer evidence lines, shorter locators and claims, sentences without numbers or verdicts) until the file fits in 240 KiB. Numbers and Yes/No verdicts are never removed by trimming.

## Automatic profile (families without a hand-written profile)

`tools/autoload.py` reads any tabular source: delimited text (delimiter, encoding, BOM and decimal comma detected),
spreadsheets (header row detected; `_row` keeps the real Excel row so answers cite cells such as `E31`), JSON
(record lists, CKAN results, GeoJSON properties; nested lists of objects become child tables keyed by the parent
ID; lists of objects inside metadata become small tables) and GeoPackage/GML/GeoJSON attributes. Numbers are
converted only when a whole column is numeric; codes with leading zeros stay text. Nothing is filled or repaired.

`tools/autoprofile.py` builds a profile from a question's `Source_IDs`: one table per distinct dataset (the same
data supplied as GML, GeoJSON and GPKG counts once), a `combined` table when sibling layers share their columns
and have disjoint keys, lazy loading of large CSVs, and per-question focus on the most relevant tables. Each
table is described by its original file and format ("from data.csv (CSV file)", "Excel workbook"), so questions
that say "in the CSV" or "in the workbook" reach the right table. The
planner also receives the guide sentences most related to the question. New tools: `value` (a field in the
row(s) chosen by filters, with its cell reference), `sum`, `extreme` with `which=min`. Differences, percentage
changes and ratios between planned numbers are computed by Python (`pipeline/derived.py`), never by the model.
Deterministic plan repairs for automatic profiles only (`executor.auto_repair`): "which … has the most records"
becomes `group_count` on the column the question names (also abbreviated: hour → `hr`); calls with invented
filter values (`'max_value'` on a numeric column) are dropped; a percent whose denominator excludes its numerator
is dropped; a second label named in the question (2021 *and* 2023) gets its own call; "total" over several rows is
a sum; the mean of a single row is read as that cell. Hand-written profiles keep the v8 prompt and schema exactly.
`make_submission.py` runs the questions family by family (Test.csv is shuffled), so each automatic profile is
built once; the output file keeps the SampleSubmission order.

```bash
python -u scripts/make_submission.py --auto --dry-run        # coverage
python -u scripts/eval_auto.py --fake                        # reference plans: table names and tools exist
python -u scripts/eval_auto.py                               # model plans vs reference plans (own questions)
```

## Inspect sources of families without a profile

```bash
python -u scripts/dump_schemas.py --out runs/schemas.txt    # read-only; --all includes covered families
```

Prints, per family of Test questions, a compact schema of every source (columns, types, nulls, examples;
spreadsheet cells with coordinates; raster, point-cloud, XML, IFC and SQLite summaries). Optional packages give
more detail: `openpyxl`, `odfpy`, `pypdf`, `rasterio`, `laspy[lazrs]`.

## Repository layout

```
pipeline/   one question end to end: planner (LLM, JSON schema), executor and plan repairs, derived values,
            Yes/No verdicts, answer templates, number guard, evidence, submission assembly and validation
tools/      deterministic tools (tabular, spatial), generic reader and automatic profile, BM25 over guides
profiles/   hand-written profiles for the Dublin and Zürich tree inventories
scripts/    make_submission, validate_submission, evaluations (holdout, automatic profile, Zürich),
            dump_schemas and exploration helpers
tests/      152 tests on small synthetic replicas of the real formats (invented values)
```

Not in the repository: `data/` (challenge sources, each under its own licence), `runs/` (generated answers)
and the private holdout gold.

## Tests

```bash
python -m pytest tests -q
```

## Licence

Apache License 2.0 (see `LICENSE`). Data are not included; each source keeps its own licence
(see `SourceManifest.csv`).
