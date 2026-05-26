"""Load deployed active strategy configs for portfolio composition."""

from __future__ import annotations

import glob
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass(frozen=True, eq=False)
class LoadedSignal:
    name: str
    returns: pd.Series
    bayesian_ci: tuple[float, float, float]
    sharpe_lower: float
    weight_max: float
    config_path: Path
    raw_config: dict[str, Any]

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, LoadedSignal):
            return NotImplemented
        return (
            self.name == other.name
            and self.returns.equals(other.returns)
            and self.bayesian_ci == other.bayesian_ci
            and self.sharpe_lower == other.sharpe_lower
            and self.weight_max == other.weight_max
            and self.config_path == other.config_path
            and self.raw_config == other.raw_config
        )


REQUIRED_KEYS = (
    "signal",
    "source_parquet",
    "sharpe_lower_ci_2_5",
    "sharpe_median_50",
    "sharpe_upper_ci_97_5",
)


def load_active_signals(patterns: Sequence[str | Path]) -> list[LoadedSignal]:
    """Load active signal configs and their OOS return series."""
    paths = _expand_patterns(patterns)
    return [_load_config(path) for path in paths]


def _expand_patterns(patterns: Sequence[str | Path]) -> list[Path]:
    found: dict[Path, None] = {}
    for pattern in patterns:
        text = str(pattern)
        if glob.has_magic(text):
            matches = [Path(item) for item in glob.glob(text)]
        else:
            path = Path(text)
            matches = [path] if path.exists() else []
        for match in matches:
            if match.is_file():
                found[match] = None
    return sorted(found)


def _load_config(path: Path) -> LoadedSignal:
    config = json.loads(path.read_text(encoding="utf-8"))
    _validate_config(config, path)

    name = str(config.get("name") or path.stem)
    signal = str(config["signal"])
    phase = config.get("phase")
    source = _resolve_source_path(path, str(config["source_parquet"]))
    returns = _load_returns(source, signal=signal, phase=str(phase) if phase is not None else None)
    if returns.empty:
        raise ValueError(f"no OOS returns match signal={signal!r} in {source}")
    returns = returns.rename(name)

    lower = float(config["sharpe_lower_ci_2_5"])
    median = float(config["sharpe_median_50"])
    upper = float(config["sharpe_upper_ci_97_5"])
    return LoadedSignal(
        name=name,
        returns=returns,
        bayesian_ci=(lower, median, upper),
        sharpe_lower=lower,
        weight_max=float(config.get("portfolio_weight_max", config.get("weight_max", 0.0))),
        config_path=path,
        raw_config=config,
    )


def _validate_config(config: dict[str, Any], path: Path) -> None:
    missing = [key for key in REQUIRED_KEYS if key not in config]
    if "portfolio_weight_max" not in config and "weight_max" not in config:
        missing.append("portfolio_weight_max")
    if missing:
        raise ValueError(f"{path} missing required key(s): {', '.join(missing)}")


def _resolve_source_path(config_path: Path, raw_source: str) -> Path:
    source = Path(raw_source)
    if source.is_absolute():
        return source
    if source.exists():
        return source
    return config_path.parent / source


def _load_returns(path: Path, *, signal: str, phase: str | None) -> pd.Series:
    if not path.exists():
        raise ValueError(f"source parquet not found: {path}")
    frame = pd.read_parquet(path)
    if "return" not in frame.columns:
        raise ValueError(f"source parquet missing return column: {path}")

    mask = pd.Series(True, index=frame.index)
    if "signal" in frame.columns:
        mask &= frame["signal"].astype("string").eq(signal)
    if phase is not None and "phase" in frame.columns:
        mask &= frame["phase"].astype("string").eq(phase)
    selected = pd.to_numeric(frame.loc[mask, "return"], errors="coerce").dropna()
    if "entry_ts" in frame.columns:
        index = pd.to_datetime(frame.loc[selected.index, "entry_ts"], utc=True)
        selected.index = index
    return selected.astype("float64")
