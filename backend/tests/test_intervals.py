from datetime import UTC, date, datetime, timedelta

import pytest

from app.services.analytics.intervals import (
    CategoryComparison,
    Span,
    compare_day,
    overlap_minutes,
    streaks,
)


def at(hour: int, minute: int = 0, day: int = 26) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=UTC)


def s(cat: str, start: datetime, end: datetime) -> Span:
    return Span(start=start, end=end, category_id=cat)


class TestOverlapMinutes:
    def test_partial(self):
        assert overlap_minutes(at(9), at(11), at(10), at(12)) == 60

    def test_contained(self):
        assert overlap_minutes(at(9), at(12), at(10), at(10, 30)) == 30

    def test_touching_is_zero(self):
        assert overlap_minutes(at(9), at(10), at(10), at(11)) == 0

    def test_disjoint_is_zero(self):
        assert overlap_minutes(at(9), at(10), at(11), at(12)) == 0

    def test_across_midnight(self):
        assert overlap_minutes(at(23), at(7, day=27), at(6, day=27), at(8, day=27)) == 60


class TestSpan:
    def test_rejects_backwards(self):
        with pytest.raises(ValueError):
            Span(start=at(10), end=at(9), category_id="x")

    def test_minutes(self):
        assert s("x", at(9), at(10, 15)).minutes == 75


class TestCompareDay:
    def test_perfect_day(self):
        plan = [s("work", at(9), at(17))]
        assert compare_day(plan, plan) == {"work": CategoryComparison(480, 480, 480)}

    def test_shifted_and_mixed(self):
        planned = [s("work", at(9), at(17)), s("gym", at(18), at(19))]
        actual = [
            s("work", at(10), at(18)),  # started an hour late, stayed an hour late
            s("leisure", at(18), at(19)),  # skipped the gym
        ]
        result = compare_day(planned, actual)
        assert result["work"] == CategoryComparison(planned=480, actual=480, aligned=420)
        assert result["gym"] == CategoryComparison(planned=60, actual=0, aligned=0)
        assert result["leisure"] == CategoryComparison(planned=0, actual=60, aligned=0)

    def test_wrong_category_never_counts_as_aligned(self):
        result = compare_day([s("work", at(9), at(10))], [s("meals", at(9), at(10))])
        assert result["work"].aligned == 0
        assert result["meals"].aligned == 0

    def test_overlapping_spans_are_not_double_counted(self):
        planned = [s("work", at(9), at(12))]
        actual = [s("work", at(9), at(11)), s("work", at(10), at(12))]
        assert compare_day(planned, actual)["work"] == CategoryComparison(180, 180, 180)

    def test_many_fragments(self):
        planned = [s("work", at(9), at(12)), s("work", at(13), at(17))]
        actual = [s("work", at(8), at(9, 30)), s("work", at(11), at(14)), s("work", at(16), at(18))]
        # aligned: 9-9:30 (30) + 11-12 (60) + 13-14 (60) + 16-17 (60)
        assert compare_day(planned, actual)["work"] == CategoryComparison(420, 390, 210)

    def test_crossing_midnight(self):
        planned = [s("sleep", at(23), at(7, day=27))]
        actual = [s("sleep", at(0, day=27), at(8, day=27))]
        assert compare_day(planned, actual)["sleep"] == CategoryComparison(480, 480, 420)

    def test_empty(self):
        assert compare_day([], []) == {}


class TestStreaks:
    today = date(2026, 10, 26)

    def days_ago(self, *offsets: int) -> list[date]:
        return [self.today - timedelta(days=o) for o in offsets]

    def test_empty(self):
        assert streaks([], self.today) == (0, 0)

    def test_current_includes_today(self):
        assert streaks(self.days_ago(0, 1, 2), self.today) == (3, 3)

    def test_today_not_yet_hit_keeps_streak(self):
        assert streaks(self.days_ago(1, 2), self.today) == (2, 2)

    def test_gap_breaks_current(self):
        assert streaks(self.days_ago(2, 3, 4, 5), self.today) == (0, 4)

    def test_best_from_the_past(self):
        assert streaks(self.days_ago(0, 1, 5, 6, 7, 8), self.today) == (2, 4)

    def test_duplicates_and_future_days_ignored(self):
        hits = self.days_ago(0, 0, 1) + [self.today + timedelta(days=1)]
        assert streaks(hits, self.today) == (2, 2)
