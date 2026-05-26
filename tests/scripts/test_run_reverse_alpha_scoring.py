from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest


def _pool_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "wallet": "0xpass",
                "account_value": 10_000.0,
                "realized_loss_rate_90d": 0.75,
                "leverage_avg_90d": 12.5,
                "n_trades_90d": 125,
                "size_cv_90d": 0.45,
                "eligible_at": pd.Timestamp("2026-05-26T00:00:00Z"),
            }
        ]
    )


def _fills_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "fill_id": "fill-1",
                "time": pd.Timestamp("2026-05-26T12:00:00Z"),
                "coin": "BTC",
                "dir": "Open Long",
                "px": 100.0,
                "sz": 5.0,
                "leverage": 10.0,
            }
        ]
    )


def _funding_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {"funding_zscore": [2.5]},
        index=pd.DatetimeIndex([pd.Timestamp("2026-05-26T11:00:00Z")], name="timestamp"),
    )


def _write_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    pool_path = tmp_path / "academic_wallet_pool.parquet"
    fills_dir = tmp_path / "fills"
    funding_dir = tmp_path / "funding"
    fills_dir.mkdir()
    funding_dir.mkdir()

    _pool_frame().to_parquet(pool_path, index=False)
    _fills_frame().to_parquet(fills_dir / "0xpass.parquet", index=False)
    _funding_frame().to_parquet(funding_dir / "BTC.parquet")
    return pool_path, fills_dir, funding_dir


def test_run_reverse_alpha_scoring_writes_scores_and_report(tmp_path: Path) -> None:
    import scripts.run_reverse_alpha_scoring as runner

    pool_path, fills_dir, funding_dir = _write_inputs(tmp_path)
    out = tmp_path / "reverse_alpha_scores.parquet"
    report = tmp_path / "reverse_scores.md"

    result = runner.run_reverse_alpha_scoring(
        pool_path=pool_path,
        fills_dir=fills_dir,
        funding_dir=funding_dir,
        out=out,
        report=report,
    )

    assert result["written_count"] == 1
    assert result["wallets_scored"] == 1
    assert out.exists()
    written = pd.read_parquet(out)
    assert written.columns.tolist() == ["fill_id", "wallet", "token", "score", "components"]
    assert written["fill_id"].tolist() == ["fill-1"]
    assert written["wallet"].tolist() == ["0xpass"]
    assert written["token"].tolist() == ["BTC"]
    assert written["score"].iloc[0] == pytest.approx(1.5 * 1.3 * 1.4)
    components = json.loads(written["components"].iloc[0])
    assert components["wallet_confidence"] == 0.5
    assert components["funding_zscore"] == 2.5
    assert report.exists()
    assert "Phase 2.5 Slice 2" in report.read_text()


def test_run_reverse_alpha_scoring_skips_missing_wallet_fills(tmp_path: Path) -> None:
    import scripts.run_reverse_alpha_scoring as runner

    pool_path = tmp_path / "academic_wallet_pool.parquet"
    fills_dir = tmp_path / "fills"
    funding_dir = tmp_path / "funding"
    out = tmp_path / "reverse_alpha_scores.parquet"
    report = tmp_path / "reverse_scores.md"
    fills_dir.mkdir()
    funding_dir.mkdir()
    _pool_frame().to_parquet(pool_path, index=False)

    result = runner.run_reverse_alpha_scoring(
        pool_path=pool_path,
        fills_dir=fills_dir,
        funding_dir=funding_dir,
        out=out,
        report=report,
    )

    assert result["written_count"] == 0
    assert result["wallets_missing_fills"] == 1
    assert pd.read_parquet(out).empty
    assert report.exists()


def test_run_reverse_alpha_scoring_serializes_nonfinite_components_as_json_null(
    tmp_path: Path,
) -> None:
    import scripts.run_reverse_alpha_scoring as runner

    pool_path, fills_dir, funding_dir = _write_inputs(tmp_path)
    funding = pd.DataFrame(
        {"funding_rate": [0.0001, 0.0010]},
        index=pd.DatetimeIndex(
            [
                pd.Timestamp("2026-05-26T08:00:00Z"),
                pd.Timestamp("2026-05-26T11:00:00Z"),
            ],
            name="timestamp",
        ),
    )
    funding.to_parquet(funding_dir / "BTC.parquet")
    out = tmp_path / "reverse_alpha_scores.parquet"

    runner.run_reverse_alpha_scoring(
        pool_path=pool_path,
        fills_dir=fills_dir,
        funding_dir=funding_dir,
        out=out,
        report=None,
    )

    written = pd.read_parquet(out)
    raw_components = written["components"].iloc[0]
    assert "Infinity" not in raw_components
    components = json.loads(raw_components)
    assert components["funding_zscore"] is None
    assert written["score"].iloc[0] == pytest.approx(1.5 * 1.3 * 1.4)


def test_run_reverse_alpha_scoring_rejects_score_token_count_mismatch(
    mocker,
    tmp_path: Path,
) -> None:
    import scripts.run_reverse_alpha_scoring as runner

    pool_path, fills_dir, funding_dir = _write_inputs(tmp_path)
    fills = pd.concat(
        [
            _fills_frame(),
            _fills_frame().assign(fill_id="fill-2", coin="ETH"),
        ],
        ignore_index=True,
    )
    fills.to_parquet(fills_dir / "0xpass.parquet", index=False)
    mocker.patch.object(
        runner,
        "score_wallet_fills",
        return_value=pd.DataFrame(
            [{"fill_id": "fill-1", "score": 1.0, "components": {}}],
            columns=["fill_id", "score", "components"],
        ),
    )

    with pytest.raises(RuntimeError, match="score row count"):
        runner.run_reverse_alpha_scoring(
            pool_path=pool_path,
            fills_dir=fills_dir,
            funding_dir=funding_dir,
            out=tmp_path / "reverse_alpha_scores.parquet",
            report=None,
        )


def test_run_reverse_alpha_scoring_main_prints_summary(
    mocker,
    tmp_path: Path,
    capsys,
) -> None:
    import scripts.run_reverse_alpha_scoring as runner

    pool_path, fills_dir, funding_dir = _write_inputs(tmp_path)
    out = tmp_path / "reverse_alpha_scores.parquet"
    report = tmp_path / "reverse_scores.md"
    mocker.patch(
        "sys.argv",
        [
            "run_reverse_alpha_scoring.py",
            "--pool",
            str(pool_path),
            "--fills-dir",
            str(fills_dir),
            "--funding-dir",
            str(funding_dir),
            "--out",
            str(out),
            "--report",
            str(report),
        ],
    )

    exit_code = runner.main()

    assert exit_code == 0
    stdout = capsys.readouterr().out
    assert "reverse alpha scoring" in stdout.lower()
    assert "written rows: 1" in stdout.lower()
    assert out.exists()
    assert report.exists()
