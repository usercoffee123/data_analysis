"""Paths and expected fingerprints for the included SECOM dataset."""

from manufacturing_analysis.paths import CONFIG_DIR, DATA_DIR


DATA_PATH = DATA_DIR / "secom/secom.data"
LABELS_PATH = DATA_DIR / "secom/secom_labels.data"
DEFAULT_THRESHOLDS_PATH = CONFIG_DIR / "secom/thresholds.json"
DATA_SHA256 = "20f0e7ee434f7dcbae0eea9ffff009a2b57f42d6b0dc9a5bd4f00782c0a3374c"
LABELS_SHA256 = "126884cf453705c9e61a903fe906f0665a3b45ce3639e621edc5c93c89627e03"
