"""Bot exclusion helpers for the academic wallet pool."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Mapping

import pandas as pd


@dataclass(frozen=True, slots=True)
class BotExclusionConfig:
    bot_score_threshold: float = 0.5
    funding_source_graph_max_shared: int = 3


def exclude_bots_from_pool(
    wallet_pool: pd.DataFrame,
    bot_scores: Mapping[str, float] | pd.DataFrame,
    *,
    config: BotExclusionConfig,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if wallet_pool.empty:
        return wallet_pool.copy(), _empty_excluded()

    frame = wallet_pool.copy()
    frame["wallet"] = frame["wallet"].astype("string").str.lower()

    scores = _coerce_bot_scores(bot_scores)
    if scores.empty:
        return frame.reset_index(drop=True), _empty_excluded()

    merged = frame.merge(scores, on="wallet", how="left")
    threshold = float(config.bot_score_threshold)
    excluded_mask = merged["bot_score"].fillna(-1.0) >= threshold - 1e-12

    excluded = merged.loc[excluded_mask, ["wallet", "bot_score"]].copy()
    excluded["reason"] = "bot_score"
    clean = merged.loc[~excluded_mask, frame.columns].copy()

    return clean.reset_index(drop=True), excluded.reset_index(drop=True)


def funding_source_graph(
    wallet_funding_sources: Mapping[str, object] | pd.DataFrame,
) -> dict[str, set[str]]:
    records = _coerce_funding_sources(wallet_funding_sources)
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
    max_shared: int,
) -> pd.DataFrame:
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
        return component_sizes[_find(parent, wallet_key)] >= max_shared

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
    frame = frame.drop_duplicates(subset=["wallet"], keep="last")
    return frame.reset_index(drop=True)


def _coerce_funding_sources(
    wallet_funding_sources: Mapping[str, object] | pd.DataFrame,
) -> list[tuple[str, str | None]]:
    if isinstance(wallet_funding_sources, pd.DataFrame):
        if wallet_funding_sources.empty:
            return []
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
    for wallet, source in rows:
        wallet_key = _normalize_wallet(wallet)
        if not wallet_key:
            continue
        records.append((wallet_key, _normalize_source(source)))
    return records


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
