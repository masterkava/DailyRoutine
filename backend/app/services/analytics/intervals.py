"""Pure interval maths for routine-vs-reality comparisons. No database access."""

from collections import defaultdict
from collections.abc import Hashable, Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta


@dataclass(frozen=True, slots=True)
class Span:
    start: datetime
    end: datetime
    category_id: Hashable

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError("Span end is before start")

    @property
    def minutes(self) -> float:
        return (self.end - self.start).total_seconds() / 60


@dataclass(frozen=True, slots=True)
class CategoryComparison:
    planned: int
    actual: int
    aligned: int


def overlap_minutes(
    a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime
) -> float:
    """Length of the intersection of [a_start, a_end) and [b_start, b_end) in minutes."""
    seconds = (min(a_end, b_end) - max(a_start, b_start)).total_seconds()
    return max(seconds, 0.0) / 60


def _merge(spans: Iterable[Span]) -> list[tuple[datetime, datetime]]:
    """Union of spans as sorted, non-overlapping (start, end) pairs."""
    merged: list[list[datetime]] = []
    for s in sorted(spans, key=lambda s: s.start):
        if s.end <= s.start:
            continue
        if merged and s.start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], s.end)
        else:
            merged.append([s.start, s.end])
    return [(a, b) for a, b in merged]


def _total(intervals: list[tuple[datetime, datetime]]) -> float:
    return sum((b - a).total_seconds() for a, b in intervals) / 60


def _intersection_minutes(
    xs: list[tuple[datetime, datetime]], ys: list[tuple[datetime, datetime]]
) -> float:
    """Two-pointer sweep over two sorted, disjoint interval lists."""
    i = j = 0
    total = 0.0
    while i < len(xs) and j < len(ys):
        total += overlap_minutes(xs[i][0], xs[i][1], ys[j][0], ys[j][1])
        if xs[i][1] <= ys[j][1]:
            i += 1
        else:
            j += 1
    return total


def compare_day(
    planned: Iterable[Span], actual: Iterable[Span]
) -> dict[Hashable, CategoryComparison]:
    """Per category: minutes planned, minutes actually spent, and minutes where the
    actual activity happened during a planned block of the *same* category.

    Overlapping spans within one side and category are unioned first, so nothing is
    double counted. Results are rounded to whole minutes.
    """
    by_cat_planned: dict[Hashable, list[Span]] = defaultdict(list)
    by_cat_actual: dict[Hashable, list[Span]] = defaultdict(list)
    for s in planned:
        by_cat_planned[s.category_id].append(s)
    for s in actual:
        by_cat_actual[s.category_id].append(s)

    result: dict[Hashable, CategoryComparison] = {}
    for cat in by_cat_planned.keys() | by_cat_actual.keys():
        p = _merge(by_cat_planned.get(cat, []))
        a = _merge(by_cat_actual.get(cat, []))
        result[cat] = CategoryComparison(
            planned=round(_total(p)),
            actual=round(_total(a)),
            aligned=round(_intersection_minutes(p, a)),
        )
    return result


def streaks(hit_days: Iterable[date], today: date) -> tuple[int, int]:
    """(current, best) runs of consecutive hit days.

    The current streak counts back from today; if today isn't a hit yet it counts
    back from yesterday instead, since the day is still in progress.
    """
    days = sorted({d for d in hit_days if d <= today})
    if not days:
        return 0, 0

    best = run = 1
    for prev, nxt in zip(days, days[1:], strict=False):
        run = run + 1 if nxt - prev == timedelta(days=1) else 1
        best = max(best, run)

    day_set = set(days)
    cursor = today if today in day_set else today - timedelta(days=1)
    current = 0
    while cursor in day_set:
        current += 1
        cursor -= timedelta(days=1)
    return current, best
