# Manufacturing data analysis

This project reads historical semiconductor manufacturing measurements and makes a list of records for a person to investigate. It checks for recorded failed tests, unusual values, and missing measurements, then saves readable reports.

**You can run the included example without changing code or installing an AI model.** The example data and comparison rules are already included.

A record marked “needs review” needs investigation. It is not proof of a defect. This project is an experiment, and it has not demonstrated reliable failure prediction.

## Start here

1. [Set up Python](#1-set-up-python) — do this once.
2. [Run the example](#2-run-the-example).
3. [Read the results](#3-read-the-results).

For the rules, custom input files, and code details, see the [technical guide](docs/technical-guide.md).

## 1. Set up Python

You need Python 3.10 or newer and a copy of this project on your computer. The project has been tested here with Python 3.14.

Open Terminal on macOS/Linux, or PowerShell on Windows. These let you run commands by typing or pasting text and pressing Enter. Run each command block separately and wait for it to finish. Copy only the commands inside the block.

First, open the project folder in your terminal. Replace the example path below with the location where you saved this project:

```sh
cd "path/to/data_analysis"
```

You should be in the folder containing `README.md`, `requirements.txt`, and `run_example.py`.

### macOS or Linux

Check your Python version:

```sh
python3 --version
```

Create a separate place for this project's Python tools, called a virtual environment:

```sh
python3 -m venv .venv
```

Install the tools the project needs:

```sh
.venv/bin/python -m pip install -r requirements.txt
```

### Windows (PowerShell)

Check your Python version:

```powershell
py --version
```

Create the virtual environment:

```powershell
py -m venv .venv
```

Install the tools the project needs:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

The commands below use Python from that environment directly, so you do not need to activate it.

## 2. Run the example

On macOS/Linux:

```sh
.venv/bin/python run_example.py
```

On Windows:

```powershell
.\.venv\Scripts\python.exe run_example.py
```

The program checks that the included data files have not changed, reads all the records, applies the saved comparison rules, and writes reports into `reports/`.

For the included data and current rules, you should see:

```text
Done: screened 1,567 records; 204 need review.
```

The program also prints the full paths to your reports. No Ollama connection is needed for this command.

You can run it again whenever you need to. Each run replaces the reports with the same names. To keep an earlier run, choose a different folder:

```sh
.venv/bin/python run_example.py --output-dir reports/another-run
```

On Windows, use `.\.venv\Scripts\python.exe` in place of `.venv/bin/python`.

## 3. Read the results

Open the `reports` folder in your file browser or editor. Start with the summary.

| File | What it is for |
| --- | --- |
| [secom.manifest.summary.md](reports/secom.manifest.summary.md) | Start here: results, recommendations, and screening counts |
| [secom.manifest.md](reports/secom.manifest.md) | Details for every record selected for review |
| [secom.manifest.json](reports/secom.manifest.json) | Complete results for programs or further analysis |

These files are created by a run. `.md` files are readable text documents with Markdown formatting; `.json` files store structured data. You do not need to understand JSON to read the summary.

### What the results mean

The example selects **204 records**: **104 with an already recorded failed test**, plus **100 passing records** selected because of unusual or missing measurements.

| Term in the report | Plain meaning |
| --- | --- |
| Sample / record | One row of historical manufacturing data |
| Feature | One measurement column; the dataset does not supply its name or unit |
| Threshold / reference bound | A saved comparison value used to identify unusual measurements |
| Anomaly | A measurement outside its saved comparison bounds |
| Coverage | How many of the measurements used for comparison are present |
| Flag / needs review | A reason for a person to investigate the record |
| Recorded test failure | A historical failed test supplied with the data |
| Status: success | The program finished processing the files |

The comparison bounds are statistical references, not approved equipment operating limits. A successful run does not mean all products passed testing. Records without flags are not guaranteed healthy.

Known failed tests are included in the queue automatically. Their inclusion does not show that the program predicted them. The [technical guide](docs/technical-guide.md#current-results-and-limits) explains the evaluation and its limits.

## If something goes wrong

| Problem | What to do |
| --- | --- |
| `python3` or `py` is not found | Install Python 3.10 or newer, then reopen your terminal. |
| Python cannot find `run_example.py` or `requirements.txt` | Use `cd` to open the project folder first. |
| `.venv` Python is not found | Complete the virtual environment step above; use the command for your operating system. |
| `No module named 'langgraph'` | Run the dependency installation command above using the same `.venv` Python. |
| `SHA-256 verification failed` | An included data file differs from the expected original. Restore it from your original project copy. |
| A threshold file is missing or invalid | Restore `config/secom/thresholds.json` from your project copy, then try again. |
| Reports cannot be saved | Choose a writable folder with `--output-dir`. |
| The program says analysis failed | Read the printed error and the saved error report, if one was created. |

A SHA-256 digest is a file fingerprint. The example uses saved fingerprints to check the two input files; you do not need to calculate them yourself.

## Optional: add an AI explanation

The normal example already produces the screening results and recommendations. If you have local Ollama running with the `qwen3.5:9b` model installed, you can also request an AI explanation:

```sh
.venv/bin/python run_example.py --with-llm
```

Use the Windows Python command on Windows. This step may take longer. If Ollama is unavailable, the calculated screening results are still saved.

The model receives a summary of the evidence. It does not choose which records are flagged. Treat its explanation as commentary to check, rather than a verified diagnosis. See [LLM behavior](docs/technical-guide.md#llm-behavior) for details.

## Where things live

Source code is grouped by responsibility. Dataset-specific code lives in `secom/`; shared tools live in `common/`.

```text
data_analysis/
├── run_example.py              # Simple command for the included example
├── manufacturing_analysis/     # Python source code
│   ├── common/                 # File verification, report writing, Ollama
│   ├── secom/                  # SECOM parsing, screening, reports, commands
│   ├── sensors/                # Separate JSON sensor workflow and command
│   └── paths.py                # Locations of project data, rules, and reports
├── config/
│   └── secom/thresholds.json    # Saved SECOM comparison rules
├── data/
│   ├── secom/                  # Original SECOM dataset and notes
│   └── sensors/example.json    # Small sensor demo input
├── tests/
│   ├── common/                 # Shared-tool checks
│   ├── secom/                  # SECOM checks
│   ├── sensors/                # Sensor-workflow checks
│   └── fixtures/               # Small, fixed test inputs
├── reports/                    # Generated results; excluded from Git
├── docs/technical-guide.md     # Detailed rules and developer reference
└── requirements.txt            # Python tools to install
```

`run_example.py` is a small launcher. The analysis code is in the package, and the SECOM input paths and file fingerprints are in `manufacturing_analysis/secom/dataset.py`. Runs do not change the saved rules.

Earlier reports that were in the top-level folder are preserved in `reports/archive/`.

For custom SECOM inputs, use `python -m manufacturing_analysis.secom`. For the separate sensor demo, use `python -m manufacturing_analysis.sensors`. Both commands need the project's `.venv` Python prefix, just like the example. See the [technical guide](docs/technical-guide.md) for complete commands.

If you change the code, run the automated checks from the project folder:

```sh
.venv/bin/python -m unittest -v
```

On Windows, substitute the Windows Python command shown above.

## About the data

The included UCI SECOM dataset contains 1,567 records with 590 anonymous measurement columns from July–October 2008. Missing values are written as `NaN`. Historical labels use `-1` for pass and `1` for fail.

McCann, M. & Johnston, A. (2008). *SECOM* [Dataset]. UCI Machine Learning Repository. [DOI: 10.24432/C54305](https://doi.org/10.24432/C54305). License: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

Original dataset documentation is retained in `data/secom/secom.names`.
