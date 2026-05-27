from __future__ import annotations

import warnings

import pandas as pd
import pytest


def _pool(wallets: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "wallet": wallets,
            "account_value": [10_000.0 + i for i in range(len(wallets))],
            "realized_loss_rate_90d": [0.60] * len(wallets),
            "leverage_avg_90d": [8.0] * len(wallets),
            "n_trades_90d": [80] * len(wallets),
            "size_cv_90d": [0.45] * len(wallets),
            "eligible_at": [pd.Timestamp("2026-05-26T00:00:00Z")] * len(wallets),
        }
    )


def test_exclude_bots_from_pool_threshold_is_inclusive_at_default_boundary() -> None:
    from wallet_pool.bot_exclusion import BotExclusionConfig, exclude_bots_from_pool

    wallet_pool = _pool(["0x49", "0x50", "0x51"])
    bot_scores = {"0x49": 0.49, "0x50": 0.50, "0x51": 0.51}

    clean_pool, excluded = exclude_bots_from_pool(
        wallet_pool,
        bot_scores,
        config=BotExclusionConfig(),
    )

    assert clean_pool["wallet"].tolist() == ["0x49"]
    assert excluded["wallet"].tolist() == ["0x50", "0x51"]
    assert excluded["bot_score"].tolist() == [0.50, 0.51]
    assert excluded["reason"].tolist() == ["bot_score", "bot_score"]


def test_exclude_bots_from_pool_uses_custom_threshold() -> None:
    from wallet_pool.bot_exclusion import BotExclusionConfig, exclude_bots_from_pool

    clean_pool, excluded = exclude_bots_from_pool(
        _pool(["0x60", "0x70"]),
        {"0x60": 0.60, "0x70": 0.70},
        config=BotExclusionConfig(bot_score_threshold=0.70),
    )

    assert clean_pool["wallet"].tolist() == ["0x60"]
    assert excluded["wallet"].tolist() == ["0x70"]


def test_exclude_bots_from_pool_accepts_bot_score_dataframe() -> None:
    from wallet_pool.bot_exclusion import BotExclusionConfig, exclude_bots_from_pool

    scores = pd.DataFrame(
        {
            "wallet": ["0xA", "0xB", "0xC"],
            "bot_score": [0.20, 0.80, 0.10],
        }
    )

    clean_pool, excluded = exclude_bots_from_pool(
        _pool(["0xa", "0xb", "0xc"]),
        scores,
        config=BotExclusionConfig(),
    )

    assert clean_pool["wallet"].tolist() == ["0xa", "0xc"]
    assert excluded["wallet"].tolist() == ["0xb"]
    assert excluded["bot_score"].tolist() == [0.80]


def test_exclude_bots_from_pool_keeps_wallets_without_bot_scores() -> None:
    from wallet_pool.bot_exclusion import BotExclusionConfig, exclude_bots_from_pool

    clean_pool, excluded = exclude_bots_from_pool(
        _pool(["0xscored", "0xmissing"]),
        {"0xscored": 0.80},
        config=BotExclusionConfig(),
    )

    assert clean_pool["wallet"].tolist() == ["0xmissing"]
    assert excluded["wallet"].tolist() == ["0xscored"]


def test_exclude_bots_from_pool_keeps_nan_scores_in_clean_pool() -> None:
    from wallet_pool.bot_exclusion import BotExclusionConfig, exclude_bots_from_pool

    scores = pd.DataFrame(
        {
            "wallet": ["0xnan", "0xbot"],
            "bot_score": [float("nan"), 0.80],
        }
    )

    clean_pool, excluded = exclude_bots_from_pool(
        _pool(["0xnan", "0xbot"]),
        scores,
        config=BotExclusionConfig(),
    )

    assert clean_pool["wallet"].tolist() == ["0xnan"]
    assert excluded["wallet"].tolist() == ["0xbot"]


def test_exclude_bots_from_pool_keeps_nan_scores_at_minimum_threshold() -> None:
    from wallet_pool.bot_exclusion import BotExclusionConfig, exclude_bots_from_pool

    clean_pool, excluded = exclude_bots_from_pool(
        _pool(["0xnan"]),
        {"0xnan": float("nan")},
        config=BotExclusionConfig(bot_score_threshold=0.0001),
    )

    assert clean_pool["wallet"].tolist() == ["0xnan"]
    assert excluded.empty


def test_exclude_bots_from_pool_empty_pool_returns_empty_frames() -> None:
    from wallet_pool.bot_exclusion import BotExclusionConfig, exclude_bots_from_pool

    clean_pool, excluded = exclude_bots_from_pool(
        _pool([]),
        {"0xbot": 0.90},
        config=BotExclusionConfig(),
    )

    assert clean_pool.empty
    assert list(clean_pool.columns) == list(_pool([]).columns)
    assert excluded.empty
    assert list(excluded.columns) == ["wallet", "bot_score", "reason"]


def test_funding_source_graph_links_wallets_that_share_a_source() -> None:
    from wallet_pool.bot_exclusion import funding_source_graph

    graph = funding_source_graph(
        {
            "0xa": "source-1",
            "0xb": "source-1",
            "0xc": "source-2",
        }
    )

    assert graph["0xa"] == {"0xb"}
    assert graph["0xb"] == {"0xa"}
    assert graph["0xc"] == set()


def test_funding_source_graph_retains_isolated_wallets() -> None:
    from wallet_pool.bot_exclusion import funding_source_graph

    graph = funding_source_graph({"0xsolo": "source-1", "0xother": "source-2"})

    assert graph["0xsolo"] == set()
    assert graph["0xother"] == set()


def test_funding_source_graph_ignores_missing_sources() -> None:
    from wallet_pool.bot_exclusion import funding_source_graph

    graph = funding_source_graph({"0xsolo": None, "0xother": ""})

    assert graph["0xsolo"] == set()
    assert graph["0xother"] == set()


def test_funding_source_graph_strict_less_than_as_of() -> None:
    from wallet_pool.bot_exclusion import funding_source_graph

    as_of = pd.Timestamp("2026-05-26T00:00:00Z")
    sources = pd.DataFrame(
        {
            "wallet": ["0xa", "0xb", "0xc"],
            "from_address": ["src-1", "src-1", "src-2"],
            "first_funded_at": [
                as_of - pd.Timedelta(seconds=1),
                as_of,
                as_of - pd.Timedelta(days=1),
            ],
        }
    )

    graph = funding_source_graph(sources, as_of=as_of)

    assert graph["0xa"] == set()
    assert "0xb" not in graph
    assert graph["0xc"] == set()


def test_funding_source_graph_warns_on_snapshot_mode_with_timestamps() -> None:
    from wallet_pool.bot_exclusion import funding_source_graph

    sources = pd.DataFrame(
        {
            "wallet": ["0xa", "0xb"],
            "from_address": ["src-1", "src-1"],
            "funded_at": [
                pd.Timestamp("2026-05-25T00:00:00Z"),
                pd.Timestamp("2026-05-26T00:00:00Z"),
            ],
        }
    )

    with pytest.warns(RuntimeWarning, match="snapshot mode is walkforward-unsafe"):
        funding_source_graph(sources)


def test_funding_source_graph_silent_without_timestamp_column() -> None:
    from wallet_pool.bot_exclusion import funding_source_graph

    sources = pd.DataFrame(
        {
            "wallet": ["0xa", "0xb"],
            "from_address": ["src-1", "src-1"],
        }
    )

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        funding_source_graph(sources)

    assert caught == []


def test_exclude_funding_source_clusters_excludes_sybil_cluster_at_boundary() -> None:
    from wallet_pool.bot_exclusion import exclude_funding_source_clusters

    wallet_pool = _pool(["0x1", "0x2", "0x3"])
    graph = {
        "0x1": {"0x2", "0x3"},
        "0x2": {"0x1", "0x3"},
        "0x3": {"0x1", "0x2"},
    }

    excluded = exclude_funding_source_clusters(wallet_pool, graph, max_shared=3)

    assert excluded["wallet"].tolist() == ["0x1", "0x2", "0x3"]
    assert excluded["reason"].tolist() == ["funding_source_cluster"] * 3


def test_exclude_funding_source_clusters_excludes_five_wallet_sybil_cluster() -> None:
    from wallet_pool.bot_exclusion import exclude_funding_source_clusters

    wallet_pool = _pool(["0x1", "0x2", "0x3", "0x4", "0x5"])
    graph = {
        "0x1": {"0x2", "0x3", "0x4", "0x5"},
        "0x2": {"0x1", "0x3", "0x4", "0x5"},
        "0x3": {"0x1", "0x2", "0x4", "0x5"},
        "0x4": {"0x1", "0x2", "0x3", "0x5"},
        "0x5": {"0x1", "0x2", "0x3", "0x4"},
    }

    excluded = exclude_funding_source_clusters(wallet_pool, graph, max_shared=3)

    assert excluded["wallet"].tolist() == ["0x1", "0x2", "0x3", "0x4", "0x5"]
    assert excluded["reason"].tolist() == ["funding_source_cluster"] * 5


def test_exclude_funding_source_clusters_keeps_small_clusters_below_threshold() -> None:
    from wallet_pool.bot_exclusion import exclude_funding_source_clusters

    wallet_pool = _pool(["0xa", "0xb", "0xc"])
    graph = {
        "0xa": {"0xb"},
        "0xb": {"0xa"},
        "0xc": set(),
    }

    excluded = exclude_funding_source_clusters(wallet_pool, graph, max_shared=3)

    assert excluded.empty
    assert list(excluded.columns) == [
        "wallet",
        "account_value",
        "realized_loss_rate_90d",
        "leverage_avg_90d",
        "n_trades_90d",
        "size_cv_90d",
        "eligible_at",
        "reason",
    ]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"bot_score_threshold": -0.01},
        {"bot_score_threshold": 0.0},
        {"bot_score_threshold": 1.01},
        {"bot_score_threshold": True},
        {"funding_source_graph_max_shared": 1},
        {"funding_source_graph_max_shared": 0},
        {"funding_source_graph_max_shared": -1},
        {"funding_source_graph_max_shared": 1.5},
    ],
)
def test_bot_exclusion_config_rejects_invalid_inputs(kwargs: dict) -> None:
    from wallet_pool.bot_exclusion import BotExclusionConfig

    with pytest.raises(ValueError):
        BotExclusionConfig(**kwargs)


def test_bot_exclusion_config_accepts_inclusive_upper_bound() -> None:
    from wallet_pool.bot_exclusion import BotExclusionConfig

    config = BotExclusionConfig(bot_score_threshold=1.0, funding_source_graph_max_shared=2)

    assert config.bot_score_threshold == 1.0
    assert config.funding_source_graph_max_shared == 2
