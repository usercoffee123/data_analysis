# Manufacturing analysis prototype

A local LangGraph workflow for exploring manufacturing measurements and preparing evidence for an engineer. SECOM is the included historical semiconductor benchmark. The tool screens records and generates reports; it does not predict failures or determine equipment health.

## Setup

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

For optional LLM commentary, serve Ollama at `http://localhost:11434` with `qwen3.5:9b` installed. Commentary uses one aggregate model call. Per-sample flags, briefs, and evaluation metrics are calculated by Python.

## Process the included dataset

The repository includes `secom.thresholds.json` with fixed feature bounds and review cutoffs. Runs load this file and screen every input record against its values:

```sh
.venv/bin/python secom_graph.py data/secom/secom.data data/secom/secom_labels.data \
  --sha256 20f0e7ee434f7dcbae0eea9ffff009a2b57f42d6b0dc9a5bd4f00782c0a3374c \
  --labels-sha256 126884cf453705c9e61a903fe906f0665a3b45ce3639e621edc5c93c89627e03 \
  --manifest reports/secom.manifest.json
```

The default threshold file is resolved beside `secom_graph.py`, regardless of the working directory. Use `--thresholds path/to/thresholds.json` to select another artifact. The artifact and feature layout are validated before screening. A missing or invalid threshold file fails the run; thresholds are never regenerated automatically. Reports record the artifact path, SHA-256 digest, and applied thresholds.

Add `--no-llm` for deterministic screening without Ollama. Add `--manifest reports/run.manifest.json` to change output destinations.

Three files are written:

- `secom.manifest.summary.md`: short summary, recommendations, model commentary status, and measured screening results.
- `secom.manifest.md`: full report including flagged sample briefs.
- `secom.manifest.json`: complete evidence, settings, all-sample index and feature statistics.

On report-generating runs, input verification or parsing errors produce failure reports. An LLM outage retains deterministic results with `model_analysis.status: failure`; `--no-llm` records `skipped`. Overall success means processing completed, not that records passed testing.

## Maintain the threshold file

The tool only reads thresholds; it contains no threshold-fitting or threshold-generation path. To change a bound, feature eligibility, or review cutoff, edit `secom.thresholds.json`, review the change, and check the file into Git. The `settings`, `fit`, and source metadata document how the included values were originally obtained; they do not instruct the tool to calculate new values.

## Screening and interpretation

The included bounds were originally derived from the earliest 60% of chronological records, with review cutoffs calibrated on the next 20%. The final 20% were excluded from that calculation, as were pass/fail labels. This history is recorded in the threshold file. Runs screen the whole input batch under the `saved_thresholds` cohort and report descriptive results. A sample's anomaly score is the fraction of observed eligible features outside the saved bounds. Missing-data screening considers eligible features only. Eligibility and cutoffs come directly from the threshold file.

Known failed tests enter the review queue separately. Evaluation excludes these known-failure flags so labels do not artificially guarantee recall. Statistical flags mean unusual measurements, not confirmed defects. An unflagged record is not declared healthy.

The included thresholds produce 204 queued records out of 1,567: 104 known failed tests and 100 passing records selected for investigation. An earlier held-out evaluation found that independent screening caught **0 of 17 failures**. Reapplying those thresholds to the source dataset produces descriptive screening results, not a new independent validation. This is a prototype for review assistance, not a validated failure detector. Treat model commentary as unverified; use the measured evaluation table for counts and recall.

## Code and tests

- `secom_graph.py`: parsing, profiling, screening, evaluation, graph orchestration and CLI.
- `secom.thresholds.json`: fixed feature bounds, eligibility, review cutoffs, and historical provenance.
- `secom_thresholds.py`: threshold loading, validation, and record scoring.
- `secom_reporting.py`: full and summary Markdown reports.
- `sensor_graph.py`: the original JSON-reading workflow and local Ollama integration.

```sh
.venv/bin/python -m unittest -v
```

The original demo is still available with `.venv/bin/python sensor_graph.py`. SECOM attribution and file descriptions are in `data/secom/README.md`. The facility integration roadmap is in `PLAN.md`.

## Extending to facility data

Start by defining a record schema with production entity IDs, equipment and recipe IDs, timestamps, feature names, units and quality flags. Obtain approved limits or independently validated references for comparable process populations, and maintain them in a versioned threshold file. Matching feature counts alone cannot establish that a facility batch uses the same units or process population; that mapping needs to be established before reuse. Validate on later records with known incidents before connecting a prioritized review queue to an operator workflow. The tool is not a live monitoring service.
