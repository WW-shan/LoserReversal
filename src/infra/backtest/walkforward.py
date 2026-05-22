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
    if n_splits <= 0:
        return []
    if mode not in {"expanding", "rolling"}:
        raise ValueError("unknown walk-forward mode")

    train_window = timedelta(days=min_train_days)
    test_window = timedelta(days=test_days)
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
        if train_start < start or test_end > end:
            raise ValueError("time range too short for requested splits")

        splits.append(((train_start, train_end), (test_start, test_end)))

    return splits
