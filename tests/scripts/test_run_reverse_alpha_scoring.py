from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


def _pool_row(wallet: object = "0xpass") -> dict[str, object]:
    return {
        "wallet": wallet,
        "account_value": 10_000.0,
        "realized_loss_rate_90d": 0.75,
        "leverage_avg_90d": 12.5,
        "n_trades_90d": 125,
        "size_cv_90d": 0.45,
        "eligible_at": pd.Timestamp("2026-05-26T00:00:00Z"),
    }


def _pool_frame() -> pd.DataFrame:
    return pd.DataFrame([_pool_row()])


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
    assert written.columns.tolist() == [
        "fill_id",
        "wallet",
        "token",
        "time",
        "dir",
        "reverse_side",
        "score",
        "components",
    ]
    assert written["fill_id"].tolist() == ["fill-1"]
    assert written["wallet"].tolist() == ["0xpass"]
    assert written["token"].tolist() == ["BTC"]
    assert written["time"].tolist() == [pd.Timestamp("2026-05-26T12:00:00Z")]
    assert written["dir"].tolist() == ["Open Long"]
    assert written["reverse_side"].tolist() == ["short"]
    assert written["score"].iloc[0] == pytest.approx(1.5 * 1.3 * 1.2924234314520021)
    components = json.loads(written["components"].iloc[0])
    assert components["wallet_confidence"] == pytest.approx(0.3990799224301785)
    assert components["funding_zscore"] == 2.5
    assert report.exists()
    assert "Phase 2.5 Slice 2" in report.read_text()


def test_run_reverse_alpha_scoring_rejects_missing_wallet_fills_by_default(tmp_path: Path) -> None:
    import scripts.run_reverse_alpha_scoring as runner

    pool_path = tmp_path / "academic_wallet_pool.parquet"
    fills_dir = tmp_path / "fills"
    funding_dir = tmp_path / "funding"
    out = tmp_path / "reverse_alpha_scores.parquet"
    report = tmp_path / "reverse_scores.md"
    fills_dir.mkdir()
    funding_dir.mkdir()
    _pool_frame().to_parquet(pool_path, index=False)

    with pytest.raises(RuntimeError, match="missing fills.*0xpass"):
        runner.run_reverse_alpha_scoring(
            pool_path=pool_path,
            fills_dir=fills_dir,
            funding_dir=funding_dir,
            out=out,
            report=report,
        )

    assert not out.exists()
    assert not report.exists()


def test_run_reverse_alpha_scoring_allows_missing_wallet_fills_with_warning(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.run_reverse_alpha_scoring as runner

    pool_path, fills_dir, funding_dir = _write_inputs(tmp_path)
    pool = pd.DataFrame([_pool_row("0xpass"), _pool_row("0xmissing")])
    pool.to_parquet(pool_path, index=False)
    out = tmp_path / "reverse_alpha_scores.parquet"

    result = runner.run_reverse_alpha_scoring(
        pool_path=pool_path,
        fills_dir=fills_dir,
        funding_dir=funding_dir,
        out=out,
        report=None,
        allow_missing_fills=True,
    )

    assert result["wallets_missing_fills"] == 1
    assert result["wallets_scored"] == 1
    stderr = capsys.readouterr().err.lower()
    assert "missing fills" in stderr
    assert "0xmissing" in stderr


def test_run_reverse_alpha_scoring_respects_missing_fills_tolerance(tmp_path: Path) -> None:
    import scripts.run_reverse_alpha_scoring as runner

    pool_path, fills_dir, funding_dir = _write_inputs(tmp_path)
    pool = pd.DataFrame([_pool_row("0xpass"), _pool_row("0xmissing")])
    pool.to_parquet(pool_path, index=False)

    result = runner.run_reverse_alpha_scoring(
        pool_path=pool_path,
        fills_dir=fills_dir,
        funding_dir=funding_dir,
        out=tmp_path / "reverse_alpha_scores.parquet",
        report=None,
        missing_fills_tolerance=0.5,
    )

    assert result["wallets_missing_fills"] == 1
    assert result["wallets_scored"] == 1


def test_run_reverse_alpha_scoring_rejects_twenty_of_twenty_one_missing_fills(
    mocker,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.run_reverse_alpha_scoring as runner

    pool_path, fills_dir, funding_dir = _write_inputs(tmp_path)
    pool = pd.DataFrame([_pool_row("0xpass"), *[_pool_row(f"0xmissing{i:02d}") for i in range(20)]])
    pool.to_parquet(pool_path, index=False)
    out = tmp_path / "reverse_alpha_scores.parquet"
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
            str(tmp_path / "reverse_scores.md"),
        ],
    )

    exit_code = runner.main()

    assert exit_code == 1
    stderr = capsys.readouterr().err.lower()
    assert "missing fills" in stderr
    assert "0xmissing00" in stderr
    assert "0xmissing19" in stderr
    assert not out.exists()


def test_run_reverse_alpha_scoring_main_allows_missing_fills_with_warning(
    mocker,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.run_reverse_alpha_scoring as runner

    pool_path, fills_dir, funding_dir = _write_inputs(tmp_path)
    pool = pd.DataFrame([_pool_row("0xpass"), _pool_row("0xmissing")])
    pool.to_parquet(pool_path, index=False)
    out = tmp_path / "reverse_alpha_scores.parquet"
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
            str(tmp_path / "reverse_scores.md"),
            "--allow-missing-fills",
        ],
    )

    exit_code = runner.main()

    assert exit_code == 0
    stderr = capsys.readouterr().err.lower()
    assert "missing fills" in stderr
    assert "0xmissing" in stderr


def test_run_reverse_alpha_scoring_serializes_nonfinite_components_as_json_null(
    tmp_path: Path,
) -> None:
    import scripts.run_reverse_alpha_scoring as runner

    pool_path, fills_dir, funding_dir = _write_inputs(tmp_path)
    funding = pd.DataFrame(
        {"funding_rate": [0.0001, 0.0001, 0.0010]},
        index=pd.DatetimeIndex(
            [
                pd.Timestamp("2026-05-26T08:00:00Z"),
                pd.Timestamp("2026-05-26T10:00:00Z"),
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


def test_run_reverse_alpha_scoring_skips_na_wallet_rows(tmp_path: Path) -> None:
    import scripts.run_reverse_alpha_scoring as runner

    pool_path, fills_dir, funding_dir = _write_inputs(tmp_path)
    pd.DataFrame([_pool_row(pd.NA), _pool_row("0xpass")]).to_parquet(pool_path, index=False)

    result = runner.run_reverse_alpha_scoring(
        pool_path=pool_path,
        fills_dir=fills_dir,
        funding_dir=funding_dir,
        out=tmp_path / "reverse_alpha_scores.parquet",
        report=None,
    )

    assert result["wallets_total"] == 1
    assert result["wallets_scored"] == 1


def test_run_reverse_alpha_scoring_warns_when_no_wallets_score(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.run_reverse_alpha_scoring as runner

    pool_path, fills_dir, funding_dir = _write_inputs(tmp_path)
    pd.DataFrame([{**_fills_frame().iloc[0].to_dict(), "dir": "Close Long"}]).to_parquet(
        fills_dir / "0xpass.parquet",
        index=False,
    )

    result = runner.run_reverse_alpha_scoring(
        pool_path=pool_path,
        fills_dir=fills_dir,
        funding_dir=funding_dir,
        out=tmp_path / "reverse_alpha_scores.parquet",
        report=None,
    )

    assert result["wallets_scored"] == 0
    assert result["written_count"] == 0
    assert "no wallet fills were scored" in capsys.readouterr().err.lower()


def test_components_json_serializes_numpy_scalars() -> None:
    import scripts.run_reverse_alpha_scoring as runner

    raw = runner._components_json({"count": np.int64(3), "flag": np.bool_(True)})

    assert json.loads(raw) == {"count": 3, "flag": True}


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


def test_print_summary_handles_report_none(capsys: pytest.CaptureFixture[str]) -> None:
    import scripts.run_reverse_alpha_scoring as runner

    runner._print_summary(
        {
            "wallets_total": 1,
            "wallets_scored": 0,
            "wallets_missing_fills": 0,
            "wallets_empty_fills": 1,
            "funding_tokens_loaded": 0,
            "written_count": 0,
            "out": Path("scores.parquet"),
            "report": None,
            "runtime_seconds": 0.1,
        }
    )

    stdout = capsys.readouterr().out.lower()
    assert "wrote: scores.parquet" in stdout
    assert "report:" not in stdout


def test_cli_help_does_not_crash() -> None:
    import scripts.run_reverse_alpha_scoring as runner

    with pytest.raises(SystemExit) as exc_info:
        runner._parse_args(["-h"])

    assert exc_info.value.code == 0
