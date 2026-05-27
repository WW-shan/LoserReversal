from __future__ import annotations

import math

import pandas as pd
import pytest


def _fill_row(
    time: str,
    *,
    px: float = 100.0,
    sz: float = 1.0,
    closed_pnl: float = 0.0,
    direction: str = "Open Long",
) -> dict[str, object]:
    return {
        "time": pd.Timestamp(time, tz="UTC"),
        "coin": "BTC",
        "side": "B",
        "dir": direction,
        "px": px,
        "sz": sz,
        "start_position": 0.0,
        "closed_pnl": closed_pnl,
        "fee": 0.0,
        "oid": 1,
        "tid": 1,
        "hash": "0x1",
        "crossed": False,
        "liquidation": False,
    }


def _fills_df(rows: list[dict[str, object]]) -> pd.DataFrame:
    if not rows:
        empty = pd.DataFrame(columns=list(_fill_row("2026-01-01T00:00:00Z").keys()))
        empty["time"] = pd.to_datetime(empty["time"], utc=True)
        return empty.set_index("time")
    frame = pd.DataFrame(rows)
    frame["time"] = pd.to_datetime(frame["time"], utc=True)
    return frame.set_index("time").sort_index()


def test_compute_wallet_metrics_empty_fills_returns_zero_counts() -> None:
    from wallet_pool.academic_pool import compute_wallet_metrics

    metrics = compute_wallet_metrics(_fills_df([]), account_value=5_000.0)

    assert metrics["account_value"] == 5_000.0
    assert metrics["n_trades_90d"] == 0
    assert metrics["realized_loss_rate_90d"] == 0.0
    assert metrics["leverage_avg_90d"] == 0.0
    assert metrics["size_cv_90d"] == 0.0


def test_compute_wallet_metrics_n_trades_counts_open_fills_in_window() -> None:
    from wallet_pool.academic_pool import compute_wallet_metrics

    fills = _fills_df(
        [
            _fill_row("2026-04-01T00:00:00Z", direction="Open Long"),
            _fill_row("2026-04-15T00:00:00Z", direction="Open Short"),
            _fill_row("2026-05-01T00:00:00Z", direction="Open Long"),
        ]
    )

    metrics = compute_wallet_metrics(
        fills,
        account_value=10_000.0,
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
    )

    assert metrics["n_trades_90d"] == 3


def test_compute_wallet_metrics_excludes_fills_older_than_90_days() -> None:
    from wallet_pool.academic_pool import compute_wallet_metrics

    fills = _fills_df(
        [
            _fill_row("2026-01-01T00:00:00Z", direction="Open Long"),  # > 90d old
            _fill_row("2026-04-01T00:00:00Z", direction="Open Long"),
            _fill_row("2026-05-15T00:00:00Z", direction="Open Short"),
        ]
    )

    metrics = compute_wallet_metrics(
        fills,
        account_value=10_000.0,
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
    )

    assert metrics["n_trades_90d"] == 2


def test_filter_window_excludes_future_fills_after_as_of() -> None:
    from wallet_pool.academic_pool import compute_wallet_metrics

    fills = _fills_df(
        [
            _fill_row("2026-01-01T00:00:00Z", direction="Open Long"),
            _fill_row("2026-04-01T00:00:00Z", direction="Open Long"),
            _fill_row("2026-05-15T00:00:00Z", direction="Open Short"),
            _fill_row("2026-06-15T00:00:00Z", direction="Open Long"),
        ]
    )

    metrics = compute_wallet_metrics(
        fills,
        account_value=10_000.0,
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
    )

    assert metrics["n_trades_90d"] == 2


def test_filter_window_excludes_fills_at_exactly_as_of() -> None:
    from wallet_pool.academic_pool import compute_wallet_metrics

    fills = _fills_df(
        [
            _fill_row("2026-05-25T23:59:59Z", direction="Open Long"),
            _fill_row("2026-05-26T00:00:00Z", direction="Open Long"),
        ]
    )

    metrics = compute_wallet_metrics(
        fills,
        account_value=10_000.0,
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
    )

    assert metrics["n_trades_90d"] == 1


def test_filter_window_finite_check_matches_legacy_corner_cases() -> None:
    from wallet_pool.academic_pool import _filter_window

    rows = [
        _fill_row("2026-05-25T00:00:00Z", px=100.0, sz=1.0),
        _fill_row("2026-05-25T01:00:00Z", px=float("nan"), sz=1.0),
        _fill_row("2026-05-25T02:00:00Z", px=float("inf"), sz=1.0),
        _fill_row("2026-05-25T03:00:00Z", px=100.0, sz=float("-inf")),
        _fill_row("2026-05-25T04:00:00Z", px="not-a-price", sz=1.0),
        _fill_row("2026-05-25T05:00:00Z", px=100.0, sz="not-a-size"),
        _fill_row("2026-05-25T06:00:00Z", px="101.5", sz="2.0"),
    ]
    for tid, row in enumerate(rows, start=1):
        row["tid"] = tid
    fills = _fills_df(rows)
    horizon = pd.Timestamp("2026-05-24T00:00:00Z")
    as_of = pd.Timestamp("2026-05-26T00:00:00Z")

    filtered = _filter_window(fills, horizon, as_of)

    legacy = fills.copy()
    legacy["px"] = pd.to_numeric(legacy["px"], errors="coerce")
    legacy["sz"] = pd.to_numeric(legacy["sz"], errors="coerce")
    legacy_mask = legacy[["px", "sz"]].apply(
        lambda col: col.map(
            lambda value: False if value is None else math.isfinite(float(value))
        )
    )
    expected = legacy.loc[legacy_mask.all(axis=1)]
    assert filtered["tid"].tolist() == expected["tid"].tolist()
    assert filtered["tid"].tolist() == [1, 7]


def test_compute_wallet_metrics_rejects_missing_required_fill_columns() -> None:
    from wallet_pool.academic_pool import compute_wallet_metrics

    fills = _fills_df([_fill_row("2026-04-01T00:00:00Z")]).drop(columns=["dir"])

    with pytest.raises(ValueError, match="fills missing required columns: \\['dir'\\]"):
        compute_wallet_metrics(
            fills,
            account_value=10_000.0,
            as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
        )


def test_compute_wallet_metrics_handles_time_as_column() -> None:
    from wallet_pool.academic_pool import compute_wallet_metrics

    fills = _fills_df(
        [
            _fill_row("2026-04-01T00:00:00Z", direction="Open Long", px=100.0, sz=50.0),
            _fill_row("2026-04-15T00:00:00Z", direction="Open Short", px=100.0, sz=100.0),
            _fill_row("2026-05-01T00:00:00Z", direction="Close Long", closed_pnl=-10.0),
            _fill_row("2026-05-02T00:00:00Z", direction="Close Long", closed_pnl=10.0),
        ]
    )
    indexed_metrics = compute_wallet_metrics(
        fills,
        account_value=1_000.0,
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
    )
    column_metrics = compute_wallet_metrics(
        fills.reset_index(),
        account_value=1_000.0,
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
    )

    assert column_metrics == indexed_metrics


def test_compute_wallet_metrics_realized_loss_rate_uses_close_fills() -> None:
    from wallet_pool.academic_pool import compute_wallet_metrics

    fills = _fills_df(
        [
            _fill_row("2026-04-01T00:00:00Z", direction="Close Long", closed_pnl=-50.0),
            _fill_row("2026-04-10T00:00:00Z", direction="Close Long", closed_pnl=-30.0),
            _fill_row("2026-04-20T00:00:00Z", direction="Close Short", closed_pnl=20.0),
            _fill_row("2026-05-01T00:00:00Z", direction="Close Long", closed_pnl=-10.0),
        ]
    )

    metrics = compute_wallet_metrics(
        fills,
        account_value=10_000.0,
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
    )

    # 3 losing close fills / 4 close fills = 0.75
    assert metrics["realized_loss_rate_90d"] == pytest.approx(0.75)


def test_compute_wallet_metrics_realized_loss_rate_zero_when_no_close_fills() -> None:
    from wallet_pool.academic_pool import compute_wallet_metrics

    fills = _fills_df(
        [
            _fill_row("2026-04-01T00:00:00Z", direction="Open Long", closed_pnl=0.0),
        ]
    )

    metrics = compute_wallet_metrics(
        fills,
        account_value=10_000.0,
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
    )

    assert metrics["realized_loss_rate_90d"] == 0.0


def test_compute_wallet_metrics_leverage_avg_uses_open_notional_over_account_value() -> None:
    from wallet_pool.academic_pool import compute_wallet_metrics

    # account_value = 1000, px*sz = 5000 → leverage 5x; px*sz = 10000 → 10x → avg 7.5x
    fills = _fills_df(
        [
            _fill_row("2026-04-01T00:00:00Z", direction="Open Long", px=100.0, sz=50.0),
            _fill_row("2026-04-15T00:00:00Z", direction="Open Short", px=100.0, sz=100.0),
        ]
    )

    metrics = compute_wallet_metrics(
        fills,
        account_value=1_000.0,
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
    )

    assert metrics["leverage_avg_90d"] == pytest.approx(7.5)


def test_compute_wallet_metrics_leverage_zero_when_account_value_non_positive() -> None:
    from wallet_pool.academic_pool import compute_wallet_metrics

    fills = _fills_df(
        [_fill_row("2026-04-01T00:00:00Z", direction="Open Long", px=100.0, sz=50.0)],
    )

    metrics = compute_wallet_metrics(
        fills,
        account_value=0.0,
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
    )

    assert metrics["leverage_avg_90d"] == 0.0


def test_compute_wallet_metrics_size_cv_is_std_over_mean_of_notional() -> None:
    from wallet_pool.academic_pool import compute_wallet_metrics

    # notionals: 1000, 5000, 10000 → mean = 5333.33, std (ddof=0) ≈ 3681.79 → CV ≈ 0.69
    fills = _fills_df(
        [
            _fill_row("2026-04-01T00:00:00Z", direction="Open Long", px=100.0, sz=10.0),
            _fill_row("2026-04-15T00:00:00Z", direction="Open Short", px=100.0, sz=50.0),
            _fill_row("2026-05-01T00:00:00Z", direction="Open Long", px=100.0, sz=100.0),
        ]
    )

    metrics = compute_wallet_metrics(
        fills,
        account_value=100_000.0,
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
    )

    assert metrics["size_cv_90d"] == pytest.approx(0.6902, abs=1e-3)


def test_compute_wallet_metrics_size_cv_zero_when_uniform_size() -> None:
    from wallet_pool.academic_pool import compute_wallet_metrics

    fills = _fills_df(
        [
            _fill_row("2026-04-01T00:00:00Z", direction="Open Long", px=100.0, sz=10.0),
            _fill_row("2026-04-15T00:00:00Z", direction="Open Short", px=100.0, sz=10.0),
            _fill_row("2026-05-01T00:00:00Z", direction="Open Long", px=100.0, sz=10.0),
        ]
    )

    metrics = compute_wallet_metrics(
        fills,
        account_value=100_000.0,
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
    )

    assert metrics["size_cv_90d"] == pytest.approx(0.0, abs=1e-9)


def test_compute_wallet_metrics_size_cv_uses_only_open_fills_within_window() -> None:
    from wallet_pool.academic_pool import compute_wallet_metrics

    fills = _fills_df(
        [
            _fill_row("2025-01-01T00:00:00Z", direction="Open Long", px=100.0, sz=999.0),  # OOO
            _fill_row("2026-04-01T00:00:00Z", direction="Open Long", px=100.0, sz=10.0),
            _fill_row("2026-04-15T00:00:00Z", direction="Close Long", px=100.0, sz=10.0),
            _fill_row("2026-05-01T00:00:00Z", direction="Open Short", px=100.0, sz=10.0),
        ]
    )

    metrics = compute_wallet_metrics(
        fills,
        account_value=100_000.0,
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
    )

    # Only two open fills within 90d, both notional=1000 → CV=0
    assert metrics["size_cv_90d"] == pytest.approx(0.0, abs=1e-9)
    assert metrics["n_trades_90d"] == 2


def test_is_academic_anti_alpha_accepts_canonical_passing_wallet() -> None:
    from wallet_pool.academic_pool import is_academic_anti_alpha

    metrics = {
        "account_value": 25_000.0,
        "realized_loss_rate_90d": 0.65,
        "leverage_avg_90d": 8.0,
        "n_trades_90d": 120,
        "size_cv_90d": 0.45,
    }

    assert is_academic_anti_alpha(metrics) is True


@pytest.mark.parametrize(
    "field",
    [
        "account_value",
        "realized_loss_rate_90d",
        "leverage_avg_90d",
        "n_trades_90d",
        "size_cv_90d",
    ],
)
def test_is_academic_anti_alpha_rejects_nan_metrics(field: str) -> None:
    from wallet_pool.academic_pool import is_academic_anti_alpha

    metrics = {
        "account_value": 25_000.0,
        "realized_loss_rate_90d": 0.65,
        "leverage_avg_90d": 8.0,
        "n_trades_90d": 120,
        "size_cv_90d": 0.45,
    }
    metrics[field] = float("nan")

    assert is_academic_anti_alpha(metrics) is False


def test_is_academic_anti_alpha_rejects_inf_n_trades() -> None:
    from wallet_pool.academic_pool import is_academic_anti_alpha

    metrics = {
        "account_value": 25_000.0,
        "realized_loss_rate_90d": 0.65,
        "leverage_avg_90d": 8.0,
        "n_trades_90d": float("inf"),
        "size_cv_90d": 0.45,
    }

    assert is_academic_anti_alpha(metrics) is False


def test_is_academic_anti_alpha_rejects_whales_above_account_band() -> None:
    from wallet_pool.academic_pool import is_academic_anti_alpha

    metrics = {
        "account_value": 250_000.0,
        "realized_loss_rate_90d": 0.65,
        "leverage_avg_90d": 8.0,
        "n_trades_90d": 120,
        "size_cv_90d": 0.45,
    }

    assert is_academic_anti_alpha(metrics) is False


def test_is_academic_anti_alpha_rejects_dust_accounts_below_band() -> None:
    from wallet_pool.academic_pool import is_academic_anti_alpha

    metrics = {
        "account_value": 500.0,
        "realized_loss_rate_90d": 0.65,
        "leverage_avg_90d": 8.0,
        "n_trades_90d": 120,
        "size_cv_90d": 0.45,
    }

    assert is_academic_anti_alpha(metrics) is False


def test_is_academic_anti_alpha_rejects_wallets_with_low_loss_rate() -> None:
    from wallet_pool.academic_pool import is_academic_anti_alpha

    metrics = {
        "account_value": 25_000.0,
        "realized_loss_rate_90d": 0.40,
        "leverage_avg_90d": 8.0,
        "n_trades_90d": 120,
        "size_cv_90d": 0.45,
    }

    assert is_academic_anti_alpha(metrics) is False


def test_is_academic_anti_alpha_rejects_low_leverage_wallets() -> None:
    from wallet_pool.academic_pool import is_academic_anti_alpha

    metrics = {
        "account_value": 25_000.0,
        "realized_loss_rate_90d": 0.65,
        "leverage_avg_90d": 3.0,
        "n_trades_90d": 120,
        "size_cv_90d": 0.45,
    }

    assert is_academic_anti_alpha(metrics) is False


def test_is_academic_anti_alpha_rejects_inactive_wallets() -> None:
    from wallet_pool.academic_pool import is_academic_anti_alpha

    metrics = {
        "account_value": 25_000.0,
        "realized_loss_rate_90d": 0.65,
        "leverage_avg_90d": 8.0,
        "n_trades_90d": 20,
        "size_cv_90d": 0.45,
    }

    assert is_academic_anti_alpha(metrics) is False


def test_is_academic_anti_alpha_rejects_market_maker_bots_with_uniform_size() -> None:
    from wallet_pool.academic_pool import is_academic_anti_alpha

    metrics = {
        "account_value": 25_000.0,
        "realized_loss_rate_90d": 0.65,
        "leverage_avg_90d": 8.0,
        "n_trades_90d": 200,
        "size_cv_90d": 0.10,
    }

    assert is_academic_anti_alpha(metrics) is False


def test_is_academic_anti_alpha_accepts_band_lower_boundaries() -> None:
    from wallet_pool.academic_pool import is_academic_anti_alpha

    # Exactly at every threshold should still be accepted (inclusive boundaries).
    metrics = {
        "account_value": 1_000.0,
        "realized_loss_rate_90d": 0.50,
        "leverage_avg_90d": 5.0,
        "n_trades_90d": 50,
        "size_cv_90d": 0.30,
    }

    assert is_academic_anti_alpha(metrics) is True


def test_is_academic_anti_alpha_accepts_account_value_upper_boundary() -> None:
    from wallet_pool.academic_pool import is_academic_anti_alpha

    metrics = {
        "account_value": 100_000.0,
        "realized_loss_rate_90d": 0.50,
        "leverage_avg_90d": 5.0,
        "n_trades_90d": 50,
        "size_cv_90d": 0.30,
    }

    assert is_academic_anti_alpha(metrics) is True
