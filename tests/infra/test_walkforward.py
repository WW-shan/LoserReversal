from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from infra.backtest.walkforward import walk_forward_splits


START = datetime(2026, 1, 1, tzinfo=timezone.utc)
END = datetime(2026, 6, 1, tzinfo=timezone.utc)


def test_expanding_mode_train_end_sequence_is_strictly_increasing():
    splits = walk_forward_splits(
        START,
        END,
        n_splits=4,
        mode="expanding",
        min_train_days=30,
        test_days=10,
    )

    train_ends = [train[1] for train, _test in splits]

    assert all(later > earlier for earlier, later in zip(train_ends, train_ends[1:]))


def test_rolling_mode_train_window_size_is_constant():
    splits = walk_forward_splits(
        START,
        END,
        n_splits=4,
        mode="rolling",
        min_train_days=30,
        test_days=10,
    )

    durations = [train[1] - train[0] for train, _test in splits]

    assert set(durations) == {timedelta(days=30)}


@pytest.mark.parametrize("mode", ["expanding", "rolling"])
def test_each_split_has_no_gap_or_overlap_between_train_and_test(mode: str):
    splits = walk_forward_splits(
        START,
        END,
        n_splits=4,
        mode=mode,
        min_train_days=30,
        test_days=10,
    )

    assert all(test[0] == train[1] for train, test in splits)


def test_returns_requested_number_of_splits():
    splits = walk_forward_splits(
        START,
        END,
        n_splits=4,
        mode="expanding",
        min_train_days=30,
        test_days=10,
    )

    assert len(splits) == 4


def test_last_split_test_end_does_not_exceed_end():
    splits = walk_forward_splits(
        START,
        END,
        n_splits=4,
        mode="rolling",
        min_train_days=30,
        test_days=10,
    )

    assert splits[-1][1][1] <= END


def test_span_too_short_to_fit_requested_splits_raises():
    with pytest.raises(ValueError):
        walk_forward_splits(
            START,
            START + timedelta(days=59),
            n_splits=3,
            mode="expanding",
            min_train_days=30,
            test_days=10,
        )


def test_invalid_mode_raises():
    with pytest.raises(ValueError):
        walk_forward_splits(
            START,
            END,
            n_splits=4,
            mode="invalid",
            min_train_days=30,
            test_days=10,
        )
