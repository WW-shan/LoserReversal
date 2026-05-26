"""Phase 2.5 academic anti-alpha wallet pool."""

from __future__ import annotations

from wallet_pool.academic_pool import (
    FUNNEL_AXES,
    LOOKBACK_DAYS,
    MAX_ACCOUNT_VALUE,
    MIN_ACCOUNT_VALUE,
    MIN_LEVERAGE,
    MIN_LOSS_RATE,
    MIN_N_TRADES,
    MIN_SIZE_CV,
    POOL_COLUMNS,
    build_academic_pool,
    build_academic_pool_with_funnel,
    compute_wallet_metrics,
    is_academic_anti_alpha,
)


__all__ = [
    "FUNNEL_AXES",
    "LOOKBACK_DAYS",
    "MAX_ACCOUNT_VALUE",
    "MIN_ACCOUNT_VALUE",
    "MIN_LEVERAGE",
    "MIN_LOSS_RATE",
    "MIN_N_TRADES",
    "MIN_SIZE_CV",
    "POOL_COLUMNS",
    "build_academic_pool",
    "build_academic_pool_with_funnel",
    "compute_wallet_metrics",
    "is_academic_anti_alpha",
]
