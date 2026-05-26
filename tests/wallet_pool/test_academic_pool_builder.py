from __future__ import annotations

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


def _retail_open_close_fills(account_value: float, n_open: int = 60) -> pd.DataFrame:
    """Build a fills frame that satisfies all 5 academic thresholds."""

    base = pd.Timestamp("2026-04-01T00:00:00Z")
    rows: list[dict[str, object]] = []
    # 60 open fills with varied notional → high size_cv, leverage 5-15x.
    leverage_targets = [account_value * 5, account_value * 10, account_value * 15]
    for i in range(n_open):
        notional = leverage_targets[i % 3]
        rows.append(
            _fill_row(
                (base + pd.Timedelta(hours=i)).isoformat(),
                px=100.0,
                sz=notional / 100.0,
                direction="Open Long" if i % 2 == 0 else "Open Short",
            )
        )
    # 10 close fills, 6 losing (60% loss rate) ≥ 50% threshold.
    for i in range(10):
        rows.append(
            _fill_row(
                (base + pd.Timedelta(days=2, hours=i)).isoformat(),
                px=100.0,
                sz=1.0,
                closed_pnl=-100.0 if i < 6 else 100.0,
                direction="Close Long",
            )
        )
    return _fills_df(rows)


def _leaderboard_row(eth_address: str, account_value: float) -> dict[str, object]:
    return {
        "eth_address": eth_address,
        "account_value": account_value,
        "display_name": eth_address,
        "pnl_day": 0.0,
        "pnl_week": 0.0,
        "pnl_month": 0.0,
        "pnl_alltime": 0.0,
        "vlm_day": 0.0,
        "vlm_week": 0.0,
        "vlm_month": 0.0,
        "vlm_alltime": 0.0,
        "roi_day": 0.0,
        "roi_week": 0.0,
        "roi_month": 0.0,
        "roi_alltime": 0.0,
    }


def test_build_academic_pool_keeps_only_qualifying_wallets() -> None:
    from wallet_pool.academic_pool import build_academic_pool

    leaderboard = pd.DataFrame(
        [
            _leaderboard_row("0xpass", account_value=25_000.0),
            _leaderboard_row("0xfail_value", account_value=500.0),
        ]
    )
    fills_by_wallet = {
        "0xpass": _retail_open_close_fills(25_000.0),
        "0xfail_value": _retail_open_close_fills(500.0),
    }

    pool = build_academic_pool(
        leaderboard,
        fills_by_wallet,
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
    )

    assert pool["wallet"].tolist() == ["0xpass"]
    assert pool["account_value"].iloc[0] == pytest.approx(25_000.0)


def test_build_academic_pool_excludes_whales_above_account_band() -> None:
    from wallet_pool.academic_pool import build_academic_pool

    leaderboard = pd.DataFrame(
        [_leaderboard_row("0xwhale", account_value=500_000.0)]
    )
    fills_by_wallet = {"0xwhale": _retail_open_close_fills(500_000.0)}

    pool = build_academic_pool(
        leaderboard,
        fills_by_wallet,
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
    )

    assert pool.empty


def test_build_academic_pool_excludes_market_maker_bots_with_uniform_size() -> None:
    from wallet_pool.academic_pool import build_academic_pool

    leaderboard = pd.DataFrame([_leaderboard_row("0xbot", account_value=20_000.0)])
    # Bot: 80 open fills all uniform size, 10 losing closes → size_cv near 0.
    base = pd.Timestamp("2026-04-01T00:00:00Z")
    rows: list[dict[str, object]] = []
    for i in range(80):
        rows.append(
            _fill_row(
                (base + pd.Timedelta(minutes=i)).isoformat(),
                px=100.0,
                sz=1_000.0,  # uniform notional 100k → 5x leverage, CV=0
                direction="Open Long" if i % 2 == 0 else "Open Short",
            )
        )
    for i in range(10):
        rows.append(
            _fill_row(
                (base + pd.Timedelta(days=1, hours=i)).isoformat(),
                px=100.0,
                sz=1_000.0,
                closed_pnl=-50.0,
                direction="Close Long",
            )
        )
    fills_by_wallet = {"0xbot": _fills_df(rows)}

    pool = build_academic_pool(
        leaderboard,
        fills_by_wallet,
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
    )

    assert pool.empty


def test_build_academic_pool_omits_wallets_with_no_fill_history() -> None:
    from wallet_pool.academic_pool import build_academic_pool

    leaderboard = pd.DataFrame([_leaderboard_row("0xidle", account_value=25_000.0)])
    fills_by_wallet = {"0xidle": _fills_df([])}

    pool = build_academic_pool(
        leaderboard,
        fills_by_wallet,
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
    )

    assert pool.empty


def test_build_academic_pool_omits_wallets_missing_from_fills_dict() -> None:
    from wallet_pool.academic_pool import build_academic_pool

    leaderboard = pd.DataFrame(
        [
            _leaderboard_row("0xpass", account_value=25_000.0),
            _leaderboard_row("0xmissing", account_value=25_000.0),
        ]
    )
    fills_by_wallet = {"0xpass": _retail_open_close_fills(25_000.0)}

    pool = build_academic_pool(
        leaderboard,
        fills_by_wallet,
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
    )

    assert pool["wallet"].tolist() == ["0xpass"]


def test_build_academic_pool_emits_required_columns_in_expected_order() -> None:
    from wallet_pool.academic_pool import POOL_COLUMNS, build_academic_pool

    leaderboard = pd.DataFrame([_leaderboard_row("0xpass", account_value=25_000.0)])
    fills_by_wallet = {"0xpass": _retail_open_close_fills(25_000.0)}

    pool = build_academic_pool(
        leaderboard,
        fills_by_wallet,
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
    )

    assert list(pool.columns) == POOL_COLUMNS
    eligible_at = pool["eligible_at"].iloc[0]
    assert eligible_at.tzinfo is not None
    assert eligible_at == pd.Timestamp("2026-05-26T00:00:00Z")


def test_build_academic_pool_returns_empty_frame_with_columns_when_no_passers() -> None:
    from wallet_pool.academic_pool import POOL_COLUMNS, build_academic_pool

    leaderboard = pd.DataFrame([_leaderboard_row("0xfail", account_value=200.0)])
    fills_by_wallet = {"0xfail": _retail_open_close_fills(200.0)}

    pool = build_academic_pool(
        leaderboard,
        fills_by_wallet,
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
    )

    assert pool.empty
    assert list(pool.columns) == POOL_COLUMNS


def test_build_academic_pool_lowercases_wallet_addresses() -> None:
    from wallet_pool.academic_pool import build_academic_pool

    leaderboard = pd.DataFrame([_leaderboard_row("0xMiXeDcAsE", account_value=25_000.0)])
    fills_by_wallet = {"0xmixedcase": _retail_open_close_fills(25_000.0)}

    pool = build_academic_pool(
        leaderboard,
        fills_by_wallet,
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
    )

    assert pool["wallet"].tolist() == ["0xmixedcase"]


def test_build_academic_pool_handles_empty_leaderboard() -> None:
    from wallet_pool.academic_pool import POOL_COLUMNS, build_academic_pool

    leaderboard = pd.DataFrame(
        columns=["eth_address", "account_value"], dtype="float64"
    )

    pool = build_academic_pool(
        leaderboard,
        fills_by_wallet={},
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
    )

    assert pool.empty
    assert list(pool.columns) == POOL_COLUMNS


def test_build_academic_pool_skips_wallets_with_non_positive_account_value() -> None:
    from wallet_pool.academic_pool import build_academic_pool

    leaderboard = pd.DataFrame(
        [
            _leaderboard_row("0xzero", account_value=0.0),
            _leaderboard_row("0xnegative", account_value=-100.0),
            _leaderboard_row("0xpass", account_value=25_000.0),
        ]
    )
    fills_by_wallet = {
        "0xzero": _retail_open_close_fills(25_000.0),
        "0xnegative": _retail_open_close_fills(25_000.0),
        "0xpass": _retail_open_close_fills(25_000.0),
    }

    pool = build_academic_pool(
        leaderboard,
        fills_by_wallet,
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
    )

    assert pool["wallet"].tolist() == ["0xpass"]


def test_build_academic_pool_funnel_records_per_axis_attrition() -> None:
    from wallet_pool.academic_pool import build_academic_pool_with_funnel

    leaderboard = pd.DataFrame(
        [
            _leaderboard_row("0xpass", account_value=25_000.0),
            _leaderboard_row("0xfail_value", account_value=500.0),
            _leaderboard_row("0xfail_value_high", account_value=500_000.0),
        ]
    )
    fills_by_wallet = {
        "0xpass": _retail_open_close_fills(25_000.0),
        "0xfail_value": _retail_open_close_fills(500.0),
        "0xfail_value_high": _retail_open_close_fills(500_000.0),
    }

    pool, funnel = build_academic_pool_with_funnel(
        leaderboard,
        fills_by_wallet,
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
    )

    assert pool["wallet"].tolist() == ["0xpass"]
    assert funnel["leaderboard"] == 3
    assert funnel["account_value"] == 1
    assert funnel["realized_loss_rate"] == 1
    assert funnel["leverage"] == 1
    assert funnel["n_trades"] == 1
    assert funnel["size_cv"] == 1
    assert funnel["final"] == 1
