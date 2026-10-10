# What this tool does

This tool processes historical semiconductor manufacturing measurements and creates a review queue for an engineer. It identifies records with known failed tests, unusually high concentrations of statistical outliers, or unusual measurement gaps. It explains the evidence and suggests investigation steps.

It does not operate equipment, identify physical root causes, or provide a validated failure prediction.

## Input

The included UCI SECOM dataset contains:

- **1,567 samples**, each representing a manufactured production entity.
- **590 anonymous features** per sample.
- A separate historical test label: **-1 means pass; 1 means fail**.
- A test timestamp for each sample.
- Missing measurements represented by `NaN`.

The two input files are `data/secom/secom.data` and `data/secom/secom_labels.data`. The tool verifies their bytes against the expected SHA-256 digests supplied on the command line before processing them. It rejects malformed measurements, inconsistent row widths, invalid labels or timestamps, and mismatched row counts.

Feature names, physical units, equipment mappings, recipes, and approved operating limits are unavailable. The tool therefore uses statistical comparisons rather than equipment-specific rules.

## Processing workflow

```text
Verify input files
       ↓
Parse measurements and matching labels
       ↓
Summarize dataset and data quality
       ↓
Load the saved threshold file
       ↓
Screen every sample using those thresholds
       ↓
Optionally request an overall interpretation from Ollama
       ↓
Create sample briefs and save JSON and Markdown reports
```

LangGraph coordinates the `parse`, `profile`, `screen`, `analyze`, and `decide` nodes. File verification and report writing surround the graph execution.

Normal runs process every sample using the checked-in `secom.thresholds.json` beside `secom_graph.py`. This default path works regardless of the working directory. `--thresholds path/to/thresholds.json` selects a different artifact. The tool validates the artifact and screens the entire input dataset without recalculating bounds or review cutoffs. A missing or invalid artifact fails the run; there is no automatic fitting fallback.

The tool contains no threshold-fitting or threshold-generation logic. Threshold changes are made by editing the JSON file and reviewing and checking those changes into Git. The file's historical settings and provenance explain the included values; they do not change the runtime screening rules.

## Where the checked-in bounds came from

The checked-in values were originally obtained from the source dataset, sorted by test timestamp and divided into three groups:

| Group | Records | Purpose |
| --- | ---: | --- |
| Earliest 60% | 940 | Originally used to obtain per-feature bounds |
| Next 20% | 313 | Originally used to obtain sample review cutoffs |
| Final 20% | 314 | Excluded from the original threshold calculation |

Pass/fail labels were excluded from this original calculation.

The saved artifact contains the eligible feature bounds, sample anomaly and missing-data thresholds, historical settings, and source provenance. All 1,567 rows are compared with those same fixed thresholds, including the rows originally used to obtain them. The input feature layout must match the artifact. Each row is assigned the `saved_thresholds` cohort. This full-batch report is descriptive; it does not claim that all rows are held-out validation data.

The original calculation selected features with at least 20 observed baseline values, at least 80% measurement coverage, and a positive interquartile range. The file marks 408 features as eligible. Runtime screening reads that eligibility directly.

The original feature-bound calculation used:

1. Calculate Q1, the 25th percentile, and Q3, the 75th percentile, using inclusive quartiles.
2. Calculate `IQR = Q3 - Q1`.
3. Set the lower bound to `Q1 - 3 × IQR`.
4. Set the upper bound to `Q3 + 3 × IQR`.

An observed value strictly outside the stored bounds is statistically unusual. A value equal to a bound is not unusual. These historical statistical bounds are not approved manufacturing limits. The tool uses them for any input batch size without calculating new bounds or cutoffs.

## Which samples enter the review queue

A sample is queued when any of the following applies:

### Recorded test failure

The supplied historical label says the sample failed. This is an already known outcome, not something the tool predicted.

### High anomaly burden

The anomaly score is:

```text
Number of unusual observed eligible features
────────────────────────────────────────────
Number of observed eligible features
```

The score must exceed the cutoff stored in the artifact: approximately **2.94%** for the included thresholds. That value was originally the calibration group's 95th-percentile score. A single unusual measurement generally does not trigger a review by itself.

This percentile sets an exploratory review threshold. It does not guarantee a particular alert rate on later records or establish that a sample is defective.

### Low measurement coverage

The missing fraction among eligible features must exceed the stored cutoff, **10%** for the included thresholds. That cutoff was originally the larger of 10% and the calibration group's 95th-percentile missing fraction.

Highly incomplete features excluded from the reference do not contribute to this coverage flag. The report still lists all missing feature IDs for each queued sample.

The missing-fraction cutoff is read directly from the threshold file.

### Insufficient reference data

If no features qualify for comparison, samples are queued for review because the tool cannot perform meaningful statistical screening.

The applied feature bounds and cutoffs come from `secom.thresholds.json` and are recorded in each JSON report. Unflagged records are not declared healthy.

## What each sample brief contains

Every queued record receives a Python-generated brief with:

- Sample ID and its one-based source row in the input files.
- Timestamp and recorded pass/fail result.
- Review reasons and its `saved_thresholds` cohort.
- Anomaly score and review threshold.
- Unusual feature IDs, measured values, reference bounds, and direction of deviation.
- Missing measurement counts and feature IDs.
- A description and recommended investigation steps.

Recommendations include reviewing test logs, tracing the production entity through manufacturing records, mapping anonymous features to equipment signals, verifying measurements, checking approved limits, and investigating acquisition gaps. These recommendations are general because the dataset lacks equipment context.

## What the LLM does

The `analyze` node makes **one call to local Ollama using `qwen3.5:9b`** by default. It receives compact dataset statistics, the ten features with the most missing measurements, applied screening thresholds and counts, and evaluation results.

The model returns an overall summary, observations, and limitations under `assessment.model_analysis`.

Python reads the saved bounds, chooses flagged samples, and writes individual sample recommendations. The LLM provides aggregate commentary. Model commentary is unverified and can mix up statistics from different evaluation groups; use the deterministic evaluation table for measured results.

Add `--no-llm` to skip the call. If Ollama fails, the tool retains the deterministic results and records the commentary failure separately.

## Current results and their meaning

The checked-in thresholds queue **204 of 1,567 samples**, comprising:

- **104 known failed tests**.
- **100 passing records** selected for statistical anomalies or measurement gaps.

The earlier rule queued 1,415 records because any single unusual value could trigger a flag. The revised approach reduces review volume.

Failure detection remains a limitation. An earlier held-out evaluation on 314 records found that independent screening flagged 26 records, all of which passed, and captured **0 of the 17 recorded failures**. Known failed-test flags are excluded from evaluation metrics so supplied labels cannot artificially guarantee detection. A normal run over the source dataset reports full-batch descriptive results rather than a fresh held-out result.

This is therefore a starting point for historical investigation and reporting, not a reliable failure detector. Flags on passing records may still identify unusual measurements or data-quality issues, but they have not been validated as useful operational alerts.

## Output files

Report-generating runs write:

| File | Contents |
| --- | --- |
| `secom.manifest.summary.md` | Short summary, recommendations, model commentary, screening method, and evaluation table |
| `secom.manifest.md` | Full Markdown report with every queued sample brief |
| `secom.manifest.json` | Complete evidence, feature statistics, settings, all-sample index, queued briefs, and model output |

Use `--manifest reports/secom.manifest.json` to put all three files in `reports/`. Input verification or parsing failures produce error reports. Overall `status: success` means processing completed; it does not mean products passed or equipment is healthy.

Reports record the artifact path and SHA-256 digest alongside the applied threshold values. Keep the threshold file in Git with its source-data provenance so later batches can be traced to the reference used for screening.

## Run it

Screen the entire dataset using the checked-in thresholds and generate reports:

```sh
.venv/bin/python secom_graph.py \
  data/secom/secom.data data/secom/secom_labels.data \
  --sha256 20f0e7ee434f7dcbae0eea9ffff009a2b57f42d6b0dc9a5bd4f00782c0a3374c \
  --labels-sha256 126884cf453705c9e61a903fe906f0665a3b45ce3639e621edc5c93c89627e03 \
  --manifest reports/secom.manifest.json
```

Add `--no-llm` to generate reports without Ollama. Add `--thresholds path/to/thresholds.json` to use another saved artifact. Omitting that option uses the threshold file beside the script and never fits new thresholds. Setup instructions are in [README.md](README.md).

## What a real facility would need

To extend this into a facility pilot, add production and equipment identifiers, feature names and units, recipes, measurement quality flags, and engineer-approved limits. Maintain approved bounds and cutoffs in a versioned threshold file, compare records from comparable processes, and validate alerts against later incidents and engineer feedback.

The tool can reuse saved references for later batches with a matching feature layout. Feature names, units, recipes, and process populations must also be consistent for reuse to make sense; the anonymous SECOM layout does not establish that operational context. The tool is not a live monitoring service. A facility integration would also need a prioritized review workflow and a way to record investigation outcomes.

## Dataset source

McCann, M. & Johnston, A. (2008). SECOM [Dataset]. UCI Machine Learning Repository. https://doi.org/10.24432/C54305. License: CC BY 4.0. See [data/secom/README.md](data/secom/README.md) for provenance.
