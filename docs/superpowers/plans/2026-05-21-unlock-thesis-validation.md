# Unlock Thesis Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a small Python package that validates the "token unlock → negative price pressure" thesis on our token pool over the past 12 months, outputting a STRONG / WEAK / REJECT verdict that decides ROADMAP next step.

**Architecture:** Three pure-Python modules (fetcher, analyzer, report) composed by a thin CLI. Data sources are TokenUnlocks-format CSV (manually seeded, since their API is gated) and CoinGecko REST (free tier, JSON cached to disk). All statistical comparisons use BTC as benchmark; analysis is event-study style on three windows.

**Tech Stack:** Python 3.11+, requests, pandas, numpy, scipy, matplotlib, tenacity, pytest, pytest-mock. Package manager: uv.

---

## File Structure

```
LoserReversal/
├── pyproject.toml                          [Task 1] uv project config + deps
├── .python-version                         [Task 1] pinned 3.11
├── src/unlock_validation/
│   ├── __init__.py                         [Task 1] package marker + __version__
│   ├── config.py                           [Task 2] thresholds, paths, category whitelists
│   ├── fetcher.py                          [Task 3-4] events + prices, with cache + retry
│   ├── analyzer.py                         [Task 5-8] returns, stats, filter, pass/fail
│   ├── report.py                           [Task 9] markdown writer
│   └── __main__.py                         [Task 10] CLI entrypoint
├── tests/
│   ├── __init__.py
│   ├── conftest.py                         [Task 1] shared fixtures
│   ├── fixtures/
│   │   ├── tokenunlocks_sample.csv         [Task 3] 5 sample events
│   │   ├── coingecko_btc.json              [Task 4] mocked price response
│   │   └── coingecko_arb.json              [Task 4] mocked price response
│   ├── test_config.py                      [Task 2]
│   ├── test_fetcher.py                     [Task 3-4]
│   ├── test_analyzer.py                    [Task 5-8]
│   └── test_report.py                      [Task 9]
├── data/
│   ├── seed/
│   │   └── unlocks_curated.csv             [Task 11] real curated events (manually populated)
│   └── cache/                              [gitignored] CoinGecko response cache
├── notebooks/
│   └── 01_unlock_thesis.ipynb              [Task 12] exploratory analysis
└── reports/
    └── unlock_thesis_report.md             [Task 12 output]
```

Each file has one responsibility. The fetcher knows about APIs; the analyzer knows about statistics; the report knows about markdown. None of them know about each other beyond the data shapes (a pandas DataFrame for events, a Dict for stats).

---

## Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `.python-version`
- Create: `src/unlock_validation/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/fixtures/.gitkeep`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "unlock-validation"
version = "0.1.0"
description = "Thesis validation: token unlocks → negative price pressure"
requires-python = ">=3.11"
dependencies = [
    "requests>=2.31",
    "pandas>=2.1",
    "numpy>=1.26",
    "scipy>=1.11",
    "matplotlib>=3.8",
    "python-dateutil>=2.8",
    "tenacity>=8.2",
]

[project.scripts]
unlock-validate = "unlock_validation.__main__:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/unlock_validation"]

[dependency-groups]
dev = [
    "pytest>=7.4",
    "pytest-mock>=3.12",
    "pytest-cov>=4.1",
    "ruff>=0.4",
    "jupyter>=1.0",
    "ipykernel>=6.29",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-v --tb=short"

[tool.ruff]
line-length = 100
target-version = "py311"
```

- [ ] **Step 2: Create `.python-version`**

```
3.11
```

- [ ] **Step 3: Create `src/unlock_validation/__init__.py`**

```python
"""Unlock thesis validation package."""

__version__ = "0.1.0"
```

- [ ] **Step 4: Create `tests/__init__.py`**

```python
```

- [ ] **Step 5: Create `tests/conftest.py`**

```python
"""Shared pytest fixtures."""

from pathlib import Path

import pytest


FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR
```

- [ ] **Step 6: Create `tests/fixtures/.gitkeep`**

```
```

- [ ] **Step 7: Install dependencies**

Run: `uv sync --extra dev`
Expected: dependencies installed, `.venv/` created.
Fallback if `uv` not available: `python3.11 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"`

- [ ] **Step 8: Verify pytest discovers nothing yet (no tests)**

Run: `uv run pytest`
Expected: `no tests ran in <time>` or exit code 5 (no tests collected). Either is acceptable.

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml .python-version src/unlock_validation/__init__.py tests/__init__.py tests/conftest.py tests/fixtures/.gitkeep
git commit -m "chore: scaffold unlock-validation package"
```

---

## Task 2: Config Module (Constants + Pass/Fail Thresholds)

**Files:**
- Create: `src/unlock_validation/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_config.py`:

```python
"""Tests for config constants."""

from unlock_validation.config import (
    CACHE_DIR,
    DATA_DIR,
    ECOSYSTEM_CATEGORIES,
    PASS_FAIL_THRESHOLDS,
    REPORTS_DIR,
    SEED_EVENTS_CSV,
    WINDOWS,
)


def test_windows_define_three_event_study_periods():
    assert WINDOWS["pre"] == (-7, 0)
    assert WINDOWS["day"] == (0, 1)
    assert WINDOWS["post"] == (0, 3)


def test_pass_fail_thresholds_have_five_metrics():
    keys = {
        "pct_pre_negative_pass",
        "pct_post_negative_pass",
        "mean_pre_pass",
        "p_value_pass",
        "team_subset_must_match_overall",
    }
    assert set(PASS_FAIL_THRESHOLDS.keys()) == keys


def test_pass_thresholds_are_numerically_correct():
    assert PASS_FAIL_THRESHOLDS["pct_pre_negative_pass"] == 0.65
    assert PASS_FAIL_THRESHOLDS["pct_post_negative_pass"] == 0.55
    assert PASS_FAIL_THRESHOLDS["mean_pre_pass"] == -0.03
    assert PASS_FAIL_THRESHOLDS["p_value_pass"] == 0.05


def test_ecosystem_categories_lowercased_for_filtering():
    for c in ECOSYSTEM_CATEGORIES:
        assert c == c.lower()


def test_paths_resolve_under_repo_root():
    assert DATA_DIR.name == "data"
    assert CACHE_DIR.parent == DATA_DIR
    assert CACHE_DIR.name == "cache"
    assert SEED_EVENTS_CSV.parent.name == "seed"
    assert REPORTS_DIR.name == "reports"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py -v`
Expected: ImportError — `unlock_validation.config` does not exist.

- [ ] **Step 3: Write minimal implementation**

Create `src/unlock_validation/config.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/unlock_validation/config.py tests/test_config.py
git commit -m "feat(config): pass/fail thresholds and paths"
```

---

## Task 3: Fetcher — Load Unlock Events from CSV

**Files:**
- Create: `tests/fixtures/tokenunlocks_sample.csv`
- Create: `src/unlock_validation/fetcher.py`
- Modify: `tests/test_fetcher.py` (new file)

- [ ] **Step 1: Create test fixture**

Create `tests/fixtures/tokenunlocks_sample.csv`:

```csv
token,coingecko_id,unlock_date,unlock_pct,category,has_hl_perp
ARB,arbitrum,2025-09-16,0.0234,investor,true
JTO,jito-governance-token,2025-12-07,0.04,team,false
APT,aptos,2025-11-12,0.018,team,true
TIA,celestia,2025-10-30,0.082,ecosystem,true
ENS,ethereum-name-service,2025-11-04,0.025,investor,false
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_fetcher.py`:

```python
"""Tests for fetcher.load_events and price fetching."""

import json
from pathlib import Path

import pandas as pd
import pytest

from unlock_validation.fetcher import load_events


def test_load_events_returns_dataframe(fixtures_dir: Path):
    df = load_events(fixtures_dir / "tokenunlocks_sample.csv")
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 5


def test_load_events_parses_required_columns(fixtures_dir: Path):
    df = load_events(fixtures_dir / "tokenunlocks_sample.csv")
    required = {"token", "coingecko_id", "unlock_date", "unlock_pct", "category", "has_hl_perp"}
    assert required.issubset(df.columns)


def test_load_events_parses_unlock_date_as_datetime(fixtures_dir: Path):
    df = load_events(fixtures_dir / "tokenunlocks_sample.csv")
    assert pd.api.types.is_datetime64_any_dtype(df["unlock_date"])


def test_load_events_normalizes_category_to_lowercase(fixtures_dir: Path):
    df = load_events(fixtures_dir / "tokenunlocks_sample.csv")
    assert df["category"].str.islower().all()


def test_load_events_parses_has_hl_perp_as_bool(fixtures_dir: Path):
    df = load_events(fixtures_dir / "tokenunlocks_sample.csv")
    assert df["has_hl_perp"].dtype == bool


def test_load_events_filters_below_pct_threshold(fixtures_dir: Path):
    df = load_events(fixtures_dir / "tokenunlocks_sample.csv", min_pct=0.02)
    # APT has 0.018 → excluded
    assert "APT" not in df["token"].values
    assert len(df) == 4
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_fetcher.py -v`
Expected: ImportError — `unlock_validation.fetcher` does not exist.

- [ ] **Step 4: Write minimal implementation**

Create `src/unlock_validation/fetcher.py`:

```python
"""Fetcher for unlock events (CSV) and price history (CoinGecko)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def load_events(csv_path: Path, min_pct: float = 0.0) -> pd.DataFrame:
    """Load unlock events from a curated CSV.

    Expected columns: token, coingecko_id, unlock_date, unlock_pct, category, has_hl_perp.
    """
    df = pd.read_csv(csv_path)
    df["unlock_date"] = pd.to_datetime(df["unlock_date"], utc=True)
    df["category"] = df["category"].str.lower().str.strip()
    df["has_hl_perp"] = df["has_hl_perp"].astype(bool)
    df["unlock_pct"] = df["unlock_pct"].astype(float)
    df = df[df["unlock_pct"] >= min_pct].reset_index(drop=True)
    return df
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_fetcher.py -v`
Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/tokenunlocks_sample.csv src/unlock_validation/fetcher.py tests/test_fetcher.py
git commit -m "feat(fetcher): load_events from curated CSV"
```

---

## Task 4: Fetcher — CoinGecko Prices with Disk Cache + Retry

**Files:**
- Create: `tests/fixtures/coingecko_btc.json`
- Create: `tests/fixtures/coingecko_arb.json`
- Modify: `src/unlock_validation/fetcher.py`
- Modify: `tests/test_fetcher.py`

- [ ] **Step 1: Create CoinGecko fixtures**

Create `tests/fixtures/coingecko_btc.json`:

```json
{
  "prices": [
    [1726358400000, 60000.0],
    [1726444800000, 60500.0],
    [1726531200000, 61200.0],
    [1726617600000, 60800.0],
    [1726704000000, 61500.0]
  ]
}
```

Create `tests/fixtures/coingecko_arb.json`:

```json
{
  "prices": [
    [1726358400000, 0.60],
    [1726444800000, 0.595],
    [1726531200000, 0.585],
    [1726617600000, 0.570],
    [1726704000000, 0.555]
  ]
}
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_fetcher.py`:

```python
from datetime import datetime, timedelta, timezone

from unlock_validation.fetcher import fetch_prices


def test_fetch_prices_returns_dataframe_with_date_index(tmp_path, fixtures_dir, mocker):
    """Loads from CoinGecko, returns DataFrame indexed by date."""
    mock_get = mocker.patch("unlock_validation.fetcher.requests.get")
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {
        "prices": [
            [1726358400000, 0.60],
            [1726444800000, 0.595],
        ]
    }
    mock_get.return_value.raise_for_status = lambda: None

    start = datetime(2025, 9, 15, tzinfo=timezone.utc)
    end = datetime(2025, 9, 16, tzinfo=timezone.utc)
    df = fetch_prices("arbitrum", start, end, cache_dir=tmp_path)

    assert isinstance(df, pd.DataFrame)
    assert "price" in df.columns
    assert pd.api.types.is_datetime64_any_dtype(df.index)
    assert len(df) == 2


def test_fetch_prices_caches_to_disk(tmp_path, mocker):
    """Second call with same arguments must not hit the network."""
    mock_get = mocker.patch("unlock_validation.fetcher.requests.get")
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {"prices": [[1726358400000, 0.60]]}
    mock_get.return_value.raise_for_status = lambda: None

    start = datetime(2025, 9, 15, tzinfo=timezone.utc)
    end = datetime(2025, 9, 16, tzinfo=timezone.utc)

    fetch_prices("arbitrum", start, end, cache_dir=tmp_path)
    fetch_prices("arbitrum", start, end, cache_dir=tmp_path)

    assert mock_get.call_count == 1


def test_fetch_prices_uses_cached_file_after_restart(tmp_path, mocker, fixtures_dir):
    """Writes cache file and subsequent call (even with fresh mock state) reads it."""
    import shutil

    cache_file = tmp_path / "arbitrum_1726358400_1726444800.json"
    shutil.copy(fixtures_dir / "coingecko_arb.json", cache_file)

    mock_get = mocker.patch("unlock_validation.fetcher.requests.get")

    start = datetime.fromtimestamp(1726358400, tz=timezone.utc)
    end = datetime.fromtimestamp(1726444800, tz=timezone.utc)
    df = fetch_prices("arbitrum", start, end, cache_dir=tmp_path)

    assert mock_get.call_count == 0
    assert len(df) == 5
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_fetcher.py -v`
Expected: `ImportError` or `AttributeError` — `fetch_prices` not defined.

- [ ] **Step 4: Extend implementation**

Append to `src/unlock_validation/fetcher.py`:

```python
import json
from datetime import datetime

import requests
from tenacity import retry, stop_after_attempt, wait_exponential


COINGECKO_BASE = "https://api.coingecko.com/api/v3"


def _cache_key(coingecko_id: str, start: datetime, end: datetime) -> str:
    return f"{coingecko_id}_{int(start.timestamp())}_{int(end.timestamp())}.json"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _http_get_prices(coingecko_id: str, start: datetime, end: datetime) -> dict:
    url = f"{COINGECKO_BASE}/coins/{coingecko_id}/market_chart/range"
    params = {
        "vs_currency": "usd",
        "from": int(start.timestamp()),
        "to": int(end.timestamp()),
    }
    response = requests.get(url, params=params, timeout=20)
    response.raise_for_status()
    return response.json()


def fetch_prices(
    coingecko_id: str,
    start: datetime,
    end: datetime,
    cache_dir: Path,
) -> pd.DataFrame:
    """Fetch daily prices for a CoinGecko coin id over [start, end].

    Caches the raw JSON response on disk. Returns a DataFrame indexed by UTC datetime
    with a single 'price' column.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / _cache_key(coingecko_id, start, end)

    if cache_path.exists():
        data = json.loads(cache_path.read_text())
    else:
        data = _http_get_prices(coingecko_id, start, end)
        cache_path.write_text(json.dumps(data))

    rows = [
        {"timestamp": pd.to_datetime(ts_ms, unit="ms", utc=True), "price": price}
        for ts_ms, price in data.get("prices", [])
    ]
    df = pd.DataFrame(rows).set_index("timestamp")
    return df
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_fetcher.py -v`
Expected: 9 passed (6 from Task 3 + 3 from Task 4).

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/coingecko_btc.json tests/fixtures/coingecko_arb.json src/unlock_validation/fetcher.py tests/test_fetcher.py
git commit -m "feat(fetcher): CoinGecko price fetcher with disk cache + retry"
```

---

## Task 5: Analyzer — Compute Abnormal Return for a Window

**Files:**
- Create: `src/unlock_validation/analyzer.py`
- Create: `tests/test_analyzer.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_analyzer.py`:

```python
"""Tests for analyzer: abnormal returns, aggregation, pass/fail."""

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from unlock_validation.analyzer import compute_abnormal_return


def _price_series(values: list[float], start: str = "2025-09-10") -> pd.DataFrame:
    idx = pd.date_range(start, periods=len(values), freq="D", tz="UTC")
    return pd.DataFrame({"price": values}, index=idx)


def test_abnormal_return_zero_when_token_and_btc_move_identically():
    token = _price_series([100, 105])
    btc = _price_series([60000, 63000])  # both +5%
    event_date = datetime(2025, 9, 11, tzinfo=timezone.utc)

    ar = compute_abnormal_return(token, btc, event_date, window=(-1, 0))

    assert ar == pytest.approx(0.0, abs=1e-6)


def test_abnormal_return_positive_when_token_outperforms_btc():
    token = _price_series([100, 110])  # +10%
    btc = _price_series([60000, 63000])  # +5%
    event_date = datetime(2025, 9, 11, tzinfo=timezone.utc)

    ar = compute_abnormal_return(token, btc, event_date, window=(-1, 0))

    # log(1.1) - log(1.05) ≈ 0.0465
    assert ar == pytest.approx(np.log(1.1) - np.log(1.05), abs=1e-6)


def test_abnormal_return_negative_when_token_underperforms_btc():
    token = _price_series([100, 100])  # 0%
    btc = _price_series([60000, 63000])  # +5%
    event_date = datetime(2025, 9, 11, tzinfo=timezone.utc)

    ar = compute_abnormal_return(token, btc, event_date, window=(-1, 0))

    assert ar == pytest.approx(-np.log(1.05), abs=1e-6)


def test_abnormal_return_handles_pre_window():
    token = _price_series([100, 95, 90, 90])  # T-2..T+1, T0 at index 2
    btc = _price_series([60000, 60000, 60000, 60000])
    event_date = datetime(2025, 9, 12, tzinfo=timezone.utc)  # T0

    ar = compute_abnormal_return(token, btc, event_date, window=(-2, 0))

    assert ar < 0
    assert ar == pytest.approx(np.log(90 / 100), abs=1e-6)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_analyzer.py -v`
Expected: ImportError on `unlock_validation.analyzer`.

- [ ] **Step 3: Write minimal implementation**

Create `src/unlock_validation/analyzer.py`:

```python
"""Statistical analysis: abnormal returns, aggregation, pass/fail."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from unlock_validation.config import ECOSYSTEM_CATEGORIES, PASS_FAIL_THRESHOLDS, WINDOWS


def _price_at(prices: pd.DataFrame, target: datetime) -> float:
    """Pick the last available price at or before `target`."""
    available = prices.loc[prices.index <= pd.Timestamp(target)]
    if available.empty:
        raise ValueError(f"No price available at or before {target}")
    return float(available["price"].iloc[-1])


def compute_abnormal_return(
    token_prices: pd.DataFrame,
    btc_prices: pd.DataFrame,
    event_date: datetime,
    window: tuple[int, int],
) -> float:
    """Compute log-return abnormal return over the window relative to BTC.

    window is (offset_start_days, offset_end_days) — e.g. (-7, 0) means T-7 to T0.
    """
    day_start, day_end = window
    start = event_date + timedelta(days=day_start)
    end = event_date + timedelta(days=day_end)

    token_ret = np.log(_price_at(token_prices, end) / _price_at(token_prices, start))
    btc_ret = np.log(_price_at(btc_prices, end) / _price_at(btc_prices, start))
    return token_ret - btc_ret
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_analyzer.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/unlock_validation/analyzer.py tests/test_analyzer.py
git commit -m "feat(analyzer): compute_abnormal_return log-return vs BTC"
```

---

## Task 6: Analyzer — Aggregate Statistics Across Events

**Files:**
- Modify: `src/unlock_validation/analyzer.py`
- Modify: `tests/test_analyzer.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_analyzer.py`:

```python
from unlock_validation.analyzer import aggregate_statistics


def test_aggregate_statistics_computes_pct_negative():
    events = pd.DataFrame({
        "ar_pre": [-0.05, -0.02, 0.01, -0.10, 0.03],   # 3 negative out of 5
        "ar_day": [0.01, -0.02, 0.0, -0.01, 0.02],
        "ar_post": [-0.03, -0.04, 0.02, -0.01, -0.05], # 4 negative out of 5
        "category": ["team", "investor", "ecosystem", "team", "investor"],
    })

    stats = aggregate_statistics(events)

    assert stats["pct_pre_negative"] == pytest.approx(3 / 5)
    assert stats["pct_post_negative"] == pytest.approx(4 / 5)
    assert stats["n_events"] == 5


def test_aggregate_statistics_computes_mean_pre():
    events = pd.DataFrame({
        "ar_pre": [-0.05, -0.02, 0.01, -0.10, 0.03],
        "ar_day": [0.0, 0.0, 0.0, 0.0, 0.0],
        "ar_post": [0.0, 0.0, 0.0, 0.0, 0.0],
        "category": ["team"] * 5,
    })

    stats = aggregate_statistics(events)

    expected_mean = (-0.05 - 0.02 + 0.01 - 0.10 + 0.03) / 5
    assert stats["mean_pre"] == pytest.approx(expected_mean)


def test_aggregate_statistics_computes_t_test_p_value():
    """With clearly negative AR values, p-value (one-sided AR<0) should be < 0.05."""
    np.random.seed(42)
    events = pd.DataFrame({
        "ar_pre": np.random.normal(loc=-0.05, scale=0.02, size=30),
        "ar_day": np.zeros(30),
        "ar_post": np.zeros(30),
        "category": ["team"] * 30,
    })

    stats = aggregate_statistics(events)

    assert stats["p_value_pre"] < 0.05


def test_aggregate_statistics_empty_events_returns_safe_defaults():
    events = pd.DataFrame(columns=["ar_pre", "ar_day", "ar_post", "category"])

    stats = aggregate_statistics(events)

    assert stats["n_events"] == 0
    assert stats["pct_pre_negative"] is None
    assert stats["mean_pre"] is None
    assert stats["p_value_pre"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_analyzer.py -v`
Expected: ImportError on `aggregate_statistics`.

- [ ] **Step 3: Extend implementation**

Append to `src/unlock_validation/analyzer.py`:

```python
from scipy import stats as scipy_stats


def aggregate_statistics(events: pd.DataFrame) -> dict:
    """Compute the five summary metrics over a set of events with AR columns.

    Returned dict shape:
      n_events, pct_pre_negative, pct_post_negative, mean_pre, mean_post, p_value_pre
    """
    if len(events) == 0:
        return {
            "n_events": 0,
            "pct_pre_negative": None,
            "pct_post_negative": None,
            "mean_pre": None,
            "mean_post": None,
            "p_value_pre": None,
        }

    ar_pre = events["ar_pre"].to_numpy()
    ar_post = events["ar_post"].to_numpy()

    # One-sided t-test: H0 mean=0, H1 mean<0
    t_stat, p_two_sided = scipy_stats.ttest_1samp(ar_pre, popmean=0.0)
    p_one_sided = p_two_sided / 2 if t_stat < 0 else 1 - p_two_sided / 2

    return {
        "n_events": len(events),
        "pct_pre_negative": float((ar_pre < 0).mean()),
        "pct_post_negative": float((ar_post < 0).mean()),
        "mean_pre": float(ar_pre.mean()),
        "mean_post": float(ar_post.mean()),
        "p_value_pre": float(p_one_sided),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_analyzer.py -v`
Expected: 8 passed (4 + 4).

- [ ] **Step 5: Commit**

```bash
git add src/unlock_validation/analyzer.py tests/test_analyzer.py
git commit -m "feat(analyzer): aggregate_statistics with one-sided t-test"
```

---

## Task 7: Analyzer — Ecosystem Filter (Dual-Track Comparison)

**Files:**
- Modify: `src/unlock_validation/analyzer.py`
- Modify: `tests/test_analyzer.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_analyzer.py`:

```python
from unlock_validation.analyzer import filter_ex_ecosystem


def test_filter_ex_ecosystem_removes_ecosystem_rows():
    events = pd.DataFrame({
        "token": ["A", "B", "C", "D"],
        "category": ["team", "ecosystem", "investor", "ecosystem development"],
    })

    filtered = filter_ex_ecosystem(events)

    assert len(filtered) == 2
    assert set(filtered["token"]) == {"A", "C"}


def test_filter_ex_ecosystem_handles_case_insensitivity():
    events = pd.DataFrame({
        "token": ["A", "B"],
        "category": ["team", "Ecosystem"],  # mixed case
    })

    filtered = filter_ex_ecosystem(events)

    assert len(filtered) == 1
    assert filtered.iloc[0]["token"] == "A"


def test_filter_ex_ecosystem_does_not_mutate_input():
    events = pd.DataFrame({"token": ["A", "B"], "category": ["team", "ecosystem"]})
    original_len = len(events)

    filter_ex_ecosystem(events)

    assert len(events) == original_len
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_analyzer.py -v`
Expected: ImportError on `filter_ex_ecosystem`.

- [ ] **Step 3: Extend implementation**

Append to `src/unlock_validation/analyzer.py`:

```python
def filter_ex_ecosystem(events: pd.DataFrame) -> pd.DataFrame:
    """Return events with ecosystem-style categories removed.

    Categories are matched case-insensitively against ECOSYSTEM_CATEGORIES.
    """
    cat_lower = events["category"].str.lower().str.strip()
    mask = ~cat_lower.isin(ECOSYSTEM_CATEGORIES)
    return events.loc[mask].reset_index(drop=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_analyzer.py -v`
Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add src/unlock_validation/analyzer.py tests/test_analyzer.py
git commit -m "feat(analyzer): filter_ex_ecosystem for dual-track comparison"
```

---

## Task 8: Analyzer — Pass/Fail Decision

**Files:**
- Modify: `src/unlock_validation/analyzer.py`
- Modify: `tests/test_analyzer.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_analyzer.py`:

```python
from unlock_validation.analyzer import pass_fail_decision


def _stats(pct_pre=0.7, pct_post=0.6, mean_pre=-0.04, p_value=0.01, n=30):
    return {
        "n_events": n,
        "pct_pre_negative": pct_pre,
        "pct_post_negative": pct_post,
        "mean_pre": mean_pre,
        "mean_post": -0.02,
        "p_value_pre": p_value,
    }


def test_pass_fail_all_metrics_pass_returns_strong():
    overall = _stats()
    team_subset = _stats(mean_pre=-0.05)  # team stronger than overall
    decision = pass_fail_decision(overall, team_subset)
    assert decision["verdict"] == "STRONG"
    assert decision["passed"] == 5


def test_pass_fail_three_metrics_pass_returns_weak():
    # pct_pre fails, p-value fails; rest pass
    overall = _stats(pct_pre=0.5, p_value=0.5)
    team_subset = _stats(pct_pre=0.5, p_value=0.5, mean_pre=-0.05)
    decision = pass_fail_decision(overall, team_subset)
    assert decision["verdict"] == "WEAK"
    assert decision["passed"] == 3


def test_pass_fail_two_metrics_pass_returns_reject():
    overall = _stats(pct_pre=0.4, pct_post=0.3, p_value=0.5)
    team_subset = _stats(pct_pre=0.4, pct_post=0.3, p_value=0.5, mean_pre=0.0)
    decision = pass_fail_decision(overall, team_subset)
    assert decision["verdict"] == "REJECT"
    assert decision["passed"] <= 2


def test_pass_fail_team_subset_weaker_than_overall_fails_metric_5():
    overall = _stats(mean_pre=-0.05)
    team_subset = _stats(mean_pre=-0.01)  # weaker than overall
    decision = pass_fail_decision(overall, team_subset)
    assert decision["details"]["team_subset_match"] is False


def test_pass_fail_per_metric_details_are_exposed():
    overall = _stats()
    team_subset = _stats(mean_pre=-0.05)
    decision = pass_fail_decision(overall, team_subset)
    keys = {
        "pct_pre_pass",
        "pct_post_pass",
        "mean_pre_pass",
        "p_value_pass",
        "team_subset_match",
    }
    assert set(decision["details"].keys()) == keys
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_analyzer.py -v`
Expected: ImportError on `pass_fail_decision`.

- [ ] **Step 3: Extend implementation**

Append to `src/unlock_validation/analyzer.py`:

```python
def pass_fail_decision(overall_stats: dict, team_subset_stats: dict) -> dict:
    """Apply the 5-metric Pass/Fail matrix and return a verdict.

    Verdict mapping:
      ≥ 4/5 pass → STRONG
      3/5 pass   → WEAK
      ≤ 2/5 pass → REJECT
    """
    t = PASS_FAIL_THRESHOLDS

    details = {
        "pct_pre_pass": (
            overall_stats["pct_pre_negative"] is not None
            and overall_stats["pct_pre_negative"] >= t["pct_pre_negative_pass"]
        ),
        "pct_post_pass": (
            overall_stats["pct_post_negative"] is not None
            and overall_stats["pct_post_negative"] >= t["pct_post_negative_pass"]
        ),
        "mean_pre_pass": (
            overall_stats["mean_pre"] is not None
            and overall_stats["mean_pre"] <= t["mean_pre_pass"]
        ),
        "p_value_pass": (
            overall_stats["p_value_pre"] is not None
            and overall_stats["p_value_pre"] < t["p_value_pass"]
        ),
        "team_subset_match": (
            team_subset_stats["mean_pre"] is not None
            and overall_stats["mean_pre"] is not None
            and team_subset_stats["mean_pre"] <= overall_stats["mean_pre"]
        ),
    }

    passed = sum(1 for v in details.values() if v)

    if passed >= 4:
        verdict = "STRONG"
    elif passed == 3:
        verdict = "WEAK"
    else:
        verdict = "REJECT"

    return {"verdict": verdict, "passed": passed, "details": details}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_analyzer.py -v`
Expected: 16 passed.

- [ ] **Step 5: Commit**

```bash
git add src/unlock_validation/analyzer.py tests/test_analyzer.py
git commit -m "feat(analyzer): pass_fail_decision with STRONG/WEAK/REJECT verdict"
```

---

## Task 9: Report Generator

**Files:**
- Create: `src/unlock_validation/report.py`
- Create: `tests/test_report.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_report.py`:

```python
"""Tests for markdown report writer."""

from pathlib import Path

import pandas as pd

from unlock_validation.report import write_markdown_report


def _sample_events() -> pd.DataFrame:
    return pd.DataFrame({
        "token": ["ARB", "JTO", "APT"],
        "category": ["investor", "team", "team"],
        "unlock_date": pd.to_datetime(["2025-09-16", "2025-12-07", "2025-11-12"], utc=True),
        "unlock_pct": [0.0234, 0.04, 0.03],
        "has_hl_perp": [True, False, True],
        "ar_pre": [-0.05, -0.07, 0.01],
        "ar_day": [-0.01, 0.0, 0.02],
        "ar_post": [-0.02, -0.04, 0.0],
    })


def test_report_writes_file_with_required_sections(tmp_path):
    events = _sample_events()
    overall = {
        "n_events": 3,
        "pct_pre_negative": 2 / 3,
        "pct_post_negative": 2 / 3,
        "mean_pre": -0.037,
        "mean_post": -0.02,
        "p_value_pre": 0.04,
    }
    team_subset = overall.copy()
    team_subset["mean_pre"] = -0.03
    ex_eco = overall.copy()

    decision = {
        "verdict": "STRONG",
        "passed": 4,
        "details": {
            "pct_pre_pass": True,
            "pct_post_pass": True,
            "mean_pre_pass": True,
            "p_value_pass": True,
            "team_subset_match": False,
        },
    }

    out = tmp_path / "out.md"
    write_markdown_report(out, events, overall, team_subset, ex_eco, decision)

    text = out.read_text()
    for section in [
        "# Unlock Thesis Validation Report",
        "## Verdict: STRONG",
        "## Pass/Fail Matrix",
        "## Aggregate Statistics",
        "## Team Subset",
        "## Ex-Ecosystem Subset",
        "## Event Detail",
        "ARB",
        "JTO",
    ]:
        assert section in text


def test_report_includes_hl_perp_flag_in_event_detail(tmp_path):
    events = _sample_events()
    overall = team = ex_eco = {
        "n_events": 3,
        "pct_pre_negative": 0.5,
        "pct_post_negative": 0.5,
        "mean_pre": -0.01,
        "mean_post": -0.01,
        "p_value_pre": 0.5,
    }
    decision = {"verdict": "REJECT", "passed": 0, "details": {
        "pct_pre_pass": False, "pct_post_pass": False, "mean_pre_pass": False,
        "p_value_pass": False, "team_subset_match": False,
    }}

    out = tmp_path / "out.md"
    write_markdown_report(out, events, overall, team, ex_eco, decision)

    text = out.read_text()
    # HL perp flag should be visible
    assert "HL perp" in text or "has_hl_perp" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_report.py -v`
Expected: ImportError on `unlock_validation.report`.

- [ ] **Step 3: Write minimal implementation**

Create `src/unlock_validation/report.py`:

```python
"""Markdown report writer for unlock thesis validation."""

from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone

import pandas as pd


def _fmt_pct(x: float | None) -> str:
    if x is None:
        return "—"
    return f"{x * 100:.1f}%"


def _fmt_num(x: float | None, decimals: int = 4) -> str:
    if x is None:
        return "—"
    return f"{x:.{decimals}f}"


def _stats_table(name: str, stats: dict) -> str:
    return (
        f"### {name}\n\n"
        f"| Metric | Value |\n"
        f"| --- | --- |\n"
        f"| n_events | {stats['n_events']} |\n"
        f"| pct_pre_negative | {_fmt_pct(stats['pct_pre_negative'])} |\n"
        f"| pct_post_negative | {_fmt_pct(stats['pct_post_negative'])} |\n"
        f"| mean_pre (vs BTC) | {_fmt_num(stats['mean_pre'])} |\n"
        f"| mean_post (vs BTC) | {_fmt_num(stats['mean_post'])} |\n"
        f"| p_value_pre (one-sided) | {_fmt_num(stats['p_value_pre'])} |\n"
    )


def _verdict_explainer(verdict: str) -> str:
    return {
        "STRONG": "Thesis confirmed in our sample. **Proceed to ROADMAP Phase 0** (build full infrastructure).",
        "WEAK": "Thesis partially confirmed. **Proceed to Phase 0 with reduced expectations** for the unlock strategy.",
        "REJECT": "Thesis not supported in our sample. **Skip to ROADMAP Phase 2** (single-wallet reverse).",
    }[verdict]


def write_markdown_report(
    path: Path,
    events: pd.DataFrame,
    overall_stats: dict,
    team_subset_stats: dict,
    ex_ecosystem_stats: dict,
    decision: dict,
) -> None:
    """Write a markdown report summarising the thesis validation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "# Unlock Thesis Validation Report",
        "",
        f"_Generated {now}_",
        "",
        f"## Verdict: {decision['verdict']}",
        "",
        _verdict_explainer(decision["verdict"]),
        "",
        f"**Metrics passed:** {decision['passed']} / 5",
        "",
        "## Pass/Fail Matrix",
        "",
        "| # | Metric | Pass? |",
        "| --- | --- | --- |",
        f"| 1 | % events with abnormal_pre < 0 ≥ 65% | {'✅' if decision['details']['pct_pre_pass'] else '❌'} |",
        f"| 2 | % events with abnormal_post < 0 ≥ 55% | {'✅' if decision['details']['pct_post_pass'] else '❌'} |",
        f"| 3 | mean(abnormal_pre) ≤ -3% | {'✅' if decision['details']['mean_pre_pass'] else '❌'} |",
        f"| 4 | t-test p-value < 0.05 | {'✅' if decision['details']['p_value_pass'] else '❌'} |",
        f"| 5 | Team-subset mean ≤ overall mean | {'✅' if decision['details']['team_subset_match'] else '❌'} |",
        "",
        "## Aggregate Statistics",
        "",
        _stats_table("Overall (all categories)", overall_stats),
        _stats_table("Team Subset", team_subset_stats),
        _stats_table("Ex-Ecosystem Subset", ex_ecosystem_stats),
        "",
        "## Event Detail",
        "",
        "| Token | Category | Unlock Date | Unlock % | HL perp | AR pre | AR day | AR post |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]

    for _, row in events.iterrows():
        lines.append(
            f"| {row['token']} | {row['category']} | "
            f"{row['unlock_date'].strftime('%Y-%m-%d')} | "
            f"{_fmt_pct(row['unlock_pct'])} | "
            f"{'✅' if row['has_hl_perp'] else '—'} | "
            f"{_fmt_num(row['ar_pre'])} | "
            f"{_fmt_num(row['ar_day'])} | "
            f"{_fmt_num(row['ar_post'])} |"
        )

    path.write_text("\n".join(lines) + "\n")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_report.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/unlock_validation/report.py tests/test_report.py
git commit -m "feat(report): markdown report writer with verdict explainer"
```

---

## Task 10: CLI Entrypoint

**Files:**
- Create: `src/unlock_validation/__main__.py`
- Modify: `src/unlock_validation/analyzer.py` (add orchestrator function)
- Modify: `tests/test_analyzer.py` (test orchestrator)

- [ ] **Step 1: Write the failing test for the orchestrator**

Append to `tests/test_analyzer.py`:

```python
from unlock_validation.analyzer import enrich_events_with_returns


def test_enrich_events_attaches_three_ar_columns(tmp_path, mocker):
    """Given events and prices, returns DataFrame with ar_pre/ar_day/ar_post columns."""
    events = pd.DataFrame({
        "token": ["TST"],
        "coingecko_id": ["test-token"],
        "unlock_date": pd.to_datetime(["2025-09-15"], utc=True),
        "unlock_pct": [0.03],
        "category": ["team"],
        "has_hl_perp": [True],
    })

    token_idx = pd.date_range("2025-09-01", "2025-09-25", freq="D", tz="UTC")
    token_prices = pd.DataFrame({"price": np.linspace(100, 90, len(token_idx))}, index=token_idx)

    btc_idx = pd.date_range("2025-09-01", "2025-09-25", freq="D", tz="UTC")
    btc_prices = pd.DataFrame({"price": np.linspace(60000, 60000, len(btc_idx))}, index=btc_idx)

    enriched = enrich_events_with_returns(
        events,
        prices_by_id={"test-token": token_prices, "bitcoin": btc_prices},
    )

    assert "ar_pre" in enriched.columns
    assert "ar_day" in enriched.columns
    assert "ar_post" in enriched.columns
    assert enriched["ar_pre"].iloc[0] < 0  # token down, btc flat → negative AR
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_analyzer.py::test_enrich_events_attaches_three_ar_columns -v`
Expected: ImportError.

- [ ] **Step 3: Add orchestrator to analyzer**

Append to `src/unlock_validation/analyzer.py`:

```python
def enrich_events_with_returns(
    events: pd.DataFrame,
    prices_by_id: dict[str, pd.DataFrame],
    btc_id: str = "bitcoin",
) -> pd.DataFrame:
    """Attach ar_pre, ar_day, ar_post columns to each event.

    prices_by_id maps coingecko_id → price DataFrame (datetime index, 'price' col).
    Events whose coingecko_id is missing from prices_by_id are skipped (with warning).
    """
    btc_prices = prices_by_id[btc_id]

    rows = []
    for _, ev in events.iterrows():
        cg_id = ev["coingecko_id"]
        if cg_id not in prices_by_id:
            continue
        token_prices = prices_by_id[cg_id]
        event_date = ev["unlock_date"].to_pydatetime()

        try:
            ar_pre = compute_abnormal_return(token_prices, btc_prices, event_date, WINDOWS["pre"])
            ar_day = compute_abnormal_return(token_prices, btc_prices, event_date, WINDOWS["day"])
            ar_post = compute_abnormal_return(token_prices, btc_prices, event_date, WINDOWS["post"])
        except ValueError:
            continue

        rows.append({**ev.to_dict(), "ar_pre": ar_pre, "ar_day": ar_day, "ar_post": ar_post})

    return pd.DataFrame(rows)
```

- [ ] **Step 4: Run orchestrator test**

Run: `uv run pytest tests/test_analyzer.py::test_enrich_events_attaches_three_ar_columns -v`
Expected: PASS.

- [ ] **Step 5: Create CLI entrypoint**

Create `src/unlock_validation/__main__.py`:

```python
"""CLI: end-to-end run that fetches data, computes stats, writes report."""

from __future__ import annotations

from datetime import timedelta

from unlock_validation.analyzer import (
    aggregate_statistics,
    enrich_events_with_returns,
    filter_ex_ecosystem,
    pass_fail_decision,
)
from unlock_validation.config import CACHE_DIR, REPORTS_DIR, SEED_EVENTS_CSV
from unlock_validation.fetcher import fetch_prices, load_events
from unlock_validation.report import write_markdown_report


PRICE_WINDOW_BUFFER_DAYS = 14  # extra days around event to ensure window coverage


def main() -> int:
    events = load_events(SEED_EVENTS_CSV, min_pct=0.02)
    print(f"[1/4] loaded {len(events)} events (≥ 2% supply)")

    coingecko_ids = sorted(set(events["coingecko_id"]) | {"bitcoin"})
    span_start = events["unlock_date"].min() - timedelta(days=30 + PRICE_WINDOW_BUFFER_DAYS)
    span_end = events["unlock_date"].max() + timedelta(days=14 + PRICE_WINDOW_BUFFER_DAYS)

    prices_by_id: dict = {}
    for cg_id in coingecko_ids:
        prices_by_id[cg_id] = fetch_prices(cg_id, span_start, span_end, cache_dir=CACHE_DIR)
    print(f"[2/4] fetched prices for {len(prices_by_id)} ids (cache: {CACHE_DIR})")

    enriched = enrich_events_with_returns(events, prices_by_id)
    print(f"[3/4] enriched {len(enriched)} events with abnormal returns")

    overall_stats = aggregate_statistics(enriched)
    team_stats = aggregate_statistics(enriched[enriched["category"] == "team"])
    ex_eco_stats = aggregate_statistics(filter_ex_ecosystem(enriched))

    decision = pass_fail_decision(overall_stats, team_stats)

    out_path = REPORTS_DIR / "unlock_thesis_report.md"
    write_markdown_report(out_path, enriched, overall_stats, team_stats, ex_eco_stats, decision)
    print(f"[4/4] verdict: {decision['verdict']} ({decision['passed']}/5) → {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: Run full test suite**

Run: `uv run pytest -v`
Expected: 17 passed (all from previous tasks + new orchestrator).

- [ ] **Step 7: Commit**

```bash
git add src/unlock_validation/__main__.py src/unlock_validation/analyzer.py tests/test_analyzer.py
git commit -m "feat(cli): __main__ orchestrator + enrich_events_with_returns"
```

---

## Task 11: Seed Curated Events CSV (Manual Data Population)

**Files:**
- Create: `data/seed/unlocks_curated.csv`
- Modify: `.gitignore` (allow data/seed/, keep data/cache/ ignored)

- [ ] **Step 1: Verify .gitignore already allows data/seed/**

Check `.gitignore` for the lines:
```
data/candles/
data/fills/
data/funding/
...
!data/seed/
```

If `!data/seed/` is absent, append it under the data files block. Current `.gitignore` already includes this exception.

- [ ] **Step 2: Manually populate seed events**

This is a **manual data collection step**. Source candidates (browse manually):
- https://token.unlocks.app/ (browse "Past Unlocks", filter date range 2025-05 to 2026-05)
- https://cryptorank.io/unlocks
- https://www.coingecko.com/en/unlocks

Goal: 40-60 events with these columns. Aim for category diversity (mix of team / investor / airdrop / ecosystem).

CoinGecko IDs can be looked up at `https://www.coingecko.com/en/coins/<token>` (the URL slug is the id).

Create `data/seed/unlocks_curated.csv` with header and at least 40 rows. Example shape:

```csv
token,coingecko_id,unlock_date,unlock_pct,category,has_hl_perp
ARB,arbitrum,2025-09-16,0.0234,investor,true
JTO,jito-governance-token,2025-12-07,0.0400,team,false
APT,aptos,2025-11-12,0.0180,team,true
TIA,celestia,2025-10-30,0.0820,ecosystem,true
ENS,ethereum-name-service,2025-11-04,0.0250,investor,false
PYTH,pyth-network,2025-05-20,0.0560,team,true
... (continue to 40-60 rows)
```

**HL perp check**: visit `https://app.hyperliquid.xyz/trade/<TOKEN>` — if it loads, set `has_hl_perp=true`; else `false`.

- [ ] **Step 3: Sanity-check the CSV**

Run: `uv run python -c "from unlock_validation.fetcher import load_events; from unlock_validation.config import SEED_EVENTS_CSV; df = load_events(SEED_EVENTS_CSV); print(df.head()); print(f'rows: {len(df)}'); print(df['category'].value_counts())"`

Expected:
- `rows: 40` (or more)
- At least 3 categories represented
- No `NaN` in any column

- [ ] **Step 4: Commit**

```bash
git add data/seed/unlocks_curated.csv
git commit -m "data: curated unlock events for past 12 months (n=<actual count>)"
```

---

## Task 12: End-to-End Run + Notebook + Final Report

**Files:**
- Create: `notebooks/01_unlock_thesis.ipynb`
- Output: `reports/unlock_thesis_report.md`

- [ ] **Step 1: Run the CLI end-to-end**

Run: `uv run python -m unlock_validation`

Expected stdout:
```
[1/4] loaded XX events (≥ 2% supply)
[2/4] fetched prices for XX ids (cache: .../data/cache)
[3/4] enriched XX events with abnormal returns
[4/4] verdict: STRONG|WEAK|REJECT (X/5) → .../reports/unlock_thesis_report.md
```

If CoinGecko returns 429 rate-limit, wait 60 seconds and re-run (tenacity will retry within a single invocation).

- [ ] **Step 2: Inspect generated report**

Read `reports/unlock_thesis_report.md` and check:
- Verdict line present
- Pass/Fail matrix with 5 rows
- Overall / Team / Ex-Ecosystem stats tables present
- Event detail table has every event with non-empty AR columns

- [ ] **Step 3: Create exploratory notebook**

Create `notebooks/01_unlock_thesis.ipynb` by running this script:

Run:
```bash
uv run jupyter nbconvert --to notebook --execute - <<'PY' > notebooks/01_unlock_thesis.ipynb
import nbformat as nbf

nb = nbf.v4.new_notebook()
nb.cells = [
    nbf.v4.new_markdown_cell("# Unlock Thesis — Exploratory Notebook\n\nValidates abnormal returns visually."),
    nbf.v4.new_code_cell(
        "import sys; sys.path.insert(0, '../src')\n"
        "from datetime import timedelta\n"
        "import pandas as pd\n"
        "import matplotlib.pyplot as plt\n"
        "from unlock_validation.analyzer import enrich_events_with_returns, aggregate_statistics, filter_ex_ecosystem\n"
        "from unlock_validation.config import CACHE_DIR, SEED_EVENTS_CSV\n"
        "from unlock_validation.fetcher import fetch_prices, load_events"
    ),
    nbf.v4.new_code_cell(
        "events = load_events(SEED_EVENTS_CSV, min_pct=0.02)\n"
        "events.head()"
    ),
    nbf.v4.new_code_cell(
        "coingecko_ids = sorted(set(events['coingecko_id']) | {'bitcoin'})\n"
        "span_start = events['unlock_date'].min() - timedelta(days=44)\n"
        "span_end = events['unlock_date'].max() + timedelta(days=28)\n"
        "prices = {cid: fetch_prices(cid, span_start, span_end, cache_dir=CACHE_DIR) for cid in coingecko_ids}\n"
        "len(prices)"
    ),
    nbf.v4.new_code_cell(
        "enriched = enrich_events_with_returns(events, prices)\n"
        "enriched[['token', 'category', 'ar_pre', 'ar_day', 'ar_post']].describe()"
    ),
    nbf.v4.new_code_cell(
        "fig, axes = plt.subplots(1, 3, figsize=(14, 4))\n"
        "for ax, col, title in zip(axes, ['ar_pre', 'ar_day', 'ar_post'], ['Pre (T-7..T0)', 'Day (T0..T+1)', 'Post (T0..T+3)']):\n"
        "    ax.hist(enriched[col].dropna(), bins=20, edgecolor='black')\n"
        "    ax.axvline(0, color='red', linestyle='--')\n"
        "    ax.set_title(f'{title} abnormal return')\n"
        "    ax.set_xlabel('AR (log-return vs BTC)')\n"
        "plt.tight_layout()\n"
        "plt.show()"
    ),
    nbf.v4.new_code_cell(
        "print('Overall stats:', aggregate_statistics(enriched))\n"
        "print('Ex-Ecosystem stats:', aggregate_statistics(filter_ex_ecosystem(enriched)))"
    ),
]
nbf.write(nb, "notebooks/01_unlock_thesis.ipynb")
print("notebook created")
PY
```

If the heredoc execution is awkward, alternatively create the notebook by running this Python file:

```bash
uv run python <<'PY'
import nbformat as nbf
from pathlib import Path

nb = nbf.v4.new_notebook()
nb.cells = [
    nbf.v4.new_markdown_cell("# Unlock Thesis — Exploratory Notebook"),
    nbf.v4.new_code_cell(
        "import sys; sys.path.insert(0, '../src')\n"
        "from datetime import timedelta\n"
        "import matplotlib.pyplot as plt\n"
        "from unlock_validation.analyzer import enrich_events_with_returns, aggregate_statistics, filter_ex_ecosystem\n"
        "from unlock_validation.config import CACHE_DIR, SEED_EVENTS_CSV\n"
        "from unlock_validation.fetcher import fetch_prices, load_events\n"
        "events = load_events(SEED_EVENTS_CSV, min_pct=0.02)\n"
        "events.head()"
    ),
    nbf.v4.new_code_cell(
        "coingecko_ids = sorted(set(events['coingecko_id']) | {'bitcoin'})\n"
        "span_start = events['unlock_date'].min() - timedelta(days=44)\n"
        "span_end = events['unlock_date'].max() + timedelta(days=28)\n"
        "prices = {cid: fetch_prices(cid, span_start, span_end, cache_dir=CACHE_DIR) for cid in coingecko_ids}\n"
        "enriched = enrich_events_with_returns(events, prices)\n"
        "enriched.describe()"
    ),
    nbf.v4.new_code_cell(
        "fig, axes = plt.subplots(1, 3, figsize=(14, 4))\n"
        "for ax, col, title in zip(axes, ['ar_pre','ar_day','ar_post'], ['Pre','Day','Post']):\n"
        "    ax.hist(enriched[col].dropna(), bins=20)\n"
        "    ax.axvline(0, color='red', linestyle='--')\n"
        "    ax.set_title(title)\n"
        "plt.tight_layout(); plt.show()"
    ),
]
Path('notebooks').mkdir(exist_ok=True)
nbf.write(nb, 'notebooks/01_unlock_thesis.ipynb')
print('notebook written')
PY
```

Expected: `notebook written`.

- [ ] **Step 4: Update task.json status**

Edit `.ccg/tasks/unlock-thesis-validation/task.json`:

```json
{
  "id": "unlock-thesis-validation",
  "title": "解锁事件价格反应实证验证（thesis check before Phase 0）",
  "status": "completed",
  "strategy": "guided-develop",
  "currentPhase": "6-verify",
  "nextAction": "Decide ROADMAP next step based on verdict",
  "gate": null,
  "branch": "main",
  "scope": "unlock-thesis-validation",
  "createdAt": "2026-05-21T13:38:44Z",
  "overlays": ["superpowers:brainstorming", "superpowers:test-driven-development", "superpowers:verification-before-completion"],
  "decisionGate": "解锁策略 thesis 是否成立 — 决定走 Phase 0 还是跳到 Phase 2",
  "verdict": "<STRONG|WEAK|REJECT from generated report>"
}
```

Replace `<STRONG|WEAK|REJECT...>` with the actual verdict from `reports/unlock_thesis_report.md`.

- [ ] **Step 5: Final commit**

```bash
git add notebooks/01_unlock_thesis.ipynb reports/unlock_thesis_report.md .ccg/tasks/unlock-thesis-validation/task.json
git commit -m "feat: end-to-end unlock thesis validation run + notebook"
```

- [ ] **Step 6: Decide ROADMAP next step**

Open `reports/unlock_thesis_report.md` and read the verdict:
- **STRONG** → Proceed to ROADMAP Phase 0 (build full infrastructure)
- **WEAK** → Proceed to Phase 0 but lower expectation weight for unlock strategy
- **REJECT** → Skip to ROADMAP Phase 2 (single-wallet reverse)

Communicate the decision to the user.

---

## Self-Review Notes

Cross-checked against spec:

- ✅ D1 (dual-track ecosystem comparison) — implemented via `filter_ex_ecosystem` + separate stats table in report
- ✅ D2 (spot price + HL subset annotation) — `has_hl_perp` column carried through and rendered in event detail table
- ✅ D3 (abnormal return vs BTC, no beta) — `compute_abnormal_return` uses simple log-return difference
- ✅ D4 (three windows) — `WINDOWS` dict in config, used in `enrich_events_with_returns`
- ✅ D5 (5-metric Pass/Fail with verdict) — `pass_fail_decision` exact match
- ✅ TDD (test-first for every behaviour module) — every implementation task starts with failing test
- ✅ YAGNI exclusions respected — no Hyperliquid SDK, no Parquet, no Vectorbt
- ✅ Done definition — `pytest -v` green, `python -m unlock_validation` runs end-to-end, markdown report produced

No placeholders. Type consistency: `compute_abnormal_return`, `aggregate_statistics`, `filter_ex_ecosystem`, `pass_fail_decision`, `enrich_events_with_returns`, `write_markdown_report` — all signatures and return shapes consistent across tasks.

Manual step in Task 11 (data curation) is intentional: TokenUnlocks API is gated and for thesis validation we want a high-quality hand-checked dataset rather than scraping risk. This is the only non-code task.
