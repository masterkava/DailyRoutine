import asyncio
import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import Category, DailyLog, EntrySource, LogEntry, User
from app.services import log_service

MONDAY = date(2026, 10, 26)
DAY = MONDAY.isoformat()
LOG = f"/api/v1/logs/{DAY}"


def ts(hhmm: str, day: int = 26) -> str:
    """UTC ISO timestamp on 2026-10-<day>."""
    return f"2026-10-{day:02d}T{hhmm}:00+00:00"


def span(entry: dict) -> tuple[str, str]:
    """(HH:MM, HH:MM) of an entry, in UTC, for compact assertions."""
    fmt = lambda s: datetime.fromisoformat(s).astimezone(UTC).strftime("%H:%M")  # noqa: E731
    return fmt(entry["started_at"]), fmt(entry["ended_at"])


async def add(user, category_id: str, start: str, end: str, **extra):
    resp = await user.post(
        f"{LOG}/entries",
        json={"category_id": category_id, "started_at": ts(start), "ended_at": ts(end), **extra},
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


async def entries(user) -> list[dict]:
    return (await user.get(LOG)).json()["entries"]


# ----------------------------------------------------------------- log snapshots


async def test_get_log_creates_snapshot_in_user_timezone(make_user):
    user = await make_user(timezone="Asia/Kolkata")
    office = await user.category_id("Office")
    sleep = await user.category_id("Sleep")
    routine = (
        await user.post(
            "/api/v1/routines",
            json={
                "name": "Weekday",
                "blocks": [
                    {
                        "category_id": office,
                        "title": "Work",
                        "start_minute": 600,
                        "duration_minutes": 480,
                    },
                    # 23:00 for 8h: crosses local midnight into Tuesday.
                    {
                        "category_id": sleep,
                        "title": "Sleep",
                        "start_minute": 1380,
                        "duration_minutes": 480,
                    },
                ],
            },
        )
    ).json()

    resp = await user.get(LOG)
    assert resp.status_code == 200, resp.text
    log = resp.json()
    assert log["template_id"] == routine["id"]
    assert log["status"] == "open"
    assert log["entries"] == []

    work, night = log["planned_snapshot"]
    # IST is UTC+05:30.
    assert datetime.fromisoformat(work["start"]) == datetime(2026, 10, 26, 4, 30, tzinfo=UTC)
    assert datetime.fromisoformat(work["end"]) == datetime(2026, 10, 26, 12, 30, tzinfo=UTC)
    assert datetime.fromisoformat(night["start"]) == datetime(2026, 10, 26, 17, 30, tzinfo=UTC)
    assert datetime.fromisoformat(night["end"]) == datetime(2026, 10, 27, 1, 30, tzinfo=UTC)
    assert night["block_id"] == routine["blocks"][1]["id"]
    assert night["category_id"] == sleep

    # Second fetch returns the same log; editing the routine later doesn't rewrite it.
    await user.put(f"/api/v1/routines/{routine['id']}/blocks", json=[])
    again = (await user.get(LOG)).json()
    assert again["id"] == log["id"]
    assert len(again["planned_snapshot"]) == 2


async def test_snapshot_uses_wall_clock_across_dst(make_user):
    user = await make_user(timezone="Europe/London")
    sleep = await user.category_id("Sleep")
    await user.post(
        "/api/v1/routines",
        json={
            "name": "Every day",
            "weekdays": 0b1111111,
            "blocks": [
                {"category_id": sleep, "title": "Wake", "start_minute": 420, "duration_minutes": 30}
            ],
        },
    )
    # BST (UTC+1) on Saturday 24 Oct; GMT from Sunday 25 Oct 2026.
    sat = (await user.get("/api/v1/logs/2026-10-24")).json()["planned_snapshot"][0]
    sun = (await user.get("/api/v1/logs/2026-10-25")).json()["planned_snapshot"][0]
    assert datetime.fromisoformat(sat["start"]) == datetime(2026, 10, 24, 6, 0, tzinfo=UTC)
    assert datetime.fromisoformat(sun["start"]) == datetime(2026, 10, 25, 7, 0, tzinfo=UTC)


async def test_get_log_without_routine_has_empty_plan(make_user):
    user = await make_user()
    log = (await user.get(LOG)).json()
    assert log["template_id"] is None
    assert log["planned_snapshot"] == []


async def test_concurrent_log_creation_returns_one_row(make_user, session_factory):
    await make_user("race@example.com")
    async with session_factory() as a, session_factory() as b:
        user_a = await a.scalar(select(User).where(User.email == "race@example.com"))
        user_b = await b.get(User, user_a.id)

        log_a = await log_service.get_or_create_log(a, user_a, MONDAY)  # insert, uncommitted
        # B's insert blocks on the unique index until A commits, then hits IntegrityError
        # and must fall back to reading A's row.
        task_b = asyncio.create_task(log_service.get_or_create_log(b, user_b, MONDAY))
        await asyncio.sleep(0.3)
        assert not task_b.done()
        await a.commit()
        log_b = await task_b
        await b.commit()

    assert log_a.id == log_b.id
    async with session_factory() as s:
        count = len((await s.scalars(select(DailyLog))).all())
    assert count == 1


async def test_patch_log_and_list(make_user):
    user = await make_user()
    resp = await user.patch(LOG, json={"mood": 4, "energy": 2, "reflection": "ok day"})
    assert resp.status_code == 200
    assert (resp.json()["mood"], resp.json()["energy"]) == (4, 2)
    assert (await user.patch(LOG, json={"mood": 6})).status_code == 422
    closed = await user.patch(LOG, json={"status": "closed"})
    assert closed.json()["status"] == "closed"

    await user.get("/api/v1/logs/2026-10-28")
    listed = await user.get("/api/v1/logs", params={"from": "2026-10-25", "to": "2026-10-27"})
    assert [log["log_date"] for log in listed.json()] == [DAY]
    bad = await user.get("/api/v1/logs", params={"from": "2026-10-27", "to": "2026-10-25"})
    assert bad.status_code == 422


# ----------------------------------------------------------- overlap trimming


async def test_new_entry_fully_covering_old_one_deletes_it(make_user):
    user = await make_user()
    office, gym = await user.category_id("Office"), await user.category_id("Fitness")
    await add(user, office, "10:00", "12:00")
    await add(user, gym, "09:00", "13:00")
    result = await entries(user)
    assert [(span(e), e["category_id"]) for e in result] == [(("09:00", "13:00"), gym)]


async def test_new_entry_inside_old_one_splits_it(make_user):
    user = await make_user()
    office, meals = await user.category_id("Office"), await user.category_id("Meals")
    original = await add(user, office, "10:00", "12:00", note="deep work")
    await add(user, meals, "10:30", "11:00")
    result = await entries(user)
    assert [span(e) for e in result] == [("10:00", "10:30"), ("10:30", "11:00"), ("11:00", "12:00")]
    assert [e["category_id"] for e in result] == [office, meals, office]
    assert result[0]["id"] == original["id"]
    assert result[2]["note"] == "deep work"
    assert result[2]["client_id"] is None


async def test_new_entry_over_left_edge_trims_old_start(make_user):
    user = await make_user()
    office, commute = await user.category_id("Office"), await user.category_id("Commute")
    await add(user, office, "10:00", "12:00")
    await add(user, commute, "09:00", "10:30")
    assert [span(e) for e in await entries(user)] == [("09:00", "10:30"), ("10:30", "12:00")]


async def test_new_entry_over_right_edge_trims_old_end(make_user):
    user = await make_user()
    office, meals = await user.category_id("Office"), await user.category_id("Meals")
    await add(user, office, "10:00", "12:00")
    await add(user, meals, "11:30", "13:00")
    assert [span(e) for e in await entries(user)] == [("10:00", "11:30"), ("11:30", "13:00")]


async def test_new_entry_across_several_old_entries(make_user):
    user = await make_user()
    a, b, c = [await user.category_id(n) for n in ("Sleep", "Meals", "Commute")]
    await add(user, a, "08:00", "09:00")
    await add(user, b, "09:00", "10:00")
    await add(user, c, "10:00", "11:00")
    office = await user.category_id("Office")
    await add(user, office, "08:30", "10:30")
    result = await entries(user)
    assert [span(e) for e in result] == [("08:00", "08:30"), ("08:30", "10:30"), ("10:30", "11:00")]
    assert [e["category_id"] for e in result] == [a, office, c]


async def test_adjacent_entries_are_left_alone(make_user):
    user = await make_user()
    office = await user.category_id("Office")
    await add(user, office, "10:00", "11:00")
    await add(user, office, "11:00", "12:00")
    assert [span(e) for e in await entries(user)] == [("10:00", "11:00"), ("11:00", "12:00")]


async def test_patch_entry_trims_neighbours(make_user):
    user = await make_user()
    office, gym = await user.category_id("Office"), await user.category_id("Fitness")
    first = await add(user, office, "08:00", "09:00")
    await add(user, gym, "09:00", "10:00")

    resp = await user.patch(f"{LOG}/entries/{first['id']}", json={"ended_at": ts("09:30")})
    assert resp.status_code == 200, resp.text
    assert [span(e) for e in await entries(user)] == [("08:00", "09:30"), ("09:30", "10:00")]

    bad = await user.patch(f"{LOG}/entries/{first['id']}", json={"ended_at": ts("07:00")})
    assert bad.status_code == 422


async def test_delete_entry(make_user):
    user = await make_user()
    office = await user.category_id("Office")
    entry = await add(user, office, "08:00", "09:00")
    assert (await user.delete(f"{LOG}/entries/{entry['id']}")).status_code == 204
    assert await entries(user) == []
    assert (await user.delete(f"{LOG}/entries/{entry['id']}")).status_code == 404


async def test_entry_validation(make_user):
    alice = await make_user("alice@example.com")
    bob = await make_user("bob@example.com")
    office = await alice.category_id("Office")
    url = f"{LOG}/entries"

    backwards = {"category_id": office, "started_at": ts("10:00"), "ended_at": ts("09:00")}
    assert (await alice.post(url, json=backwards)).status_code == 422

    naive = {
        "category_id": office,
        "started_at": "2026-10-26T09:00:00",
        "ended_at": "2026-10-26T10:00:00",
    }
    assert (await alice.post(url, json=naive)).status_code == 422

    outside_window = {
        "category_id": office,
        "started_at": ts("23:00", day=25),
        "ended_at": ts("01:00"),
    }
    assert (await alice.post(url, json=outside_window)).status_code == 422

    bobs = await bob.category_id("Office")
    foreign = {"category_id": bobs, "started_at": ts("09:00"), "ended_at": ts("10:00")}
    assert (await alice.post(url, json=foreign)).status_code == 422


async def test_entries_of_different_users_do_not_interfere(make_user):
    alice = await make_user("alice@example.com")
    bob = await make_user("bob@example.com")
    await add(alice, await alice.category_id("Office"), "09:00", "10:00")
    await add(bob, await bob.category_id("Office"), "09:00", "10:00")
    assert len(await entries(alice)) == 1
    assert len(await entries(bob)) == 1


async def test_exclusion_constraint_blocks_overlap_at_db_level(make_user, db):
    """The service never produces overlaps; this proves the DB would refuse one anyway."""
    await make_user()
    user = await db.scalar(select(User))
    log = await log_service.get_or_create_log(db, user, MONDAY)
    category_id = await db.scalar(select(Category.id).where(Category.user_id == user.id))
    for start, end in ((9, 11), (10, 12)):
        db.add(
            LogEntry(
                daily_log_id=log.id,
                user_id=user.id,
                category_id=category_id,
                started_at=datetime(2026, 10, 26, start, tzinfo=UTC),
                ended_at=datetime(2026, 10, 26, end, tzinfo=UTC),
                source=EntrySource.manual,
            )
        )
    await db.flush()  # deferred: nothing raised yet
    with pytest.raises(IntegrityError, match="ex_log_entries_no_overlap"):
        await db.commit()


# ------------------------------------------------------------------ idempotency


async def test_client_id_makes_create_idempotent(make_user):
    user = await make_user()
    office = await user.category_id("Office")
    client_id = str(uuid.uuid4())
    payload = {
        "category_id": office,
        "started_at": ts("09:00"),
        "ended_at": ts("10:00"),
        "client_id": client_id,
    }

    first = await user.post(f"{LOG}/entries", json=payload)
    second = await user.post(f"{LOG}/entries", json=payload)
    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert len(await entries(user)) == 1


async def test_client_id_of_another_user_conflicts(make_user):
    alice = await make_user("alice@example.com")
    bob = await make_user("bob@example.com")
    client_id = str(uuid.uuid4())
    await add(alice, await alice.category_id("Office"), "09:00", "10:00", client_id=client_id)
    resp = await bob.post(
        f"{LOG}/entries",
        json={
            "category_id": await bob.category_id("Office"),
            "started_at": ts("09:00"),
            "ended_at": ts("10:00"),
            "client_id": client_id,
        },
    )
    assert resp.status_code == 409


# ------------------------------------------------------------------ accept plan


async def _weekday_routine(user, blocks: list[tuple[str, str, int, int]]) -> dict:
    payload = [
        {
            "category_id": await user.category_id(cat),
            "title": title,
            "start_minute": start,
            "duration_minutes": duration,
        }
        for cat, title, start, duration in blocks
    ]
    resp = await user.post("/api/v1/routines", json={"name": "Weekday", "blocks": payload})
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_accept_plan_fills_only_empty_blocks(make_user):
    user = await make_user()
    await _weekday_routine(
        user,
        [
            ("Fitness", "Gym", 420, 60),
            ("Office", "Work", 540, 480),
            ("Family", "Family", 1080, 120),
        ],
    )
    # Already logged something during the work block.
    await add(user, await user.category_id("Meals"), "12:00", "13:00")

    resp = await user.post(f"{LOG}/accept-plan")
    assert resp.status_code == 200, resp.text
    result = resp.json()["entries"]
    assert [(span(e), e["source"]) for e in result] == [
        (("07:00", "08:00"), "planned"),
        (("12:00", "13:00"), "manual"),
        (("18:00", "20:00"), "planned"),
    ]
    snapshot = {b["title"]: b["block_id"] for b in resp.json()["planned_snapshot"]}
    assert result[0]["planned_block_id"] == snapshot["Gym"]

    # Running it again adds nothing.
    again = (await user.post(f"{LOG}/accept-plan")).json()["entries"]
    assert len(again) == 3


async def test_editing_planned_entry_marks_it_adjusted(make_user):
    user = await make_user()
    await _weekday_routine(user, [("Fitness", "Gym", 420, 60)])
    gym_entry = (await user.post(f"{LOG}/accept-plan")).json()["entries"][0]
    resp = await user.patch(f"{LOG}/entries/{gym_entry['id']}", json={"ended_at": ts("07:45")})
    assert resp.json()["source"] == "adjusted"


async def test_block_crossing_midnight(make_user):
    user = await make_user(timezone="Asia/Kolkata")
    await _weekday_routine(user, [("Sleep", "Sleep", 1380, 480)])  # 23:00 -> 07:00 IST

    result = (await user.post(f"{LOG}/accept-plan")).json()["entries"]
    assert len(result) == 1
    assert datetime.fromisoformat(result[0]["started_at"]) == datetime(
        2026, 10, 26, 17, 30, tzinfo=UTC
    )
    assert datetime.fromisoformat(result[0]["ended_at"]) == datetime(
        2026, 10, 27, 1, 30, tzinfo=UTC
    )

    # Woke up late: logging 06:00-08:00 IST (00:30-02:30 UTC on the 27th) under the same
    # log date trims the tail of the overnight sleep.
    resp = await user.post(
        f"{LOG}/entries",
        json={
            "category_id": await user.category_id("Leisure"),
            "started_at": "2026-10-27T06:00:00+05:30",
            "ended_at": "2026-10-27T08:00:00+05:30",
        },
    )
    assert resp.status_code == 201, resp.text
    result = await entries(user)
    assert datetime.fromisoformat(result[0]["ended_at"]) == datetime(
        2026, 10, 27, 0, 30, tzinfo=UTC
    )
