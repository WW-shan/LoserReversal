from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import requests


VALID_WALLET = "0x" + "a" * 40
VALID_WALLET_ALT = "0x" + "b" * 40


@pytest.fixture(autouse=True)
def _redirect_cache_dir(monkeypatch, tmp_path: Path) -> None:
    import scripts.build_academic_wallet_pool as builder

    monkeypatch.setattr(builder, "CACHE_DIR", tmp_path / "cache", raising=False)


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


def _retail_open_close_fills(account_value: float, n_open: int = 60) -> pd.DataFrame:
    base = pd.Timestamp("2026-04-01T00:00:00Z")
    rows: list[dict[str, object]] = []
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
    frame = pd.DataFrame(rows)
    frame["time"] = pd.to_datetime(frame["time"], utc=True)
    return frame.set_index("time").sort_index()


def _leaderboard_frame(rows: list[tuple[str, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "eth_address": addr,
                "account_value": account_value,
                "display_name": addr,
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
            for addr, account_value in rows
        ]
    )


def _academic_pool_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "wallet": VALID_WALLET,
                "account_value": 25_000.0,
                "realized_loss_rate_90d": 0.65,
                "leverage_avg_90d": 8.0,
                "n_trades_90d": 60,
                "size_cv_90d": 0.45,
                "eligible_at": pd.Timestamp("2026-05-26T00:00:00Z"),
            }
        ]
    )


def test_cli_runs_end_to_end_with_mocked_fetchers(mocker, tmp_path: Path) -> None:
    import scripts.build_academic_wallet_pool as builder

    leaderboard = _leaderboard_frame(
        [
            ("0xpass", 25_000.0),
            ("0xwhale", 500_000.0),
        ]
    )
    mocker.patch.object(builder, "fetch_leaderboard", return_value=leaderboard)

    def _fake_fetch(address: str, start, end):
        if address.lower() == "0xpass":
            return _retail_open_close_fills(25_000.0)
        return _retail_open_close_fills(500_000.0)

    mocker.patch.object(builder, "fetch_user_fills", side_effect=_fake_fetch)

    out_path = tmp_path / "academic_wallet_pool.parquet"
    result = builder.build_academic_wallet_pool(
        out=out_path,
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
        throttle_ms=0,
    )

    assert out_path.exists()
    written = pd.read_parquet(out_path)
    assert written["wallet"].tolist() == ["0xpass"]
    assert result["written_count"] == 1
    assert result["funnel"]["leaderboard"] == 1
    assert result["funnel"]["final"] == 1


def test_cli_honours_top_n_limit(mocker, tmp_path: Path) -> None:
    import scripts.build_academic_wallet_pool as builder

    leaderboard = _leaderboard_frame(
        [
            ("0xa", 25_000.0),
            ("0xb", 25_000.0),
            ("0xc", 25_000.0),
        ]
    )
    mocker.patch.object(builder, "fetch_leaderboard", return_value=leaderboard)
    fetched_addresses: list[str] = []

    def _fake_fetch(address: str, start, end):
        fetched_addresses.append(address)
        return _retail_open_close_fills(25_000.0)

    mocker.patch.object(builder, "fetch_user_fills", side_effect=_fake_fetch)

    result = builder.build_academic_wallet_pool(
        out=tmp_path / "pool.parquet",
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
        top_n=2,
        throttle_ms=0,
    )

    assert len(fetched_addresses) == 2
    assert result["funnel"]["leaderboard"] == 2


def test_build_academic_wallet_pool_dedupes_addresses_before_top_n(
    mocker,
    tmp_path: Path,
) -> None:
    import scripts.build_academic_wallet_pool as builder

    leaderboard = _leaderboard_frame(
        [
            ("0xAbc", 25_000.0),
            ("0xABC", 25_000.0),
            ("0xdef ", 25_000.0),
        ]
    )
    mocker.patch.object(builder, "fetch_leaderboard", return_value=leaderboard)
    fetched_addresses: list[str] = []

    def _fake_fetch(address: str, start, end):
        fetched_addresses.append(address)
        return _retail_open_close_fills(25_000.0)

    mocker.patch.object(builder, "fetch_user_fills", side_effect=_fake_fetch)

    result = builder.build_academic_wallet_pool(
        out=tmp_path / "pool.parquet",
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
        top_n=2,
        throttle_ms=0,
    )

    assert fetched_addresses == ["0xabc", "0xdef"]
    assert result["funnel"]["leaderboard"] == 2


def test_build_academic_wallet_pool_skips_missing_addresses_before_fetch(
    mocker,
    tmp_path: Path,
) -> None:
    import scripts.build_academic_wallet_pool as builder

    leaderboard = _leaderboard_frame(
        [
            ("0xmissing", 25_000.0),
            ("0xpass", 25_000.0),
        ]
    )
    leaderboard.loc[0, "eth_address"] = None
    mocker.patch.object(builder, "fetch_leaderboard", return_value=leaderboard)
    fetched_addresses: list[str] = []

    def _fake_fetch(address: str, start, end):
        fetched_addresses.append(address)
        return _retail_open_close_fills(25_000.0)

    mocker.patch.object(builder, "fetch_user_fills", side_effect=_fake_fetch)

    result = builder.build_academic_wallet_pool(
        out=tmp_path / "pool.parquet",
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
        top_n=10,
        throttle_ms=0,
    )

    assert fetched_addresses == ["0xpass"]
    assert result["funnel"]["valid_address"] == 1
    assert result["written_count"] == 1


def test_build_academic_pool_pre_filters_leaderboard_to_account_band(
    mocker,
    tmp_path: Path,
) -> None:
    import scripts.build_academic_wallet_pool as builder

    leaderboard = _leaderboard_frame(
        [
            ("0xdust", 500.0),
            ("0xretail_a", 25_000.0),
            ("0xretail_b", 50_000.0),
            ("0xlarge", 200_000.0),
            ("0xwhale", 5_000_000.0),
        ]
    )
    mocker.patch.object(builder, "fetch_leaderboard", return_value=leaderboard)
    fetched_addresses: list[str] = []

    def _fake_fetch(address: str, start, end):
        fetched_addresses.append(address)
        return _retail_open_close_fills(25_000.0)

    mocker.patch.object(builder, "fetch_user_fills", side_effect=_fake_fetch)

    result = builder.build_academic_wallet_pool(
        out=tmp_path / "pool.parquet",
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
        top_n=10,
        throttle_ms=0,
    )

    assert fetched_addresses == ["0xretail_a", "0xretail_b"]
    assert result["funnel"]["leaderboard"] == 2


def test_build_academic_pool_reports_script_level_pre_filter_funnel_axes(
    mocker,
    tmp_path: Path,
) -> None:
    import scripts.build_academic_wallet_pool as builder

    leaderboard = _leaderboard_frame(
        [
            ("0xdust", 500.0),
            ("0xnan", float("nan")),
            ("0xinf", float("inf")),
            ("0xretail", 25_000.0),
            ("0xwhale", 500_000.0),
        ]
    )
    mocker.patch.object(builder, "fetch_leaderboard", return_value=leaderboard)
    mocker.patch.object(
        builder,
        "fetch_user_fills",
        return_value=_retail_open_close_fills(25_000.0),
    )

    result = builder.build_academic_wallet_pool(
        out=tmp_path / "pool.parquet",
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
        top_n=10,
        throttle_ms=0,
    )

    assert result["funnel"]["leaderboard_pre_filter"] == 5
    assert result["funnel"]["pre_filtered_band"] == 1
    assert result["funnel"]["leaderboard"] == 1


def test_default_top_n_is_2000() -> None:
    import scripts.build_academic_wallet_pool as builder

    assert builder.DEFAULT_TOP_N == 2000


def test_cache_path_uses_minute_precision() -> None:
    import scripts.build_academic_wallet_pool as builder

    first = builder._cache_path(
        VALID_WALLET,
        pd.Timestamp("2026-05-26T00:00:00Z").to_pydatetime(),
        pd.Timestamp("2026-05-26T12:00:00Z").to_pydatetime(),
    )
    second = builder._cache_path(
        VALID_WALLET,
        pd.Timestamp("2026-05-26T00:01:00Z").to_pydatetime(),
        pd.Timestamp("2026-05-26T12:01:00Z").to_pydatetime(),
    )

    assert first is not None
    assert second is not None
    assert first != second
    assert "20260526T1200" in first.name
    assert "20260526T1201" in second.name


def test_cache_path_rejects_malformed_wallet() -> None:
    import scripts.build_academic_wallet_pool as builder

    lookback_start = pd.Timestamp("2026-05-26T00:00:00Z").to_pydatetime()
    lookback_end = pd.Timestamp("2026-05-26T12:00:00Z").to_pydatetime()

    assert builder._cache_path("../etc/passwd", lookback_start, lookback_end) is None
    assert builder._cache_path("0xAbc/../../etc", lookback_start, lookback_end) is None

    valid_path = builder._cache_path(VALID_WALLET, lookback_start, lookback_end)

    assert valid_path is not None
    assert valid_path.parent == builder.CACHE_DIR


def test_cache_path_rejects_trailing_newline_wallet() -> None:
    import scripts.build_academic_wallet_pool as builder

    lookback_start = pd.Timestamp("2026-05-26T00:00:00Z").to_pydatetime()
    lookback_end = pd.Timestamp("2026-05-26T12:00:00Z").to_pydatetime()

    assert builder._cache_path(f"{VALID_WALLET}\n", lookback_start, lookback_end) is None


def test_write_pool_writes_final_without_leftover_partial(tmp_path: Path) -> None:
    import scripts.build_academic_wallet_pool as builder

    out_path = tmp_path / "academic_wallet_pool.parquet"

    builder._write_pool(_academic_pool_frame(), out_path)

    assert out_path.exists()
    assert not out_path.with_suffix(out_path.suffix + ".partial").exists()
    assert pd.read_parquet(out_path)["wallet"].tolist() == [VALID_WALLET]


def test_write_pool_failure_removes_partial_and_leaves_no_final(
    mocker,
    tmp_path: Path,
) -> None:
    import scripts.build_academic_wallet_pool as builder

    out_path = tmp_path / "academic_wallet_pool.parquet"
    partial_path = out_path.with_suffix(out_path.suffix + ".partial")

    def _raise_after_partial(table, path: Path, **kwargs) -> None:
        Path(path).write_bytes(b"partial")
        raise RuntimeError("write failed")

    mocker.patch.object(builder.pq, "write_table", side_effect=_raise_after_partial)

    with pytest.raises(RuntimeError, match="write failed"):
        builder._write_pool(_academic_pool_frame(), out_path)

    assert not partial_path.exists()
    assert not out_path.exists()


def test_write_cached_fills_writes_final_without_leftover_partial(tmp_path: Path) -> None:
    import scripts.build_academic_wallet_pool as builder

    cache_path = tmp_path / "fills.parquet"

    builder._write_cached_fills(cache_path, _retail_open_close_fills(25_000.0))

    assert cache_path.exists()
    assert not cache_path.with_suffix(cache_path.suffix + ".partial").exists()
    assert not pd.read_parquet(cache_path).empty


def test_write_cached_fills_failure_removes_partial_and_leaves_no_final(
    mocker,
    tmp_path: Path,
) -> None:
    import scripts.build_academic_wallet_pool as builder

    cache_path = tmp_path / "fills.parquet"
    partial_path = cache_path.with_suffix(cache_path.suffix + ".partial")

    def _raise_after_partial(self, path: Path, *args, **kwargs) -> None:
        Path(path).write_bytes(b"partial")
        raise RuntimeError("cache write failed")

    mocker.patch.object(pd.DataFrame, "to_parquet", _raise_after_partial)

    with pytest.raises(RuntimeError, match="cache write failed"):
        builder._write_cached_fills(cache_path, _retail_open_close_fills(25_000.0))

    assert not partial_path.exists()
    assert not cache_path.exists()


def test_cli_logs_warning_when_fill_fetch_fails(mocker, tmp_path: Path, capsys) -> None:
    import scripts.build_academic_wallet_pool as builder

    leaderboard = _leaderboard_frame(
        [
            ("0xboom", 25_000.0),
            ("0xpass", 25_000.0),
        ]
    )
    mocker.patch.object(builder, "fetch_leaderboard", return_value=leaderboard)

    def _fake_fetch(address: str, start, end):
        if address == "0xboom":
            raise requests.ConnectionError("network failure")
        return _retail_open_close_fills(25_000.0)

    mocker.patch.object(builder, "fetch_user_fills", side_effect=_fake_fetch)

    result = builder.build_academic_wallet_pool(
        out=tmp_path / "pool.parquet",
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
        throttle_ms=0,
    )

    stderr = capsys.readouterr().err
    assert "warning" in stderr.lower()
    assert result["wallets_failed"] == 1
    assert result["written_count"] == 1


def test_cli_handles_tenacity_retry_error(mocker, tmp_path: Path) -> None:
    import tenacity

    import scripts.build_academic_wallet_pool as builder

    leaderboard = _leaderboard_frame([("0xfail", 25_000.0)])
    mocker.patch.object(builder, "fetch_leaderboard", return_value=leaderboard)
    mocker.patch.object(
        builder,
        "fetch_user_fills",
        side_effect=tenacity.RetryError("retries exhausted"),
    )

    result = builder.build_academic_wallet_pool(
        out=tmp_path / "pool.parquet",
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
        throttle_ms=0,
    )

    assert result["wallets_failed"] == 1
    assert result["written_count"] == 0


def test_build_academic_pool_handles_corrupt_cache(
    mocker,
    tmp_path: Path,
    capsys,
) -> None:
    import scripts.build_academic_wallet_pool as builder

    as_of = pd.Timestamp("2026-05-26T00:00:00Z")
    lookback_start = (as_of - pd.Timedelta(days=builder.LOOKBACK_DAYS)).to_pydatetime()
    lookback_end = as_of.to_pydatetime()
    cache_path = builder._cache_path(VALID_WALLET, lookback_start, lookback_end)
    assert cache_path is not None
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(b"not a parquet file")

    leaderboard = _leaderboard_frame([(VALID_WALLET, 25_000.0)])
    mocker.patch.object(builder, "fetch_leaderboard", return_value=leaderboard)
    fetch_mock = mocker.patch.object(
        builder,
        "fetch_user_fills",
        return_value=_retail_open_close_fills(25_000.0),
    )

    result = builder.build_academic_wallet_pool(
        out=tmp_path / "pool.parquet",
        as_of=as_of,
        throttle_ms=0,
    )

    stderr = capsys.readouterr().err
    assert "cached fills" in stderr
    assert "refetching" in stderr
    assert fetch_mock.call_count == 1
    assert result["written_count"] == 1
    assert not pd.read_parquet(cache_path).empty


def test_build_academic_pool_handles_cache_with_missing_columns(
    mocker,
    tmp_path: Path,
    capsys,
) -> None:
    import scripts.build_academic_wallet_pool as builder

    as_of = pd.Timestamp("2026-05-26T00:00:00Z")
    lookback_start = (as_of - pd.Timedelta(days=builder.LOOKBACK_DAYS)).to_pydatetime()
    lookback_end = as_of.to_pydatetime()
    cache_path = builder._cache_path(VALID_WALLET, lookback_start, lookback_end)
    assert cache_path is not None
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"wallet": [VALID_WALLET], "px": [100.0]}).to_parquet(
        cache_path,
        index=False,
    )

    leaderboard = _leaderboard_frame([(VALID_WALLET, 25_000.0)])
    mocker.patch.object(builder, "fetch_leaderboard", return_value=leaderboard)
    fetch_mock = mocker.patch.object(
        builder,
        "fetch_user_fills",
        return_value=_retail_open_close_fills(25_000.0),
    )

    result = builder.build_academic_wallet_pool(
        out=tmp_path / "pool.parquet",
        as_of=as_of,
        throttle_ms=0,
    )

    stderr = capsys.readouterr().err
    assert "missing columns" in stderr
    assert "refetching" in stderr
    assert fetch_mock.call_count == 1
    assert result["written_count"] == 1
    assert set(pd.read_parquet(cache_path).columns) >= {"dir", "px", "sz", "closed_pnl"}


def test_build_academic_pool_handles_cache_with_no_time_axis(
    mocker,
    tmp_path: Path,
    capsys,
) -> None:
    import scripts.build_academic_wallet_pool as builder

    as_of = pd.Timestamp("2026-05-26T00:00:00Z")
    lookback_start = (as_of - pd.Timedelta(days=builder.LOOKBACK_DAYS)).to_pydatetime()
    lookback_end = as_of.to_pydatetime()
    cache_path = builder._cache_path(VALID_WALLET_ALT, lookback_start, lookback_end)
    assert cache_path is not None
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "dir": ["Open Long"],
            "px": [100.0],
            "sz": [1.0],
            "closed_pnl": [0.0],
        }
    ).to_parquet(cache_path, index=False)

    leaderboard = _leaderboard_frame([(VALID_WALLET_ALT, 25_000.0)])
    mocker.patch.object(builder, "fetch_leaderboard", return_value=leaderboard)
    fetch_mock = mocker.patch.object(
        builder,
        "fetch_user_fills",
        return_value=_retail_open_close_fills(25_000.0),
    )

    result = builder.build_academic_wallet_pool(
        out=tmp_path / "pool.parquet",
        as_of=as_of,
        throttle_ms=0,
    )

    stderr = capsys.readouterr().err
    assert "missing time axis" in stderr
    assert "refetching" in stderr
    assert fetch_mock.call_count == 1
    assert result["written_count"] == 1


def test_cli_reraises_unexpected_fetch_errors(mocker, tmp_path: Path) -> None:
    import scripts.build_academic_wallet_pool as builder

    leaderboard = _leaderboard_frame([("0xboom", 25_000.0)])
    mocker.patch.object(builder, "fetch_leaderboard", return_value=leaderboard)
    mocker.patch.object(builder, "fetch_user_fills", side_effect=RuntimeError("schema drift"))

    with pytest.raises(RuntimeError, match="schema drift"):
        builder.build_academic_wallet_pool(
            out=tmp_path / "pool.parquet",
            as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
            throttle_ms=0,
        )


def test_build_academic_wallet_pool_uses_cache_unless_rebuild_requested(
    mocker,
    tmp_path: Path,
) -> None:
    import scripts.build_academic_wallet_pool as builder

    leaderboard = _leaderboard_frame([(VALID_WALLET, 25_000.0)])
    mocker.patch.object(builder, "fetch_leaderboard", return_value=leaderboard)
    fetched_addresses: list[str] = []

    def _fake_fetch(address: str, start, end):
        fetched_addresses.append(address)
        return _retail_open_close_fills(25_000.0)

    fetch_mock = mocker.patch.object(builder, "fetch_user_fills", side_effect=_fake_fetch)

    builder.build_academic_wallet_pool(
        out=tmp_path / "pool_first.parquet",
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
        throttle_ms=0,
    )
    fetch_mock.side_effect = AssertionError("cache should avoid refetch")
    cached_result = builder.build_academic_wallet_pool(
        out=tmp_path / "pool_cached.parquet",
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
        throttle_ms=0,
    )
    fetch_mock.side_effect = _fake_fetch
    builder.build_academic_wallet_pool(
        out=tmp_path / "pool_rebuilt.parquet",
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
        rebuild_cache=True,
        throttle_ms=0,
    )

    assert fetched_addresses == [VALID_WALLET, VALID_WALLET]
    assert cached_result["written_count"] == 1


def test_cli_rejects_top_n_zero(mocker, capsys) -> None:
    import scripts.build_academic_wallet_pool as builder

    mocker.patch("sys.argv", ["build_academic_wallet_pool.py", "--top-n", "0"])

    with pytest.raises(SystemExit):
        builder._parse_args()

    assert "--top-n must be greater than 0" in capsys.readouterr().err


def test_cli_help_does_not_crash(mocker) -> None:
    import scripts.build_academic_wallet_pool as builder

    mocker.patch("sys.argv", ["build_academic_wallet_pool.py", "-h"])

    with pytest.raises(SystemExit) as exc:
        builder._parse_args()

    assert exc.value.code == 0


def test_cli_parse_args_accepts_rebuild_cache(mocker) -> None:
    import scripts.build_academic_wallet_pool as builder

    mocker.patch("sys.argv", ["build_academic_wallet_pool.py", "--rebuild-cache"])

    args = builder._parse_args()

    assert args.rebuild_cache is True


def test_cli_main_entrypoint_prints_summary(mocker, tmp_path: Path, capsys) -> None:
    import scripts.build_academic_wallet_pool as builder

    leaderboard = _leaderboard_frame([("0xpass", 25_000.0)])
    mocker.patch.object(builder, "fetch_leaderboard", return_value=leaderboard)
    mocker.patch.object(
        builder, "fetch_user_fills", return_value=_retail_open_close_fills(25_000.0)
    )

    out_path = tmp_path / "pool.parquet"
    mocker.patch(
        "sys.argv",
        [
            "build_academic_wallet_pool.py",
            "--out",
            str(out_path),
            "--throttle-ms",
            "0",
            "--as-of",
            "2026-05-26T00:00:00Z",
        ],
    )

    exit_code = builder.main()

    assert exit_code == 0
    stdout = capsys.readouterr().out
    assert "academic pool" in stdout.lower()
    assert "written" in stdout.lower()
    assert out_path.exists()
