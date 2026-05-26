"""Risk-aware portfolio composition for active strategy signals."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from infra.backtest.risk import max_drawdown


DEFAULT_TRADES_PER_YEAR = 14.4
DEFAULT_FRACTIONAL_KELLY = 0.25


@dataclass(frozen=True)
class SignalInput:
    name: str
    returns: pd.Series
    bayesian_ci: tuple[float, float, float]
    sharpe_lower: float
    weight_max: float


class PortfolioComposer:
    """Compose active signals with capped risk-parity or mean-variance weights."""

    def __init__(
        self,
        *,
        trades_per_year: float = DEFAULT_TRADES_PER_YEAR,
        fractional_kelly: float = DEFAULT_FRACTIONAL_KELLY,
    ) -> None:
        if trades_per_year <= 0:
            raise ValueError("trades_per_year must be positive")
        if fractional_kelly < 0:
            raise ValueError("fractional_kelly must be non-negative")
        self.trades_per_year = float(trades_per_year)
        self.fractional_kelly = float(fractional_kelly)
        self._signals: dict[str, SignalInput] = {}

    def add_signal(
        self,
        name: str,
        oos_returns: Iterable[float] | pd.Series,
        bayesian_ci: Mapping[str, float] | tuple[float, float, float],
        sharpe_lower: float,
        weight_max: float,
    ) -> None:
        """Register one active signal and its OOS trade returns."""
        if name in self._signals:
            raise ValueError(f"duplicate signal name: {name}")
        if not name:
            raise ValueError("signal name must be non-empty")
        if weight_max < 0:
            raise ValueError("weight_max must be non-negative")

        returns = self._coerce_returns(oos_returns)
        if returns.empty:
            raise ValueError("signal must contain at least one return")

        self._signals[name] = SignalInput(
            name=name,
            returns=returns,
            bayesian_ci=self._coerce_ci(bayesian_ci),
            sharpe_lower=float(sharpe_lower),
            weight_max=float(weight_max),
        )

    def correlation_matrix(self) -> pd.DataFrame:
        """Return the pairwise OOS return correlation matrix."""
        names = list(self._signals)
        if not names:
            return pd.DataFrame(dtype="float64")

        matrix = pd.DataFrame(np.eye(len(names)), index=names, columns=names, dtype="float64")
        for i, left_name in enumerate(names):
            for right_name in names[i + 1 :]:
                corr = _pairwise_correlation(
                    self._signals[left_name].returns,
                    self._signals[right_name].returns,
                )
                matrix.loc[left_name, right_name] = corr
                matrix.loc[right_name, left_name] = corr
        return matrix

    def risk_parity_weights(self, target_vol: float = 0.15) -> dict[str, float]:
        """Return capped inverse-volatility risk-parity weights."""
        self._validate_target_vol(target_vol)
        names = list(self._signals)
        if not names:
            return {}
        if len(names) == 1:
            signal = self._signals[names[0]]
            return {signal.name: signal.weight_max}

        vols = np.array([_std_or_nan(self._signals[name].returns) for name in names])
        positive_vols = vols[np.isfinite(vols) & (vols > 0.0)]
        fallback_vol = float(np.median(positive_vols)) if positive_vols.size else 1.0
        safe_vols = np.where(np.isfinite(vols) & (vols > 0.0), vols, fallback_vol)
        raw = 1.0 / safe_vols
        proportions = raw / raw.sum()
        weights = self._cap_and_scale(names, proportions, target_vol)
        return weights

    def mean_variance_weights(self, target_vol: float = 0.15) -> dict[str, float]:
        """Return long-only capped mean-variance weights."""
        self._validate_target_vol(target_vol)
        names = list(self._signals)
        if not names:
            return {}
        if len(names) == 1:
            signal = self._signals[names[0]]
            return {signal.name: signal.weight_max}

        frame = self._returns_frame(names)
        means = frame.mean().to_numpy(dtype="float64")
        if not np.any(means > 0.0):
            return self.risk_parity_weights(target_vol=target_vol)

        cov = frame.cov(ddof=0).to_numpy(dtype="float64")
        cov = np.nan_to_num(cov, nan=0.0, posinf=0.0, neginf=0.0)
        ridge = max(float(np.trace(cov)) / max(len(names), 1), 1e-8) * 1e-6
        try:
            raw = np.linalg.pinv(cov + np.eye(len(names)) * ridge) @ means
        except np.linalg.LinAlgError:
            return self.risk_parity_weights(target_vol=target_vol)

        raw = np.clip(raw, a_min=0.0, a_max=None)
        if not np.any(raw > 0.0):
            return self.risk_parity_weights(target_vol=target_vol)

        proportions = raw / raw.sum()
        return self._clip_and_scale(names, proportions, target_vol)

    def combined_metrics(self, weights: Mapping[str, float] | None = None) -> dict[str, float | int]:
        """Return combined Sharpe, MaxDD, trade count, and win rate."""
        names = list(self._signals)
        if not names:
            return {"sharpe": 0.0, "max_dd": 0.0, "n_trades": 0, "win_rate": 0.0}

        if len(names) == 1:
            combined = self._signals[names[0]].returns
        else:
            active_weights = dict(weights or self.risk_parity_weights())
            frame = self._returns_frame(names)
            weight_vector = np.array(
                [float(active_weights.get(name, 0.0)) for name in names],
                dtype="float64",
            )
            combined = pd.Series(
                frame.to_numpy(dtype="float64") @ weight_vector,
                index=frame.index,
                dtype="float64",
            )

        return {
            "sharpe": _annualized_sharpe(combined, self.trades_per_year),
            "max_dd": _returns_max_drawdown(combined),
            "n_trades": int(sum(len(signal.returns) for signal in self._signals.values())),
            "win_rate": _win_rate(combined),
        }

    def signal_stats(self) -> dict[str, dict[str, float | int]]:
        """Return per-signal stats plus Kelly sizing metadata."""
        rows: dict[str, dict[str, float | int]] = {}
        for name, signal in self._signals.items():
            lower, median, upper = signal.bayesian_ci
            kelly_fraction = self._kelly_fraction(lower)
            rows[name] = {
                "n_trades": int(signal.returns.size),
                "win_rate": _win_rate(signal.returns),
                "sharpe": _annualized_sharpe(signal.returns, self.trades_per_year),
                "max_dd": _returns_max_drawdown(signal.returns),
                "avg_return": float(signal.returns.mean()),
                "volatility": float(signal.returns.std(ddof=0)),
                "weight_max": float(signal.weight_max),
                "sharpe_lower": float(signal.sharpe_lower),
                "ci_lower": float(lower),
                "ci_median": float(median),
                "ci_upper": float(upper),
                "kelly_fraction": float(kelly_fraction),
                "kelly_weight": float(min(signal.weight_max, kelly_fraction)),
            }
        return rows

    def weights_frame(self, weights: Mapping[str, float]) -> pd.DataFrame:
        """Return one row per signal for parquet/report output."""
        stats = self.signal_stats()
        rows: list[dict[str, Any]] = []
        for name, row in stats.items():
            rows.append({"signal": name, "weight": float(weights.get(name, 0.0)), **row})
        return pd.DataFrame(rows)

    def _cap_and_scale(
        self,
        names: list[str],
        proportions: np.ndarray,
        target_vol: float,
    ) -> dict[str, float]:
        caps = np.array([self._signals[name].weight_max for name in names], dtype="float64")
        target_total = min(float(caps.sum()), 1.0)
        weights = _allocate_with_caps(proportions, caps, target_total)
        scaled = self._scale_to_target_vol(names, weights, target_vol)
        return {name: float(weight) for name, weight in zip(names, scaled, strict=True)}

    def _clip_and_scale(
        self,
        names: list[str],
        proportions: np.ndarray,
        target_vol: float,
    ) -> dict[str, float]:
        caps = np.array([self._signals[name].weight_max for name in names], dtype="float64")
        target_total = min(float(caps.sum()), 1.0)
        weights = np.minimum(proportions * target_total, caps)
        scaled = self._scale_to_target_vol(names, weights, target_vol)
        return {name: float(weight) for name, weight in zip(names, scaled, strict=True)}

    def _scale_to_target_vol(
        self,
        names: list[str],
        weights: np.ndarray,
        target_vol: float,
    ) -> np.ndarray:
        if not np.any(weights > 0.0):
            return weights
        frame = self._returns_frame(names)
        portfolio_returns = frame.to_numpy(dtype="float64") @ weights
        annualized_vol = _annualized_volatility(
            pd.Series(portfolio_returns, index=frame.index, dtype="float64"),
            self.trades_per_year,
        )
        if annualized_vol <= 0.0 or not math.isfinite(annualized_vol):
            return weights
        scale = min(1.0, target_vol / annualized_vol)
        return weights * scale

    def _returns_frame(self, names: list[str]) -> pd.DataFrame:
        series = [self._signals[name].returns.rename(name) for name in names]
        frame = pd.concat(series, axis=1).fillna(0.0)
        if frame.empty:
            max_len = max(len(item) for item in series)
            frame = pd.DataFrame(
                {
                    name: self._signals[name].returns.reset_index(drop=True).reindex(
                        range(max_len), fill_value=0.0
                    )
                    for name in names
                },
                dtype="float64",
            )
        return frame.astype("float64")

    def _kelly_fraction(self, sharpe_lower: float) -> float:
        if sharpe_lower <= 0.0:
            return 0.0
        full_kelly = sharpe_lower / (1.0 + sharpe_lower**2)
        return float(full_kelly * self.fractional_kelly)

    @staticmethod
    def _coerce_returns(oos_returns: Iterable[float] | pd.Series) -> pd.Series:
        if isinstance(oos_returns, pd.Series):
            values = oos_returns.copy()
        else:
            values = pd.Series(list(oos_returns), dtype="float64")
        numeric = pd.to_numeric(values, errors="coerce").dropna().astype("float64")
        return numeric

    @staticmethod
    def _coerce_ci(
        bayesian_ci: Mapping[str, float] | tuple[float, float, float],
    ) -> tuple[float, float, float]:
        if isinstance(bayesian_ci, Mapping):
            lower = _mapping_value(bayesian_ci, ("lower", "lower_2_5", "sharpe_lower_ci_2_5"))
            median = _mapping_value(bayesian_ci, ("median", "median_50", "sharpe_median_50"))
            upper = _mapping_value(bayesian_ci, ("upper", "upper_97_5", "sharpe_upper_ci_97_5"))
            return (float(lower), float(median), float(upper))
        if len(bayesian_ci) != 3:
            raise ValueError("bayesian_ci tuple must contain lower, median, upper")
        lower, median, upper = bayesian_ci
        return (float(lower), float(median), float(upper))

    @staticmethod
    def _validate_target_vol(target_vol: float) -> None:
        if target_vol <= 0:
            raise ValueError("target_vol must be positive")


def _mapping_value(values: Mapping[str, float], keys: tuple[str, ...]) -> float:
    for key in keys:
        if key in values:
            return float(values[key])
    raise ValueError(f"bayesian_ci missing one of keys: {keys}")


def _allocate_with_caps(proportions: np.ndarray, caps: np.ndarray, target_total: float) -> np.ndarray:
    weights = np.zeros_like(proportions, dtype="float64")
    remaining = np.arange(proportions.size)
    remaining_total = target_total

    while remaining.size and remaining_total > 0.0:
        remaining_props = proportions[remaining]
        prop_sum = float(remaining_props.sum())
        if prop_sum <= 0.0:
            raw = np.full(remaining.size, remaining_total / remaining.size)
        else:
            raw = remaining_total * remaining_props / prop_sum
        cap_mask = raw >= caps[remaining]
        if not np.any(cap_mask):
            weights[remaining] = raw
            break

        capped_indices = remaining[cap_mask]
        weights[capped_indices] = caps[capped_indices]
        remaining_total -= float(caps[capped_indices].sum())
        remaining = remaining[~cap_mask]

    return np.minimum(weights, caps)


def _pairwise_correlation(left: pd.Series, right: pd.Series) -> float:
    aligned = pd.concat([left, right], axis=1, join="inner").dropna()
    if len(aligned) < 2:
        min_len = min(len(left), len(right))
        if min_len < 2:
            return 0.0
        aligned = pd.DataFrame(
            {
                "left": left.reset_index(drop=True).iloc[:min_len],
                "right": right.reset_index(drop=True).iloc[:min_len],
            },
            dtype="float64",
        )
    corr = aligned.iloc[:, 0].corr(aligned.iloc[:, 1])
    if pd.isna(corr):
        return 0.0
    return float(corr)


def _annualized_sharpe(returns: pd.Series, periods_per_year: float) -> float:
    clean = returns.astype("float64").dropna()
    if clean.empty:
        return 0.0
    std = float(clean.std(ddof=0))
    mean = float(clean.mean())
    if std == 0.0:
        if mean > 0.0:
            return float("inf")
        if mean < 0.0:
            return float("-inf")
        return 0.0
    return float(mean / std * math.sqrt(periods_per_year))


def _annualized_volatility(returns: pd.Series, periods_per_year: float) -> float:
    clean = returns.astype("float64").dropna()
    if clean.empty:
        return 0.0
    return float(clean.std(ddof=0) * math.sqrt(periods_per_year))


def _returns_max_drawdown(returns: pd.Series) -> float:
    clean = returns.astype("float64").dropna()
    if clean.empty:
        return 0.0
    equity = (1.0 + clean).cumprod()
    return max_drawdown(equity)


def _win_rate(returns: pd.Series) -> float:
    clean = returns.astype("float64").dropna()
    if clean.empty:
        return 0.0
    return float((clean > 0.0).mean())


def _std_or_nan(values: pd.Series) -> float:
    return float(values.astype("float64").std(ddof=0))
