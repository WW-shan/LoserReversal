from __future__ import annotations

import math

import pandas as pd
import pytest

from portfolio.composer import PortfolioComposer


def test_correlation_matrix_is_empty_without_signals() -> None:
    composer = PortfolioComposer()

    assert composer.correlation_matrix().empty
    assert composer.risk_parity_weights() == {}
    assert composer.mean_variance_weights() == {}
    assert composer.combined_metrics()["n_trades"] == 0


def test_single_signal_uses_weight_cap_and_raw_combined_stats() -> None:
    composer = PortfolioComposer()
    returns = pd.Series([0.10, -0.02, 0.04, 0.03], dtype="float64")

    composer.add_signal(
        "v1+D",
        returns,
        bayesian_ci={"lower": 0.5035, "median": 1.8812, "upper": 3.3224},
        sharpe_lower=0.5035,
        weight_max=0.10,
    )

    assert composer.correlation_matrix().loc["v1+D", "v1+D"] == 1.0
    assert composer.risk_parity_weights() == {"v1+D": 0.10}
    assert composer.mean_variance_weights() == {"v1+D": 0.10}
    metrics = composer.combined_metrics()
    assert metrics["n_trades"] == 4
    assert metrics["win_rate"] == 0.75
    assert metrics["max_dd"] == pytest.approx(-0.02)


def test_single_signal_target_vol_scales_down_high_volatility_signal() -> None:
    composer = PortfolioComposer()
    composer.add_signal("wild", [1.0, -1.0, 1.0, -1.0], (0.5, 1.0, 1.5), 0.5, 1.0)

    weights = composer.risk_parity_weights(target_vol=0.15)

    assert weights["wild"] < 1.0
    assert weights["wild"] == pytest.approx(0.15 / math.sqrt(14.4))


def test_uncorrelated_equal_vol_signals_get_equal_risk_parity_weights() -> None:
    composer = PortfolioComposer()
    composer.add_signal("a", [0.10, -0.10, 0.10, -0.10], (0.5, 1.0, 1.5), 0.5, 0.50)
    composer.add_signal("b", [0.10, 0.10, -0.10, -0.10], (0.5, 1.0, 1.5), 0.5, 0.50)

    corr = composer.correlation_matrix()
    weights = composer.risk_parity_weights(target_vol=1.0)

    assert corr.loc["a", "b"] == pytest.approx(0.0)
    assert weights["a"] == pytest.approx(weights["b"])
    assert weights["a"] == pytest.approx(0.50)


def test_risk_parity_respects_weight_caps() -> None:
    composer = PortfolioComposer()
    composer.add_signal("small", [0.03, -0.02, 0.03, -0.02], (0.4, 1.0, 1.5), 0.4, 0.10)
    composer.add_signal("large", [0.03, -0.02, 0.03, -0.02], (0.4, 1.0, 1.5), 0.4, 0.40)

    weights = composer.risk_parity_weights(target_vol=1.0)

    assert weights["small"] <= 0.10
    assert weights["large"] <= 0.40
    assert sum(weights.values()) == pytest.approx(0.50)


def test_risk_parity_handles_zero_volatility_signal() -> None:
    composer = PortfolioComposer()
    composer.add_signal("flat", [0.01, 0.01, 0.01, 0.01], (0.4, 1.0, 1.5), 0.4, 0.50)
    composer.add_signal("moving", [0.03, -0.01, 0.02, -0.02], (0.4, 1.0, 1.5), 0.4, 0.50)

    weights = composer.risk_parity_weights(target_vol=1.0)

    assert math.isfinite(weights["flat"])
    assert math.isfinite(weights["moving"])
    assert weights["flat"] == pytest.approx(0.50)
    assert weights["moving"] == pytest.approx(0.50)


def test_mean_variance_favors_higher_expected_return_for_same_risk() -> None:
    composer = PortfolioComposer()
    composer.add_signal("low", [0.01, -0.02, 0.03, -0.01], (0.4, 1.0, 1.5), 0.4, 0.50)
    composer.add_signal("high", [0.05, 0.02, 0.07, 0.03], (0.4, 1.0, 1.5), 0.4, 0.50)

    weights = composer.mean_variance_weights(target_vol=1.0)

    assert weights["high"] > weights["low"]
    assert weights["high"] <= 0.50


def test_mean_variance_falls_back_to_risk_parity_when_expected_returns_are_negative() -> None:
    composer = PortfolioComposer()
    composer.add_signal("a", [-0.03, -0.01, -0.02, -0.04], (0.4, 1.0, 1.5), 0.4, 0.50)
    composer.add_signal("b", [-0.02, -0.04, -0.01, -0.03], (0.4, 1.0, 1.5), 0.4, 0.50)

    assert composer.mean_variance_weights(target_vol=1.0) == composer.risk_parity_weights(
        target_vol=1.0
    )


def test_highly_correlated_signals_do_not_get_square_root_n_sharpe_lift() -> None:
    composer = PortfolioComposer()
    base = pd.Series([0.04, -0.02, 0.05, -0.01, 0.03, -0.02, 0.06, -0.01])
    near_clone = base * 0.92 + pd.Series([0.002, 0.001, -0.001, 0.0, 0.001, 0.0, -0.002, 0.0])
    composer.add_signal("base", base, (0.6, 1.0, 1.5), 0.6, 0.50)
    composer.add_signal("clone", near_clone, (0.6, 1.0, 1.5), 0.6, 0.50)

    corr = composer.correlation_matrix().loc["base", "clone"]
    combined = composer.combined_metrics(composer.risk_parity_weights(target_vol=1.0))
    signal_stats = composer.signal_stats()

    assert corr > 0.90
    assert combined["sharpe"] < max(row["sharpe"] for row in signal_stats.values()) * 1.10


def test_disjoint_timestamped_returns_do_not_use_positional_correlation_fallback() -> None:
    composer = PortfolioComposer()
    composer.add_signal(
        "left",
        pd.Series([0.10, 0.20], index=pd.to_datetime(["2026-01-01", "2026-01-02"], utc=True)),
        (0.5, 1.0, 1.5),
        0.5,
        0.50,
    )
    composer.add_signal(
        "right",
        pd.Series([0.10, 0.20], index=pd.to_datetime(["2026-02-01", "2026-02-02"], utc=True)),
        (0.5, 1.0, 1.5),
        0.5,
        0.50,
    )

    corr = composer.correlation_matrix()

    assert corr.loc["left", "right"] == 0.0


def test_kelly_sizing_uses_quarter_kelly_from_ci_lower_bound() -> None:
    composer = PortfolioComposer()
    composer.add_signal("v1+D", [0.10, -0.02, 0.04], (0.5035, 1.8812, 3.3224), 0.5035, 0.10)

    stats = composer.signal_stats()["v1+D"]
    annualized_vol = pd.Series([0.10, -0.02, 0.04], dtype="float64").std(ddof=0) * math.sqrt(14.4)

    assert stats["kelly_fraction"] == pytest.approx(0.5035 / annualized_vol * 0.25)
    assert stats["kelly_weight"] == pytest.approx(0.10)


def test_kelly_sizing_is_monotonic_in_ci_lower_bound_for_same_returns() -> None:
    low = PortfolioComposer()
    high = PortfolioComposer()
    returns = [0.08, -0.03, 0.06, -0.01]
    low.add_signal("low", returns, (0.5, 1.0, 1.5), 0.5, 10.0)
    high.add_signal("high", returns, (1.5, 2.0, 2.5), 1.5, 10.0)

    assert high.signal_stats()["high"]["kelly_fraction"] > low.signal_stats()["low"][
        "kelly_fraction"
    ]


def test_negative_ci_lower_bound_gets_zero_kelly_weight() -> None:
    composer = PortfolioComposer()
    composer.add_signal("bad", [0.01, -0.04, -0.02], (-0.2, 0.1, 0.6), -0.2, 0.10)

    stats = composer.signal_stats()["bad"]

    assert stats["kelly_fraction"] == 0.0
    assert stats["kelly_weight"] == 0.0


def test_add_signal_rejects_empty_returns() -> None:
    composer = PortfolioComposer()

    with pytest.raises(ValueError, match="at least one return"):
        composer.add_signal("empty", [], (0.0, 0.0, 0.0), 0.0, 0.10)


def test_add_signal_rejects_duplicate_name() -> None:
    composer = PortfolioComposer()
    composer.add_signal("dup", [0.01], (0.1, 0.2, 0.3), 0.1, 0.10)

    with pytest.raises(ValueError, match="duplicate signal"):
        composer.add_signal("dup", [0.02], (0.1, 0.2, 0.3), 0.1, 0.10)
