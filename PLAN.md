# Sensor Triage Prototype Plan

## Goal

Verify the exact sensor input file with SHA-256, analyze its readings with local Ollama `qwen3.5:9b`, and write an auditable manifest plus an evidence-backed triage brief for a human decision-maker. The graph must not operate equipment or treat an unconfigured sensor as healthy.

## Prototype Workflow

1. Read the input file as bytes, calculate SHA-256, and compare it with the expected digest. A missing or mismatched digest fails closed before analysis.
2. Parse a verified JSON object with a `readings` array; validate each reading and its optional warning/critical bounds.
3. Compare valid values to configured bounds and attach a status plus the rule that matched.
4. Send readings and rule findings to local Ollama for a structured interpretation, without allowing the model to override deterministic findings.
5. Package findings and model interpretation into a human-review decision brief, then write a success/failure manifest containing the digest and result.

## Run It

```sh
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python sensor_graph.py
.venv/bin/python -m unittest -v
```

Ollama must be serving at `http://localhost:11434` and have `qwen3.5:9b` installed (`ollama list`). The demo uses the workspace virtual environment at `.venv`.

The no-argument demo writes `sensor-sample.json` and `sensor-sample.manifest.json`. To process a file, pass its expected digest:

```sh
.venv/bin/python sensor_graph.py readings.json --sha256 <expected-64-character-sha256>
```

On macOS, get the expected digest with `shasum -a 256 readings.json` and pass the first field as `--sha256`.

The manifest defaults to `<input>.manifest.json`; override it with `--manifest path.json`. A manifest has `status: "success"` only when the digest matches and parsing plus model analysis complete successfully. A failed digest prevents the model call.

The manifest's `assessment` includes `description`, a plain-language account of each reading and any threshold breach, and `recommendations`, a list of next steps for human review. These fields come from the configured rules; the separate `model_analysis` adds the model's interpretation. The existing `recommended_action` remains available as a concise overall action. Invalid input produces a description of validation errors and a recommendation to correct them.

Example input shape:

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

Thresholds in examples are illustrative only. A real deployment must use limits approved for its sensor, equipment, environment, and operating procedure.

## SECOM Dataset Workflow

`secom_graph.py` verifies both raw files and parses aligned feature/label rows. Normal runs load the checked-in `secom.thresholds.json` beside the script and screen every input row without refitting. The default artifact path is independent of the working directory. Report-generating runs profile historical yield and data quality, optionally call local Ollama with aggregate evidence, and write a human-review brief. Missing values stay missing. This path does not train a failure predictor or infer physical units, operating limits, or root causes.

Apply the included thresholds to every record:

```sh
.venv/bin/python secom_graph.py data/secom/secom.data data/secom/secom_labels.data \
  --sha256 20f0e7ee434f7dcbae0eea9ffff009a2b57f42d6b0dc9a5bd4f00782c0a3374c \
  --labels-sha256 126884cf453705c9e61a903fe906f0665a3b45ce3639e621edc5c93c89627e03 \
  --manifest reports/secom.manifest.json
```

Use `--thresholds path/to/thresholds.json` to override the default artifact. The artifact must be valid and have a matching feature layout. Missing or invalid artifacts fail the run and are never regenerated automatically. Reports include the artifact path, SHA-256 digest, and applied threshold values. Full feature statistics and the brief go to the JSON manifest; terminal output omits the long feature list. Historical labels describe observed tests, not predictions. Attribution is in `data/secom/README.md`. The existing JSON sensor workflow remains available.

Thresholds are maintained in `secom.thresholds.json`. The tool contains no threshold-fitting or threshold-generation logic. To change the applied limits or feature eligibility, edit the file, review the change, and check it into Git. Historical settings and source provenance in the file explain how the included values were obtained.

### Per-sample screening

Report-generating runs save a full Markdown report beside the manifest (`secom.manifest.md`) and a short summary (`secom.manifest.summary.md`). Failed analysis runs write error reports. Changing `--manifest` changes both destinations. Markdown rendering does not make an additional LLM call. `--no-llm` skips commentary; an LLM outage retains deterministic results and reports a separate commentary failure. See README.md for the primary setup and run instructions.

The included thresholds were originally obtained with a chronological 60% baseline / 20% calibration / 20% remaining split. Per-feature bounds used Q1 - 3 IQR to Q3 + 3 IQR, selecting features with at least 20 observations, 80% baseline coverage, and positive IQR. Those bounds and eligibility are stored in the file. A sample's anomaly score is the fraction of its available eligible features outside the stored bounds. It is flagged only above the stored cutoff, originally the calibration scores' 95th percentile. This is an exploratory review cutoff, not a validated failure threshold.

Missing-data flags consider only eligible features and require a missing fraction above the stored cutoff, currently 10%. Known failed tests still enter the queue separately. No eligible reference features triggers a needs-review flag. Screening uses the threshold file regardless of input batch size.

The manifest indexes every sample and includes flagged briefs with scores, unusual values, missing features, source rows and recommendations. Markdown includes evaluation metrics excluding known-failure flags, so those labels cannot artificially guarantee detection. Runs assign every record to the `saved_thresholds` cohort and report descriptive full-batch results without a held-out claim. Replaying the source data cannot establish future failure detection. The single optional Ollama call summarizes the results. These bounds are not approved limits and unflagged records are not declared healthy.

## Build-Out Plan

1. **Define the decision contract:** Identify sensor types, units, sampling cadence, acceptable latency, consumers, and exactly which actions the decision-maker can take.
2. **Ground the rules:** Source limits from domain owners and operating procedures; define hysteresis, persistence windows, missing/stale readings, calibration, and sensor-quality checks. Version every rule set.
3. **Add ingestion:** Implement the chosen transport (file, REST, MQTT, or stream), authentication, event timestamps, schema versioning, idempotency, and a dead-letter path.
4. **Improve inference:** Add time-window features and domain-validated anomaly detection. Keep deterministic checks authoritative and evaluate the local model's structured summaries against labeled examples.
5. **Integrate decisions:** Send structured briefs to the actual operator queue or API. Require acknowledgement for urgent alerts; do not add automated control until separately safety-reviewed.
6. **Evaluate and operate:** Replay labeled historical incidents, measure false alarms and missed events, test sensor faults and boundary values, monitor latency/drift, and retain an auditable record of inputs, rule versions, outputs, and human decisions.

## Prototype Limits

- It evaluates each reading independently; it does not model trends, correlations, or time windows.
- It trusts caller-provided thresholds and does not determine whether those thresholds are correct.
- The model output is an interpretation for a human, not a diagnosis or control command.
- Production use needs domain validation, security/privacy review, observability, and operational fail-safe design.
