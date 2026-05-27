"""Bot exclusion helpers for the academic wallet pool."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Mapping
import warnings

import pandas as pd


@dataclass(frozen=True, slots=True)
class BotExclusionConfig:
    """Inclusive bot and sybil-cluster thresholds for pool exclusion.

    Validation is intentionally strict (raise rather than clamp) so library
    callers cannot bypass the bounds enforced by the CLI in
    ``scripts/build_clean_wallet_pool.py``. See ``.ccg/spec/backend/index.md``
    rule "Threshold parameter validation".
    """

    bot_score_threshold: float = 0.5
    funding_source_graph_max_shared: int = 3

    def __post_init__(self) -> None:
        threshold = self.bot_score_threshold
        if not isinstance(threshold, (int, float)) or isinstance(threshold, bool):
            raise ValueError(
                f"bot_score_threshold must be a float in (0.0, 1.0]; got {threshold!r}"
            )
        if not 0.0 < float(threshold) <= 1.0:
            raise ValueError(
                f"bot_score_threshold must be in (0.0, 1.0]; got {threshold!r}"
            )
        max_shared = self.funding_source_graph_max_shared
        if type(max_shared) is not int or max_shared < 2:
            raise ValueError(
                "funding_source_graph_max_shared must be an int >= 2 "
                f"(cluster size of 1 trivially excludes every wallet); got {max_shared!r}"
            )


def exclude_bots_from_pool(
    wallet_pool: pd.DataFrame,
    bot_scores: Mapping[str, float] | pd.DataFrame,
    *,
    config: BotExclusionConfig,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split a wallet pool into clean and score-excluded wallets.

    Wallets missing from ``bot_scores`` or carrying NaN scores are left in
    ``clean_pool``; production pipelines that fail to score a wallet should
    exclude those failures before treating the pool as clean.
    """

    frame = wallet_pool.copy()
    if "wallet" in frame.columns:
        frame["wallet"] = frame["wallet"].astype("string").str.lower()
    if frame.empty:
        return frame.reset_index(drop=True), _empty_excluded()

    scores = _coerce_bot_scores(bot_scores)
    if scores.empty:
        return frame.reset_index(drop=True), _empty_excluded()

    merged = frame.merge(scores, on="wallet", how="left")
    threshold = float(config.bot_score_threshold)
    bot_score = merged["bot_score"]
    excluded_mask = bot_score.notna() & (bot_score >= threshold)

    excluded = merged.loc[excluded_mask, ["wallet", "bot_score"]].copy()
    excluded["reason"] = "bot_score"
    clean = merged.loc[~excluded_mask, frame.columns].copy()

    return clean.reset_index(drop=True), excluded.reset_index(drop=True)


def funding_source_graph(
    wallet_funding_sources: Mapping[str, object] | pd.DataFrame,
    *,
    as_of: pd.Timestamp | None = None,
) -> dict[str, set[str]]:
    """Build wallet adjacency sets from shared first-funding-source addresses.

    DataFrame inputs with a ``first_funded_at``, ``funded_at``, or ``timestamp``
    column are filtered to rows strictly before ``as_of`` for point-in-time
    queries. Passing ``as_of=None`` keeps current snapshot behavior and warns
    when timestamp data is available because that mode is walkforward-unsafe.
    """

    wallet_funding_sources = _funding_sources_for_as_of(
        wallet_funding_sources,
        as_of=as_of,
        warn_snapshot=True,
    )
    records, _ = _coerce_funding_sources(wallet_funding_sources)
    wallets = sorted({wallet for wallet, _ in records})
    parent = _parent_map(wallets)

    by_source: dict[str, set[str]] = defaultdict(set)
    for wallet, source in records:
        if source is not None:
            by_source[source].add(wallet)

    for source_wallets in by_source.values():
        ordered = sorted(source_wallets)
        for wallet in ordered[1:]:
            _union(parent, ordered[0], wallet)

    components = _components(parent)
    return {
        wallet: set(components[_find(parent, wallet)] - {wallet})
        for wallet in wallets
    }


def exclude_funding_source_clusters(
    wallet_pool: pd.DataFrame,
    funding_graph: Mapping[str, set[str]],
    *,
    config: BotExclusionConfig | None = None,
    max_shared: int | None = None,
) -> pd.DataFrame:
    """Return pool rows belonging to funding-source clusters.

    ``max_shared`` is a legacy keyword; pass ``config=BotExclusionConfig(...)``
    instead.
    """

    if config is not None:
        threshold = config.funding_source_graph_max_shared
        if max_shared is not None:
            warnings.warn(
                "max_shared is deprecated and ignored when config is provided",
                DeprecationWarning,
                stacklevel=2,
            )
    elif max_shared is not None:
        warnings.warn(
            "max_shared is deprecated; pass config=BotExclusionConfig(...) instead",
            DeprecationWarning,
            stacklevel=2,
        )
        threshold = max_shared
    else:
        raise TypeError("exclude_funding_source_clusters requires config or max_shared")

    frame = wallet_pool.copy()
    if "wallet" in frame.columns:
        frame["wallet"] = frame["wallet"].astype("string").str.lower()
    if frame.empty:
        return _empty_cluster_excluded(frame)

    parent = _parent_map(_wallets_from_graph(funding_graph))
    for wallet, related_wallets in funding_graph.items():
        wallet_key = _normalize_wallet(wallet)
        for related_wallet in related_wallets:
            related_key = _normalize_wallet(related_wallet)
            _union(parent, wallet_key, related_key)

    components = _components(parent)
    component_sizes = {
        root: len(members)
        for root, members in components.items()
    }

    def _is_cluster_wallet(wallet: str) -> bool:
        wallet_key = _normalize_wallet(wallet)
        if wallet_key not in parent:
            return False
        return component_sizes[_find(parent, wallet_key)] >= threshold

    excluded = frame.loc[frame["wallet"].map(_is_cluster_wallet)].copy()
    if excluded.empty:
        return _empty_cluster_excluded(frame)
    excluded["reason"] = "funding_source_cluster"
    return excluded.reset_index(drop=True)


def _coerce_bot_scores(bot_scores: Mapping[str, float] | pd.DataFrame) -> pd.DataFrame:
    if isinstance(bot_scores, pd.DataFrame):
        if bot_scores.empty:
            return pd.DataFrame({"wallet": pd.Series(dtype="string"), "bot_score": pd.Series(dtype="float64")})
        frame = bot_scores.copy()
        wallet_column = _find_column(frame.columns, "wallet")
        score_column = _find_column(frame.columns, "bot_score")
        if wallet_column is None or score_column is None:
            raise ValueError("bot_scores dataframe must contain wallet and bot_score columns")
        frame = frame[[wallet_column, score_column]].rename(
            columns={wallet_column: "wallet", score_column: "bot_score"}
        )
    else:
        frame = pd.DataFrame(
            {
                "wallet": list(bot_scores.keys()),
                "bot_score": list(bot_scores.values()),
            }
        )

    frame["wallet"] = frame["wallet"].astype("string").str.lower()
    frame["bot_score"] = pd.to_numeric(frame["bot_score"], errors="coerce").astype("float64")
    frame = frame.dropna(subset=["wallet"])
    conflicting_scores = frame.groupby("wallet")["bot_score"].nunique(dropna=True)
    conflicts = sorted(conflicting_scores[conflicting_scores > 1].index.tolist())
    if conflicts:
        raise ValueError(f"bot_scores contains conflicting values for wallets: {conflicts}")
    frame = frame.drop_duplicates(subset=["wallet"], keep="last")
    return frame.reset_index(drop=True)


def _coerce_funding_sources(
    wallet_funding_sources: Mapping[str, object] | pd.DataFrame,
) -> tuple[list[tuple[str, str | None]], int]:
    if isinstance(wallet_funding_sources, pd.DataFrame):
        if wallet_funding_sources.empty:
            return [], 0
        frame = wallet_funding_sources.copy()
        wallet_column = _find_column(frame.columns, "wallet")
        source_column = _find_first_column(
            frame.columns,
            ("from_address", "funding_source", "first_funding_source", "source"),
        )
        if wallet_column is None or source_column is None:
            raise ValueError("wallet_funding_sources must contain wallet and funding source columns")
        rows = zip(frame[wallet_column].tolist(), frame[source_column].tolist(), strict=False)
    else:
        rows = wallet_funding_sources.items()

    records: list[tuple[str, str | None]] = []
    missing_source_count = 0
    for wallet, source in rows:
        wallet_key = _normalize_wallet(wallet)
        if not wallet_key:
            continue
        source_key = _normalize_source(source)
        if source_key is None:
            missing_source_count += 1
        records.append((wallet_key, source_key))
    return records, missing_source_count


def _find_column(columns: pd.Index, expected: str) -> str | None:
    for column in columns:
        if str(column).lower() == expected:
            return str(column)
    return None


def _find_first_column(columns: pd.Index, candidates: tuple[str, ...]) -> str | None:
    for candidate in candidates:
        column = _find_column(columns, candidate)
        if column is not None:
            return column
    return None


def _funding_sources_for_as_of(
    wallet_funding_sources: Mapping[str, object] | pd.DataFrame,
    *,
    as_of: pd.Timestamp | None,
    warn_snapshot: bool,
) -> Mapping[str, object] | pd.DataFrame:
    if not isinstance(wallet_funding_sources, pd.DataFrame):
        return wallet_funding_sources

    timestamp_column = _find_first_column(
        wallet_funding_sources.columns,
        ("first_funded_at", "funded_at", "timestamp"),
    )
    if timestamp_column is None:
        return wallet_funding_sources

    if as_of is None:
        if warn_snapshot:
            warnings.warn(
                "funding_source_graph in snapshot mode is walkforward-unsafe; "
                "pass as_of for point-in-time queries",
                RuntimeWarning,
                stacklevel=2,
            )
        return wallet_funding_sources

    as_of_ts = _coerce_as_of_timestamp(as_of)
    timestamps = pd.to_datetime(
        wallet_funding_sources[timestamp_column],
        utc=True,
        errors="coerce",
    )
    return wallet_funding_sources.loc[timestamps < as_of_ts].copy()


def _coerce_as_of_timestamp(value: pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _normalize_wallet(value: object) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip().lower()


def _normalize_source(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    source = str(value).strip().lower()
    return source or None


def _parent_map(wallets: list[str] | set[str]) -> dict[str, str]:
    return {wallet: wallet for wallet in wallets}


def _find(parent: dict[str, str], wallet: str) -> str:
    parent.setdefault(wallet, wallet)
    while parent[wallet] != wallet:
        parent[wallet] = parent[parent[wallet]]
        wallet = parent[wallet]
    return wallet


def _union(parent: dict[str, str], left: str, right: str) -> None:
    left_root = _find(parent, left)
    right_root = _find(parent, right)
    if left_root != right_root:
        parent[right_root] = left_root


def _components(parent: dict[str, str]) -> dict[str, set[str]]:
    components: dict[str, set[str]] = defaultdict(set)
    for wallet in list(parent):
        components[_find(parent, wallet)].add(wallet)
    return components


def _wallets_from_graph(funding_graph: Mapping[str, set[str]]) -> set[str]:
    wallets: set[str] = set()
    for wallet, related_wallets in funding_graph.items():
        wallet_key = _normalize_wallet(wallet)
        if wallet_key:
            wallets.add(wallet_key)
        wallets.update(_normalize_wallet(related) for related in related_wallets)
    return {wallet for wallet in wallets if wallet}


def _empty_excluded() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "wallet": pd.Series(dtype="string"),
            "bot_score": pd.Series(dtype="float64"),
            "reason": pd.Series(dtype="string"),
        }
    )


def _empty_cluster_excluded(wallet_pool: pd.DataFrame) -> pd.DataFrame:
    frame = wallet_pool.iloc[0:0].copy()
    frame["reason"] = pd.Series(dtype="string")
    return frame
