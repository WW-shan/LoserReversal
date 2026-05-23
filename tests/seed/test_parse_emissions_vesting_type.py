from __future__ import annotations

import csv
from pathlib import Path

from data.seed import parse_emissions
from data.seed.parse_emissions import Coin


def test_parse_emissions_writes_vesting_type_for_each_manual_call(
    monkeypatch,
    tmp_path: Path,
):
    _write_protocol(
        tmp_path / "cliff-token.ts",
        "cliff-token",
        "CLF",
        'team: manualCliff("2026-01-01", 20)',
    )
    _write_protocol(
        tmp_path / "step-token.ts",
        "step-token",
        "STP",
        'team: manualStep("2026-01-02", 86400, 2, 20)',
    )
    _write_protocol(
        tmp_path / "linear-token.ts",
        "linear-token",
        "LIN",
        'team: manualLinear("2026-01-03", "2026-01-05", 40)',
    )
    out_csv = _run_parser(monkeypatch, tmp_path)

    rows = _read_rows(out_csv)

    assert {row["vesting_type"] for row in rows} == {"cliff", "step", "linear"}
    assert _vesting_types_for(rows, "CLF") == ["cliff"]
    assert _vesting_types_for(rows, "STP") == ["step", "step"]
    assert _vesting_types_for(rows, "LIN") == ["linear", "linear"]


def test_parse_emissions_keeps_mixed_vesting_rows_separate_after_aggregation(
    monkeypatch,
    tmp_path: Path,
):
    _write_protocol(
        tmp_path / "mixed-token.ts",
        "mixed-token",
        "MIX",
        """
        team: [
            manualCliff("2026-01-10", 20),
            manualStep("2026-01-10", 86400, 1, 30),
        ],
        """,
    )
    out_csv = _run_parser(monkeypatch, tmp_path)

    rows = _read_rows(out_csv)

    assert len(rows) == 2
    assert {row["vesting_type"] for row in rows} == {"cliff", "step"}
    assert sorted(float(row["unlock_pct"]) for row in rows) == [0.02, 0.03]


def test_parse_emissions_includes_unlocks_from_2023(monkeypatch, tmp_path: Path):
    _write_protocol(
        tmp_path / "cliff-token.ts",
        "cliff-token",
        "CLF",
        'team: manualCliff("2023-01-01", 20)',
    )
    out_csv = _run_parser(monkeypatch, tmp_path)

    rows = _read_rows(out_csv)

    assert [row["unlock_date"] for row in rows] == ["2023-01-01"]


def _run_parser(monkeypatch, protocols_dir: Path) -> Path:
    out_csv = protocols_dir / "unlocks.csv"
    coins = {
        "cliff-token": Coin("cliff-token", "CLF", "Cliff Token"),
        "step-token": Coin("step-token", "STP", "Step Token"),
        "linear-token": Coin("linear-token", "LIN", "Linear Token"),
        "mixed-token": Coin("mixed-token", "MIX", "Mixed Token"),
    }
    by_symbol = {coin.symbol: [coin] for coin in coins.values()}
    monkeypatch.setattr(parse_emissions, "PROTOCOLS_DIR", protocols_dir)
    monkeypatch.setattr(parse_emissions, "OUT_CSV", out_csv)
    monkeypatch.setattr(parse_emissions, "load_coins", lambda: (coins, by_symbol))
    monkeypatch.setattr(parse_emissions, "hyperliquid_symbols", lambda: {"CLF", "STP", "LIN", "MIX"})

    assert parse_emissions.main() == 0
    return out_csv


def _write_protocol(path: Path, coingecko_id: str, symbol: str, body: str) -> None:
    path.write_text(
        f"""
        const protocol: Protocol = {{
            meta: {{
                token: "coingecko:{coingecko_id}",
                total: 1000,
            }},
            categories: {{
                insiders: ["team"],
            }},
            {body}
        }};
        """,
        encoding="utf-8",
    )


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def _vesting_types_for(rows: list[dict[str, str]], token: str) -> list[str]:
    return [row["vesting_type"] for row in rows if row["token"] == token]
