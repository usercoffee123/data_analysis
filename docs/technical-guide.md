# Technical guide

[Back to the beginner README](../README.md)

This guide explains the existing analysis rules, custom input commands, and code layout. Start with the README to run the included example. Paths in commands are relative to the project folder.

## Run the full command

These commands are for macOS/Linux. On Windows, use the README's setup steps, replace `.venv/bin/python` with `.\.venv\Scripts\python.exe`, and put the analysis command on one line without the trailing `\` characters. Run module commands from the project folder.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

.venv/bin/python -m manufacturing_analysis.secom \
  data/secom/secom.data data/secom/secom_labels.data \
  --sha256 20f0e7ee434f7dcbae0eea9ffff009a2b57f42d6b0dc9a5bd4f00782c0a3374c \
  --labels-sha256 126884cf453705c9e61a903fe906f0665a3b45ce3639e621edc5c93c89627e03 \
  --manifest reports/secom.manifest.json \
  --no-llm
```

This processes the entire included dataset and writes the reports below. Remove `--no-llm` to request one aggregate interpretation from Ollama. Ollama must be serving at `http://localhost:11434` with `qwen3.5:9b` installed.

## Dataset

The included [UCI SECOM dataset](https://archive.ics.uci.edu/dataset/179/secom) contains historical semiconductor manufacturing measurements from July–October 2008:

- **1,567 records**, each representing a production entity.
- **590 anonymous measurement features** per record, with missing values represented by `NaN`.
- Historical pass/fail test results: **-1 = pass; 1 = fail**.
- A test timestamp for each record.

`data/secom/secom.data` contains the measurements. Matching rows in `data/secom/secom_labels.data` contain outcomes and timestamps. `data/secom/secom.names` contains the original dataset documentation. The downloaded feature file has 590 columns; UCI's web description reports 591. The tool reads the actual file width.

The features have no supplied names, units, equipment mappings, recipes, or approved operating limits. This dataset is not identified as specifically coming from RAM manufacturing.

## What happens during a run

```text
Verify input files → Parse → Profile → Screen → Optional LLM summary → Reports
```

1. Verify both input files against the expected SHA-256 digests supplied on the command line.
2. Parse the measurements, labels, and timestamps; reject inconsistent row widths, invalid values, or mismatched row counts.
3. Summarize historical outcomes, missing measurements, and feature statistics.
4. Load `config/secom/thresholds.json` and check every record against its fixed bounds and review cutoffs.
5. Generate a brief for every queued record, describing the evidence and investigation steps.
6. Optionally send aggregate evidence to Ollama and include its interpretation in the report.
7. Save complete evidence as JSON, plus short and full Markdown reports.

LangGraph coordinates the `parse`, `profile`, `screen`, `analyze`, and `decide` nodes. Input verification and report writing surround the graph execution.

## Fixed thresholds and review rules

`config/secom/thresholds.json` is the checked-in source of feature eligibility, lower and upper bounds, and sample review cutoffs. The default path is resolved from the project folder, so it does not depend on the working directory. Use `--thresholds path/to/thresholds.json` to select a different file.

There is no threshold-creation or recalibration code. Runs validate and read the file without changing it. Missing or incompatible thresholds fail the run. To change thresholds, edit the JSON and review and check the changes into Git. Reports record the threshold file's path, SHA-256 digest, and applied values.

A record enters the review queue if any of these conditions applies:

| Reason | Rule |
| --- | --- |
| Recorded test failure | The supplied historical test label is `1`. This is a known outcome, not a prediction. |
| High anomaly burden | The fraction of observed eligible features outside their bounds exceeds the saved cutoff, approximately **2.94%**. |
| Low measurement coverage | The missing fraction among eligible features exceeds the saved cutoff, **10%**. |
| Insufficient reference data | No features in the threshold file are eligible for comparison. |

The file marks **408 of 590 features** as eligible. Measurements equal to a bound are not counted as unusual. Missing measurements in ineligible features do not trigger the coverage rule, but each queued brief lists all its missing feature IDs.

The bounds were originally obtained from the earliest 60% of timestamp-ordered source records, using `Q1 - 3 × IQR` and `Q3 + 3 × IQR`. Features needed at least 20 observed values, 80% baseline coverage, and a positive IQR. Review cutoffs came from the next 20%; the final 20% and pass/fail labels were excluded from that calculation. The threshold file retains this history as provenance. Runtime screening uses only the saved values.

## Sample briefs and investigation steps

Each queued brief contains a sample ID, one-based source row, timestamp, recorded outcome, flag reasons, anomaly score, unusual values and their comparison bounds, missing feature IDs, and recommendations.

Suggested steps include:

- Review the failed-test details and trace the production entity through manufacturing logs.
- Map unusual feature IDs to equipment signals and verify the measurements.
- Compare measurements with approved process limits and comparable production records.
- Investigate whether acquisition gaps or unavailable tests explain missing values.
- Have a process engineer review the evidence before drawing a conclusion.

These are general, Python-generated recommendations. Anonymous SECOM features prevent equipment-specific diagnoses.

## LLM behavior

The default run makes **one call to local Ollama using `qwen3.5:9b`**. It receives compact dataset statistics, the ten features with the most missing measurements, screening counts, thresholds, and evaluation results. Its summary, observations, and limitations are stored under `assessment.model_analysis`.

The LLM does not choose flags or create per-sample recommendations. `--no-llm` skips commentary. An Ollama failure retains the screening results and records `model_analysis.status: failure`; disabled commentary records `skipped`.

Model commentary is unverified. Use the calculated evaluation table for measured counts and recall.

## Reports

With `--manifest reports/secom.manifest.json`, the run writes:

| File | Contents |
| --- | --- |
| `reports/secom.manifest.summary.md` | Short summary, recommendations, model commentary, screening method, and evaluation table |
| `reports/secom.manifest.md` | Full report with every queued sample brief |
| `reports/secom.manifest.json` | Input verification, feature statistics, fixed settings, all-record index, briefs, and model output |

Without `--manifest`, the same filenames are written in the project `reports/` folder. Generated reports are excluded from Git. Input or threshold failures produce error reports. Overall `status: success` means processing completed, not that products passed testing or equipment is healthy.

The README and this guide are project documentation; generated Markdown files are analysis outputs.

## Current results and limits

The fixed thresholds queue **204 of 1,567 records**: **104 known failed tests** and **100 passing records** selected for investigation.

Evaluation excludes known-failure flags when measuring independent screening. Whole-dataset results are descriptive and include records originally used to obtain thresholds; they are not new held-out validation. An earlier held-out evaluation captured **0 of 17 recorded failures**. The current method has not demonstrated reliable failure detection.

Statistical flags identify unusual measurements, not confirmed defects. Unflagged records are not declared healthy. The tool does not diagnose physical causes, predict future failures, or operate equipment.

## Original sensor demo

A smaller JSON-reading workflow remains available:

```sh
.venv/bin/python -m manufacturing_analysis.sensors
```

It requires Ollama, reads the included `data/sensors/example.json`, and writes `reports/sensors/sensor-sample.manifest.json`. Custom input files still require an expected digest. For a custom file:

```sh
.venv/bin/python -m manufacturing_analysis.sensors readings.json --sha256 <expected-digest>
```

Example input:

```json
{
  "readings": [
    {
      "sensor_id": "pump-07-vibration",
      "value": 12.4,
      "unit": "mm/s",
      "warning_max": 7.1,
      "critical_max": 11.0
    }
  ]
}
```

This workflow checks the supplied bounds and requests a model interpretation. The output includes `description`, `recommendations`, `findings`, and `model_analysis`. Unconfigured readings require review. Example thresholds are illustrative; use engineer-approved limits for real equipment.

## Code and validation

| File | Responsibility |
| --- | --- |
| `run_example.py` | Small entry point that calls the packaged example |
| `manufacturing_analysis/secom/example.py` | Included-dataset launcher and readable terminal output |
| `manufacturing_analysis/secom/dataset.py` | SECOM input paths, expected digests, and default configuration path |
| `manufacturing_analysis/secom/cli.py` | Command-line arguments for custom SECOM inputs |
| `manufacturing_analysis/secom/workflow.py` | Graph nodes, optional model commentary, and file processing |
| `manufacturing_analysis/secom/data.py` | Paired-file parsing and descriptive feature statistics |
| `manufacturing_analysis/secom/screening.py` | Review rules, investigation steps, sample briefs, and evaluation |
| `manufacturing_analysis/secom/thresholds.py` | Fixed-threshold loading, validation, and record scoring |
| `config/secom/thresholds.json` | Versioned bounds, eligibility, review cutoffs, and provenance |
| `manufacturing_analysis/secom/reporting.py` | Short and full Markdown reports |
| `manufacturing_analysis/common/ollama.py` | Model settings, prompt, HTTP request, and response validation |
| `manufacturing_analysis/common/io.py` | Input digests and atomic JSON/text output |
| `manufacturing_analysis/sensors/workflow.py` | Reusable JSON sensor workflow |
| `manufacturing_analysis/sensors/cli.py` | Sensor demo and custom-input command |
| `manufacturing_analysis/paths.py` | Repository data, configuration, and report locations |
| `tests/fixtures/` | Static thresholds used by tests |

Run the tests:

```sh
.venv/bin/python -m unittest -v
```

To modify behavior, start with these functions:

| Change | Location |
| --- | --- |
| Dataset format or feature statistics | `parse_measurements`, `parse_labels`, and `feature_statistics` in `manufacturing_analysis/secom/data.py` |
| Which records enter the queue | `flag_reasons` in `manufacturing_analysis/secom/screening.py` |
| Per-record recommendations | `investigation_steps` in `manufacturing_analysis/secom/screening.py` |
| Numeric bounds and review cutoffs | `config/secom/thresholds.json` |
| LLM model or instructions | Constants in `manufacturing_analysis/common/ollama.py` |
| Summary or full report layout | Section renderers in `manufacturing_analysis/secom/reporting.py` |
| Processing steps | Node list in `build_secom_graph` in `manufacturing_analysis/secom/workflow.py` |

Scoring and unusual-value evidence share one `inspect_row` function, so a change to feature comparisons applies consistently to both. Report renderers operate on completed results and do not call the model. The CLI and Python API use the same input and output-path checks.

## Package boundaries

- `manufacturing_analysis/common/` provides file I/O and the Ollama client. It does not import either analysis workflow.
- `manufacturing_analysis/secom/` owns the paired-file format, historical labels, feature statistics, screening rules, evaluation, and SECOM reports.
- `manufacturing_analysis/sensors/` owns JSON sensor validation and sensor-specific decisions. It does not import SECOM code.
- Each workflow's `cli.py` handles terminal arguments; `workflow.py` provides reusable processing functions. `__main__.py` enables the `python -m` commands.
- `manufacturing_analysis/paths.py` resolves repository resources from its own location. Default data and configuration paths work independently of the terminal's current folder.
- `config/` contains versioned rules, `data/` contains input files, and `reports/` contains generated output. Original SECOM threshold provenance is retained when moving the configuration file.
- Tests mirror the package folders. Run all checks with `.venv/bin/python -m unittest -v`, or just SECOM checks with `.venv/bin/python -m unittest discover -s tests/secom -v`.

To use the processing functions in another script, import them from the package:

```python
from manufacturing_analysis.secom.workflow import process_secom
from manufacturing_analysis.sensors.workflow import run_assessment
```

The former top-level source modules have moved into the package. Update older imports and use the module commands shown above. The beginner command `.venv/bin/python run_example.py` is unchanged.

## Extending to a facility

Define production and equipment IDs, timestamps, process steps, recipes, feature names, units, and measurement-quality flags. Obtain approved limits or independently validated comparisons for the relevant process population, and maintain them in the versioned threshold file.

Matching column counts alone does not establish compatible units or operating conditions. Validate alerts on later incidents and engineer feedback before connecting an operator review queue. A facility integration would also need ingestion, authentication, monitoring, acknowledgements, and recorded investigation outcomes. This prototype processes file batches rather than a live sensor stream.

## Dataset attribution

McCann, M. & Johnston, A. (2008). *SECOM* [Dataset]. UCI Machine Learning Repository. [DOI: 10.24432/C54305](https://doi.org/10.24432/C54305). License: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

The included files were downloaded from the [UCI SECOM archive](https://archive.ics.uci.edu/static/public/179/secom.zip). Original documentation is retained in `data/secom/secom.names`.
