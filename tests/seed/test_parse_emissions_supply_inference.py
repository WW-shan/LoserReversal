from __future__ import annotations

from pathlib import Path

from data.seed import parse_emissions
from data.seed.parse_emissions import Coin


def test_primary_supply_key_used_when_present():
    actual = parse_emissions.infer_total_supply(
        {"totalSupply": 1000, "qty": 5},
        max_manual_amount=10,
    )

    assert actual == 1000


def test_fallback_used_only_when_plausible():
    actual = parse_emissions.infer_total_supply({"qty": 1000}, max_manual_amount=10)

    assert actual == 1000


def test_fallback_rejected_when_implausibly_small(tmp_path: Path):
    protocol_path = tmp_path / "small-token.ts"
    protocol_path.write_text(
        """
        const qty = 5;
        const protocol: Protocol = {
            meta: {
                token: "coingecko:small-token",
            },
            categories: {
                insiders: ["team"],
            },
            team: manualCliff("2026-01-01", 10),
        };
        """,
        encoding="utf-8",
    )
    coin = Coin("small-token", "SML", "Small Token")

    actual = parse_emissions.parse_file(
        protocol_path,
        {"small-token": coin},
        {"SML": [coin]},
        {"SML"},
    )

    assert actual == []
