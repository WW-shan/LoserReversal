"""Project-wide constants: paths, thresholds, category whitelists."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = REPO_ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
SEED_EVENTS_CSV = DATA_DIR / "seed" / "unlocks_curated.csv"
REPORTS_DIR = REPO_ROOT / "reports"

WINDOWS = {
    "pre": (-7, 0),
    "day": (0, 1),
    "post": (0, 3),
}

# Pass/Fail thresholds from spec § Pass/Fail Decision Matrix
PASS_FAIL_THRESHOLDS = {
    "pct_pre_negative_pass": 0.65,
    "pct_post_negative_pass": 0.55,
    "mean_pre_pass": -0.03,
    "p_value_pass": 0.05,
    "team_subset_must_match_overall": True,
}

ECOSYSTEM_CATEGORIES = frozenset({"ecosystem", "ecosystem development", "community"})
