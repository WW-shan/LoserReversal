from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import pytest


def _fill_row(
    time: pd.Timestamp,
    *,
    coin: str,
    sz: float,
) -> dict[str, object]:
    return {
        "time": time,
        "coin": coin,
        "side": "B",
        "dir": "Open Long",
        "px": 100.0,
        "sz": sz,
        "start_position": 0.0,
        "closed_pnl": 0.0,
        "fee": 0.0,
        "oid": 1,
        "tid": 1,
        "hash": "0x1",
        "crossed": False,
        "liquidation": False,
    }


def _fills_df(rows: list[dict[str, object]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    frame["time"] = pd.to_datetime(frame["time"], utc=True)
    return frame.set_index("time").sort_index()


def _bot_fills() -> pd.DataFrame:
    base = pd.Timestamp("2026-05-01T00:00:00Z")
    return _fills_df(
        [
            _fill_row(base + pd.Timedelta(hours=i), coin="BTC", sz=1_000.0)
            for i in range(24)
        ]
    )


def _human_fills() -> pd.DataFrame:
    base = pd.Timestamp("2026-05-01T00:00:00Z")
    coins = ["BTC", "ETH", "SOL", "HYPE", "DOGE", "XRP", "BNB", "SUI"]
    gaps = [0, 7, 31, 215, 377, 600, 980, 1_440]
    sizes = [127.43, 981.27, 53.81, 2_345.67, 410.19, 88.42, 1_579.31, 231.76]
    return _fills_df(
        [
            _fill_row(base + pd.Timedelta(minutes=gaps[i]), coin=coins[i], sz=sizes[i])
            for i in range(len(coins))
        ]
    )


def _leaderboard_frame(rows: list[tuple[str, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "eth_address": wallet,
                "account_value": account_value,
                "display_name": wallet,
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
            for wallet, account_value in rows
        ]
    )


def test_score_raises_when_n_trades_key_missing() -> None:
    from bot_reverse.bot_detector import score_bot_likelihood

    features = {
        "tx_hour_entropy": 0.9,
        "size_uniformity_cv": 0.1,
        "coin_diversity": 0.1,
        "median_session_gap_minutes": 45.0,
        "round_number_pct": 0.9,
    }

    with pytest.raises(ValueError, match="missing required 'n_trades' key"):
        score_bot_likelihood(features)


def test_build_bot_pool_writes_bot_wallets_and_excludes_humans(mocker, tmp_path: Path) -> None:
    import scripts.build_bot_pool as builder

    leaderboard = _leaderboard_frame(
        [
            ("0xbot", 25_000.0),
            ("0xhuman", 25_000.0),
        ]
    )
    mocker.patch.object(builder, "fetch_leaderboard", return_value=leaderboard)

    def _fake_fetch(address: str, start, end):
        if address.lower() == "0xbot":
            return _bot_fills()
        return _human_fills()

    mocker.patch.object(builder, "fetch_user_fills", side_effect=_fake_fetch)

    out_path = tmp_path / "bot_wallets.parquet"
    result = builder.build_bot_pool(
        out=out_path,
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
        throttle_ms=0,
    )

    written = pd.read_parquet(out_path)
    assert written.columns.tolist() == [
        "wallet",
        "bot_score",
        "hour_entropy",
        "size_cv",
        "coin_diversity",
        "session_gap_median_min",
        "round_number_pct",
    ]
    assert written["wallet"].tolist() == ["0xbot"]
    assert written["bot_score"].iloc[0] >= 0.8
    assert result["written_count"] == 1
    assert result["human_excluded_count"] == 1


def test_build_bot_pool_honours_top_n_and_max_wallets(mocker, tmp_path: Path) -> None:
    import scripts.build_bot_pool as builder

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
        return _bot_fills()

    mocker.patch.object(builder, "fetch_user_fills", side_effect=_fake_fetch)

    result = builder.build_bot_pool(
        out=tmp_path / "bot_wallets.parquet",
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
        top_n=3,
        max_wallets=2,
        throttle_ms=0,
    )

    written = pd.read_parquet(tmp_path / "bot_wallets.parquet")
    assert fetched_addresses == ["0xa", "0xb", "0xc"]
    assert written["wallet"].tolist() == ["0xa", "0xb"]
    assert result["leaderboard_count"] == 3
    assert result["written_count"] == 2


def test_build_bot_pool_deduplicates_leaderboard_wallets(mocker, tmp_path: Path) -> None:
    import scripts.build_bot_pool as builder

    leaderboard = _leaderboard_frame(
        [
            ("0xa", 25_000.0),
            ("0xa", 25_000.0),
            ("0xb", 25_000.0),
        ]
    )
    mocker.patch.object(builder, "fetch_leaderboard", return_value=leaderboard)
    fetched_addresses: list[str] = []

    def _fake_fetch(address: str, start, end):
        fetched_addresses.append(address)
        return _bot_fills()

    mocker.patch.object(builder, "fetch_user_fills", side_effect=_fake_fetch)

    result = builder.build_bot_pool(
        out=tmp_path / "bot_wallets.parquet",
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
        top_n=3,
        throttle_ms=0,
    )

    written = pd.read_parquet(tmp_path / "bot_wallets.parquet")
    assert fetched_addresses == ["0xa", "0xb"]
    assert written["wallet"].tolist() == ["0xa", "0xb"]
    assert result["leaderboard_count"] == 2
    assert result["written_count"] == 2


def test_build_bot_pool_lowercases_and_deduplicates_before_top_n(mocker, tmp_path: Path) -> None:
    import scripts.build_bot_pool as builder

    leaderboard = _leaderboard_frame(
        [
            ("0xAbC", 25_000.0),
            ("0xabc", 25_000.0),
            ("0xdef", 25_000.0),
        ]
    )
    mocker.patch.object(builder, "fetch_leaderboard", return_value=leaderboard)
    fetched_addresses: list[str] = []

    def _fake_fetch(address: str, start, end):
        fetched_addresses.append(address)
        return _bot_fills()

    mocker.patch.object(builder, "fetch_user_fills", side_effect=_fake_fetch)

    result = builder.build_bot_pool(
        out=tmp_path / "bot_wallets.parquet",
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
        top_n=2,
        throttle_ms=0,
    )

    assert fetched_addresses == ["0xabc", "0xdef"]
    assert result["leaderboard_count"] == 2


def test_build_bot_pool_logs_warning_when_fill_fetch_fails(mocker, tmp_path: Path, capsys) -> None:
    import scripts.build_bot_pool as builder

    leaderboard = _leaderboard_frame(
        [
            ("0xboom", 25_000.0),
            ("0xbot", 25_000.0),
        ]
    )
    mocker.patch.object(builder, "fetch_leaderboard", return_value=leaderboard)

    def _fake_fetch(address: str, start, end):
        if address == "0xboom":
            raise RuntimeError("network failure")
        return _bot_fills()

    mocker.patch.object(builder, "fetch_user_fills", side_effect=_fake_fetch)

    result = builder.build_bot_pool(
        out=tmp_path / "bot_wallets.parquet",
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
        throttle_ms=0,
    )

    stderr = capsys.readouterr().err
    assert "warning" in stderr.lower()
    assert result["wallets_failed"] == 1
    assert result["written_count"] == 1


def test_build_bot_pool_handles_null_eth_address(mocker, tmp_path: Path) -> None:
    import scripts.build_bot_pool as builder

    leaderboard = pd.DataFrame({"eth_address": ["0xbot", pd.NA]})
    mocker.patch.object(builder, "fetch_leaderboard", return_value=leaderboard)
    fetched_addresses: list[str] = []

    def _fake_fetch(address: str, start, end):
        fetched_addresses.append(address)
        return _bot_fills()

    mocker.patch.object(builder, "fetch_user_fills", side_effect=_fake_fetch)

    out_path = tmp_path / "bot_wallets.parquet"
    result = builder.build_bot_pool(
        out=out_path,
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
        throttle_ms=0,
    )

    written = pd.read_parquet(out_path)
    assert fetched_addresses == ["0xbot"]
    assert written["wallet"].tolist() == ["0xbot"]
    assert result["written_count"] == 1


def test_build_bot_pool_resume_skips_completed_wallets_and_retries_failed(mocker, tmp_path: Path) -> None:
    import scripts.build_bot_pool as builder

    out_path = tmp_path / "bot_wallets.parquet"
    checkpoint_path = Path(f"{out_path}.tmp.parquet")
    checkpoint = pd.DataFrame(
        [
            {
                "wallet": "0xbot",
                "bot_score": 1.0,
                "hour_entropy": 1.0,
                "size_cv": 0.0,
                "coin_diversity": 0.1,
                "session_gap_median_min": 60.0,
                "round_number_pct": 1.0,
                "status": "bot",
                "processed_at": "2026-05-26T00:00:00+00:00",
            },
            {
                "wallet": "0xhuman",
                "bot_score": 0.1,
                "hour_entropy": 0.0,
                "size_cv": 2.0,
                "coin_diversity": 1.0,
                "session_gap_median_min": 1440.0,
                "round_number_pct": 0.0,
                "status": "human",
                "processed_at": "2026-05-26T00:00:01+00:00",
            },
            {
                "wallet": "0xfailed",
                "bot_score": float("nan"),
                "hour_entropy": float("nan"),
                "size_cv": float("nan"),
                "coin_diversity": float("nan"),
                "session_gap_median_min": float("nan"),
                "round_number_pct": float("nan"),
                "status": "failed",
                "processed_at": "2026-05-26T00:00:02+00:00",
            },
        ],
        columns=builder.CHECKPOINT_COLUMNS,
    )
    builder._write_checkpoint(checkpoint, checkpoint_path)

    leaderboard = _leaderboard_frame(
        [
            ("0xbot", 25_000.0),
            ("0xhuman", 25_000.0),
            ("0xfailed", 25_000.0),
            ("0xnew", 25_000.0),
        ]
    )
    mocker.patch.object(builder, "fetch_leaderboard", return_value=leaderboard)
    fetched_addresses: list[str] = []

    def _fake_fetch(address: str, start, end):
        fetched_addresses.append(address)
        return _bot_fills()

    mocker.patch.object(builder, "fetch_user_fills", side_effect=_fake_fetch)

    result = builder.build_bot_pool(
        out=out_path,
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
        throttle_ms=0,
        resume=True,
    )

    written = pd.read_parquet(out_path)
    assert fetched_addresses == ["0xfailed", "0xnew"]
    assert written["wallet"].tolist() == ["0xbot", "0xfailed", "0xnew"]
    assert not checkpoint_path.exists()
    assert result["written_count"] == 3
    assert result["resumed_from_checkpoint"] is True
    assert result["checkpoint_skipped_count"] == 2


def test_build_bot_pool_fresh_run_cleans_stale_checkpoint(mocker, tmp_path: Path) -> None:
    import scripts.build_bot_pool as builder

    out_path = tmp_path / "bot_wallets.parquet"
    checkpoint_path = builder._checkpoint_path(out_path)
    builder._write_checkpoint(
        pd.DataFrame(
            [
                {
                    "wallet": "0xfake",
                    "bot_score": 0.0,
                    "hour_entropy": 0.0,
                    "size_cv": 0.0,
                    "coin_diversity": 0.0,
                    "session_gap_median_min": 0.0,
                    "round_number_pct": 0.0,
                    "status": "failed",
                    "processed_at": "2026-05-26T00:00:00+00:00",
                }
            ],
            columns=builder.CHECKPOINT_COLUMNS,
        ),
        checkpoint_path,
    )

    leaderboard = _leaderboard_frame([("0xbot", 25_000.0)])
    mocker.patch.object(builder, "fetch_leaderboard", return_value=leaderboard)
    mocker.patch.object(builder, "fetch_user_fills", return_value=_bot_fills())

    result = builder.build_bot_pool(
        out=out_path,
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
        throttle_ms=0,
    )

    assert pd.read_parquet(out_path)["wallet"].tolist() == ["0xbot"]
    assert not checkpoint_path.exists()
    assert result["written_count"] == 1


def test_resume_retries_previously_failed_wallets(mocker, tmp_path: Path) -> None:
    import scripts.build_bot_pool as builder

    out_path = tmp_path / "bot_wallets.parquet"
    checkpoint_path = builder._checkpoint_path(out_path)
    builder._write_checkpoint(
        pd.DataFrame(
            [
                {
                    "wallet": "0xfail",
                    "bot_score": float("nan"),
                    "hour_entropy": float("nan"),
                    "size_cv": float("nan"),
                    "coin_diversity": float("nan"),
                    "session_gap_median_min": float("nan"),
                    "round_number_pct": float("nan"),
                    "status": "failed",
                    "processed_at": "2026-05-26T00:00:00+00:00",
                }
            ],
            columns=builder.CHECKPOINT_COLUMNS,
        ),
        checkpoint_path,
    )
    leaderboard = _leaderboard_frame([("0xfail", 25_000.0)])
    mocker.patch.object(builder, "fetch_leaderboard", return_value=leaderboard)
    fetch_user_fills = mocker.patch.object(builder, "fetch_user_fills", return_value=_bot_fills())

    result = builder.build_bot_pool(
        out=out_path,
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
        throttle_ms=0,
        resume=True,
    )

    fetch_user_fills.assert_called_once()
    assert fetch_user_fills.call_args.args[0] == "0xfail"
    assert pd.read_parquet(out_path)["wallet"].tolist() == ["0xfail"]
    assert result["written_count"] == 1


def test_build_bot_pool_retry_replaces_previous_failed_row(mocker, tmp_path: Path) -> None:
    import scripts.build_bot_pool as builder

    out_path = tmp_path / "bot_wallets.parquet"
    checkpoint_path = builder._checkpoint_path(out_path)
    builder._write_checkpoint(
        pd.DataFrame(
            [
                {
                    "wallet": "0xfail",
                    "bot_score": float("nan"),
                    "hour_entropy": float("nan"),
                    "size_cv": float("nan"),
                    "coin_diversity": float("nan"),
                    "session_gap_median_min": float("nan"),
                    "round_number_pct": float("nan"),
                    "status": "failed",
                    "processed_at": "2026-05-26T00:00:00+00:00",
                }
            ],
            columns=builder.CHECKPOINT_COLUMNS,
        ),
        checkpoint_path,
    )

    leaderboard = _leaderboard_frame(
        [
            ("0xfail", 25_000.0),
            ("0xnext", 25_000.0),
        ]
    )
    mocker.patch.object(builder, "fetch_leaderboard", return_value=leaderboard)
    mocker.patch.object(
        builder,
        "fetch_user_fills",
        side_effect=[_bot_fills(), KeyboardInterrupt],
    )

    with pytest.raises(KeyboardInterrupt):
        builder.build_bot_pool(
            out=out_path,
            as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
            throttle_ms=0,
            resume=True,
        )

    checkpoint = pd.read_parquet(checkpoint_path)
    assert checkpoint["wallet"].tolist() == ["0xfail"]
    assert checkpoint["status"].tolist() == ["bot"]


def test_build_bot_pool_ignores_checkpoint_with_old_schema(tmp_path: Path, capsys) -> None:
    import scripts.build_bot_pool as builder

    checkpoint_path = tmp_path / "bot_wallets.parquet.tmp.parquet"
    old_checkpoint = pd.DataFrame(
        [
            {
                "wallet": "0xold",
                "bot_score": 1.0,
                "hour_entropy": 1.0,
                "size_cv": 0.0,
                "coin_diversity": 0.1,
                "session_gap_min": 60.0,
                "round_number_pct": 1.0,
            }
        ]
    )
    old_checkpoint.to_parquet(checkpoint_path, index=False)

    rows, wallets = builder._load_checkpoint(checkpoint_path)

    assert rows == []
    assert wallets == set()
    assert "missing columns" in capsys.readouterr().err


def test_build_bot_pool_ignores_corrupt_checkpoint(tmp_path: Path, capsys) -> None:
    import scripts.build_bot_pool as builder

    checkpoint_path = tmp_path / "bot_wallets.parquet.tmp.parquet"
    checkpoint_path.write_text("not parquet", encoding="utf-8")

    rows, wallets = builder._load_checkpoint(checkpoint_path)

    assert rows == []
    assert wallets == set()
    assert "unreadable" in capsys.readouterr().err


def test_save_checkpoint_writes_partial_then_atomic_replace(mocker, tmp_path: Path) -> None:
    import scripts.build_bot_pool as builder

    checkpoint_path = tmp_path / "bot_wallets.parquet.tmp.parquet"
    rows = [
        {
            "wallet": "0xbot",
            "bot_score": 1.0,
            "hour_entropy": 1.0,
            "size_cv": 0.0,
            "coin_diversity": 0.1,
            "session_gap_median_min": 60.0,
            "round_number_pct": 1.0,
            "status": "bot",
            "processed_at": "2026-05-26T00:00:00+00:00",
        }
    ]
    replaced: list[tuple[Path, Path]] = []

    def _fake_replace(src: Path, dst: Path) -> None:
        replaced.append((Path(src), Path(dst)))

    mocker.patch.object(builder.os, "replace", side_effect=_fake_replace)

    builder._save_checkpoint(rows, checkpoint_path)

    assert replaced == [(checkpoint_path.with_suffix(checkpoint_path.suffix + ".partial"), checkpoint_path)]


def test_save_checkpoint_removes_partial_when_replace_fails(mocker, tmp_path: Path) -> None:
    import scripts.build_bot_pool as builder

    checkpoint_path = tmp_path / "bot_wallets.parquet.tmp.parquet"
    rows = [
        {
            "wallet": "0xbot",
            "bot_score": 1.0,
            "hour_entropy": 1.0,
            "size_cv": 0.0,
            "coin_diversity": 0.1,
            "session_gap_median_min": 60.0,
            "round_number_pct": 1.0,
            "status": "bot",
            "processed_at": "2026-05-26T00:00:00+00:00",
        }
    ]
    partial_path = checkpoint_path.with_suffix(checkpoint_path.suffix + ".partial")
    mocker.patch.object(builder.os, "replace", side_effect=RuntimeError("replace failed"))

    with pytest.raises(RuntimeError, match="replace failed"):
        builder._save_checkpoint(rows, checkpoint_path)

    assert not partial_path.exists()


def test_load_checkpoint_coerces_numeric_columns_and_drops_invalid_completed_rows(
    tmp_path: Path,
) -> None:
    import scripts.build_bot_pool as builder

    checkpoint_path = tmp_path / "bot_wallets.parquet.tmp.parquet"
    pd.DataFrame(
        [
            {
                "wallet": "0xbot",
                "bot_score": "0.9",
                "hour_entropy": "1.0",
                "size_cv": "0.0",
                "coin_diversity": "0.1",
                "session_gap_median_min": "60.0",
                "round_number_pct": "1.0",
                "status": "bot",
                "processed_at": "2026-05-26T00:00:00+00:00",
            },
            {
                "wallet": "0xbad",
                "bot_score": "not-a-score",
                "hour_entropy": "1.0",
                "size_cv": "0.0",
                "coin_diversity": "0.1",
                "session_gap_median_min": "60.0",
                "round_number_pct": "1.0",
                "status": "bot",
                "processed_at": "2026-05-26T00:00:01+00:00",
            },
            {
                "wallet": "0xfail",
                "bot_score": None,
                "hour_entropy": None,
                "size_cv": None,
                "coin_diversity": None,
                "session_gap_median_min": None,
                "round_number_pct": None,
                "status": "failed",
                "processed_at": "2026-05-26T00:00:02+00:00",
            },
        ],
        columns=builder.CHECKPOINT_COLUMNS,
    ).to_parquet(checkpoint_path, index=False)

    rows, wallets = builder._load_checkpoint(checkpoint_path)

    assert [row["wallet"] for row in rows] == ["0xbot", "0xfail"]
    assert isinstance(rows[0]["bot_score"], float)
    assert rows[0]["bot_score"] == pytest.approx(0.9)
    assert wallets == {"0xbot"}


def test_build_bot_pool_keyboard_interrupt_saves_checkpoint_with_partial_rows(
    mocker,
    tmp_path: Path,
) -> None:
    import scripts.build_bot_pool as builder

    out_path = tmp_path / "bot_wallets.parquet"
    checkpoint_path = Path(f"{out_path}.tmp.parquet")
    leaderboard = _leaderboard_frame(
        [
            ("0xbot", 25_000.0),
            ("0xinterrupt", 25_000.0),
        ]
    )
    mocker.patch.object(builder, "fetch_leaderboard", return_value=leaderboard)
    mocker.patch.object(builder, "fetch_user_fills", side_effect=[_bot_fills(), KeyboardInterrupt])

    with pytest.raises(KeyboardInterrupt):
        builder.build_bot_pool(
            out=out_path,
            as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
            throttle_ms=0,
            resume=True,
        )

    checkpoint = pd.read_parquet(checkpoint_path)
    assert checkpoint["wallet"].tolist() == ["0xbot"]
    assert checkpoint["status"].tolist() == ["bot"]


def test_build_bot_pool_written_schema_matches_declared_schema(mocker, tmp_path: Path) -> None:
    import scripts.build_bot_pool as builder

    leaderboard = _leaderboard_frame([("0xbot", 25_000.0)])
    mocker.patch.object(builder, "fetch_leaderboard", return_value=leaderboard)
    mocker.patch.object(builder, "fetch_user_fills", return_value=_bot_fills())

    out_path = tmp_path / "bot_wallets.parquet"
    builder.build_bot_pool(
        out=out_path,
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
        throttle_ms=0,
    )

    assert pq.read_table(out_path).schema.remove_metadata() == builder.BOT_POOL_SCHEMA
    assert pq.read_table(out_path).column_names == builder.BOT_POOL_COLUMNS


def test_build_bot_pool_checkpoint_schema_matches_declared(mocker, tmp_path: Path) -> None:
    import scripts.build_bot_pool as builder

    leaderboard = _leaderboard_frame([("0xbot", 25_000.0)])
    mocker.patch.object(builder, "fetch_leaderboard", return_value=leaderboard)
    mocker.patch.object(builder, "fetch_user_fills", return_value=_bot_fills())
    out_path = tmp_path / "bot_wallets.parquet"
    checkpoint_path = builder._checkpoint_path(out_path)

    builder._save_checkpoint(
        [builder._checkpoint_row("0xtest", status="bot")],
        checkpoint_path,
    )

    assert pq.read_table(checkpoint_path).schema.remove_metadata() == builder.CHECKPOINT_SCHEMA


def test_build_bot_pool_print_summary_mentions_resume(capsys) -> None:
    import scripts.build_bot_pool as builder

    builder._print_summary(
        {
            "out": Path("bot_wallets.parquet"),
            "written_count": 1,
            "leaderboard_count": 2,
            "wallets_fetched": 1,
            "wallets_failed": 0,
            "human_excluded_count": 0,
            "runtime_seconds": 0.1,
            "as_of": pd.Timestamp("2026-05-26T00:00:00Z"),
            "resumed_from_checkpoint": True,
            "checkpoint_skipped_count": 3,
        }
    )

    stdout = capsys.readouterr().out
    assert "resumed: yes (skipped 3 previously-processed wallets)" in stdout
    assert "this run only" in stdout


def test_build_bot_pool_main_entrypoint_prints_summary(mocker, tmp_path: Path, capsys) -> None:
    import scripts.build_bot_pool as builder

    leaderboard = _leaderboard_frame([("0xbot", 25_000.0)])
    mocker.patch.object(builder, "fetch_leaderboard", return_value=leaderboard)
    mocker.patch.object(builder, "fetch_user_fills", return_value=_bot_fills())

    out_path = tmp_path / "bot_wallets.parquet"
    mocker.patch(
        "sys.argv",
        [
            "build_bot_pool.py",
            "--out",
            str(out_path),
            "--throttle-ms",
            "0",
            "--as-of",
            "2026-05-26T00:00:00Z",
            "--min-trades",
            "10",
        ],
    )

    exit_code = builder.main()

    assert exit_code == 0
    stdout = capsys.readouterr().out
    assert "bot pool" in stdout.lower()
    assert "written" in stdout.lower()
    assert out_path.exists()


def test_build_bot_pool_parse_args_accepts_resume_and_min_trades(mocker) -> None:
    import scripts.build_bot_pool as builder

    mocker.patch("sys.argv", ["build_bot_pool.py", "--resume", "--min-trades", "30"])

    args = builder._parse_args()

    assert args.resume is True
    assert args.min_trades == 30


def test_build_bot_pool_rejects_invalid_max_wallets(mocker, capsys) -> None:
    import scripts.build_bot_pool as builder

    mocker.patch("sys.argv", ["build_bot_pool.py", "--max-wallets", "0"])

    with pytest.raises(SystemExit):
        builder._parse_args()

    assert "--max-wallets must be greater than 0" in capsys.readouterr().err


def test_is_bot_wallet_rejects_invalid_min_trades() -> None:
    from bot_reverse.bot_detector import is_bot_wallet

    features = {
        "tx_hour_entropy": 0.0,
        "size_uniformity_cv": 0.0,
        "coin_diversity": 0.0,
        "median_session_gap_minutes": 360.0,
        "round_number_pct": 0.0,
        "n_trades": 50.0,
    }

    for min_trades_for_scoring in (0, -1):
        with pytest.raises(ValueError, match="min_trades_for_scoring must be >= 1"):
            is_bot_wallet(features, min_trades_for_scoring=min_trades_for_scoring)
