from __future__ import annotations

from datetime import datetime, timedelta


def walk_forward_splits(
    start: datetime,
    end: datetime,
    n_splits: int = 5,
    mode: str = "expanding",
    min_train_days: int = 90,
    test_days: int = 60,
) -> list[tuple[tuple[datetime, datetime], tuple[datetime, datetime]]]:
    if mode not in {"expanding", "rolling"}:
        raise ValueError("unknown walk-forward mode")
    if n_splits < 1:
        raise ValueError("n_splits must be at least 1")
    if min_train_days < 1:
        raise ValueError("min_train_days must be at least 1")
    if test_days < 1:
        raise ValueError("test_days must be at least 1")

    train_window = timedelta(days=min_train_days)
    test_window = timedelta(days=test_days)
    if start + train_window + n_splits * test_window > end:
        raise ValueError("time range too short for requested splits")

    splits: list[tuple[tuple[datetime, datetime], tuple[datetime, datetime]]] = []

    for split in range(n_splits):
        if mode == "expanding":
            train_start = start
            train_end = start + train_window + split * test_window
        else:
            train_start = start + split * test_window
            train_end = train_start + train_window

        test_start = train_end
        test_end = test_start + test_window

        splits.append(((train_start, train_end), (test_start, test_end)))

    return splits
