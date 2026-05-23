from __future__ import annotations

from pathlib import Path

from data.seed import parse_emissions
from data.seed.parse_emissions import Coin


def test_parse_emissions_prints_drop_reason_counters(monkeypatch, tmp_path: Path, capsys):
    _write_protocol(
        tmp_path / "valid-token.ts",
        """
        meta: { token: "coingecko:valid-token", total: 1000 },
        categories: { insiders: ["team"] },
        team: manualCliff("2026-01-01", 20),
        """,
    )
    _write_protocol(
        tmp_path / "no-supply-token.ts",
        """
        meta: { token: "coingecko:no-supply-token" },
        categories: { insiders: ["team"] },
        team: manualCliff("2026-01-01", 20),
        """,
    )
    _write_protocol(
        tmp_path / "missing-coin-token.ts",
        """
        meta: { token: "coingecko:missing-coin-token", total: 1000 },
        categories: { insiders: ["team"] },
        team: manualCliff("2026-01-01", 20),
        """,
    )
    _write_protocol(
        tmp_path / "no-categories-token.ts",
        """
        meta: { token: "coingecko:no-categories-token", total: 1000 },
        team: manualCliff("2026-01-01", 20),
        """,
    )
    _write_protocol(
        tmp_path / "out-window-token.ts",
        """
        meta: { token: "coingecko:out-window-token", total: 1000 },
        categories: { insiders: ["team"] },
        team: manualCliff("2022-12-31", 20),
        """,
    )
    _write_protocol(
        tmp_path / "out-pct-token.ts",
        """
        meta: { token: "coingecko:out-pct-token", total: 1000 },
        categories: { insiders: ["team"] },
        team: manualCliff("2026-01-01", 400),
        """,
    )
    coins = {
        "valid-token": Coin("valid-token", "VAL", "Valid Token"),
        "no-supply-token": Coin("no-supply-token", "NOS", "No Supply Token"),
        "no-categories-token": Coin("no-categories-token", "NOC", "No Categories Token"),
        "out-window-token": Coin("out-window-token", "OUT", "Out Window Token"),
        "out-pct-token": Coin("out-pct-token", "PCT", "Out Pct Token"),
    }
    by_symbol = {coin.symbol: [coin] for coin in coins.values()}
    monkeypatch.setattr(parse_emissions, "PROTOCOLS_DIR", tmp_path)
    monkeypatch.setattr(parse_emissions, "OUT_CSV", tmp_path / "unlocks.csv")
    monkeypatch.setattr(parse_emissions, "load_coins", lambda: (coins, by_symbol))
    monkeypatch.setattr(parse_emissions, "hyperliquid_symbols", lambda: set(by_symbol))

    assert parse_emissions.main() == 0

    out = capsys.readouterr().out
    assert "protocols_scanned: 6" in out
    assert "protocols_parsed: 3" in out
    assert "protocols_dropped_no_supply: 1" in out
    assert "protocols_dropped_no_coin_match: 1" in out
    assert "protocols_dropped_no_categories: 1" in out
    assert "events_emitted_total: 1" in out
    assert "events_dropped_out_of_window: 1" in out
    assert "events_dropped_out_of_pct_range: 1" in out


def _write_protocol(path: Path, body: str) -> None:
    path.write_text(
        f"""
        const protocol: Protocol = {{
            {body}
        }};
        """,
        encoding="utf-8",
    )
