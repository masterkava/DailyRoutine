from datetime import date

ROUTINES = "/api/v1/routines"
MONDAY = date(2026, 10, 26)
SATURDAY = date(2026, 10, 24)


def block(category_id: str, title: str, start: int, duration: int) -> dict:
    return {
        "category_id": category_id,
        "title": title,
        "start_minute": start,
        "duration_minutes": duration,
    }


async def test_create_routine_with_blocks_sorted(make_user):
    user = await make_user()
    office = await user.category_id("Office")
    sleep = await user.category_id("Sleep")
    resp = await user.post(
        ROUTINES,
        json={
            "name": "Weekday",
            "blocks": [block(sleep, "Sleep", 1380, 480), block(office, "Work", 600, 480)],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["weekdays"] == 0b0011111
    assert [b["title"] for b in body["blocks"]] == ["Work", "Sleep"]

    listed = await user.get(ROUTINES)
    assert [r["id"] for r in listed.json()] == [body["id"]]


async def test_replace_blocks_rejects_overlap(make_user):
    user = await make_user()
    office = await user.category_id("Office")
    gym = await user.category_id("Fitness")
    routine = (await user.post(ROUTINES, json={"name": "Weekday"})).json()

    overlapping = [block(office, "Work", 540, 480), block(gym, "Gym", 960, 60)]  # 9-17 vs 16-17
    resp = await user.put(f"{ROUTINES}/{routine['id']}/blocks", json=overlapping)
    assert resp.status_code == 422
    assert "overlap" in resp.json()["detail"].lower()

    # Same rule on create.
    resp = await user.post(ROUTINES, json={"name": "Bad", "blocks": overlapping})
    assert resp.status_code == 422

    # Touching end-to-start is fine.
    adjacent = [block(office, "Work", 540, 480), block(gym, "Gym", 1020, 60)]
    resp = await user.put(f"{ROUTINES}/{routine['id']}/blocks", json=adjacent)
    assert resp.status_code == 200
    assert len(resp.json()["blocks"]) == 2


async def test_replace_blocks_replaces_everything(make_user):
    user = await make_user()
    office = await user.category_id("Office")
    routine = (
        await user.post(
            ROUTINES, json={"name": "Weekday", "blocks": [block(office, "Work", 540, 480)]}
        )
    ).json()
    resp = await user.put(
        f"{ROUTINES}/{routine['id']}/blocks", json=[block(office, "Half day", 540, 240)]
    )
    assert [b["title"] for b in resp.json()["blocks"]] == ["Half day"]


async def test_blocks_must_use_own_categories(make_user):
    alice = await make_user("alice@example.com")
    bob = await make_user("bob@example.com")
    bobs_category = await bob.category_id("Office")
    resp = await alice.post(
        ROUTINES, json={"name": "Sneaky", "blocks": [block(bobs_category, "x", 0, 60)]}
    )
    assert resp.status_code == 422


async def test_block_range_validation(make_user):
    user = await make_user()
    office = await user.category_id("Office")
    resp = await user.post(ROUTINES, json={"name": "x", "blocks": [block(office, "x", 2880, 10)]})
    assert resp.status_code == 422
    resp = await user.post(ROUTINES, json={"name": "x", "blocks": [block(office, "x", 0, 1441)]})
    assert resp.status_code == 422


async def test_routine_for_date_matches_weekday(make_user):
    user = await make_user()
    weekday = (await user.post(ROUTINES, json={"name": "Weekday", "weekdays": 0b0011111})).json()
    weekend = (await user.post(ROUTINES, json={"name": "Weekend", "weekdays": 0b1100000})).json()
    assert MONDAY.weekday() == 0 and SATURDAY.weekday() == 5

    mon = await user.get(f"{ROUTINES}/for-date", params={"date": MONDAY.isoformat()})
    sat = await user.get(f"{ROUTINES}/for-date", params={"date": SATURDAY.isoformat()})
    assert mon.json()["id"] == weekday["id"]
    assert sat.json()["id"] == weekend["id"]

    await user.patch(f"{ROUTINES}/{weekend['id']}", json={"is_active": False})
    sat = await user.get(f"{ROUTINES}/for-date", params={"date": SATURDAY.isoformat()})
    assert sat.json() is None


async def test_routine_crud_and_isolation(make_user):
    alice = await make_user("alice@example.com")
    bob = await make_user("bob@example.com")
    routine = (await alice.post(ROUTINES, json={"name": "Mine"})).json()

    assert (await bob.get(f"{ROUTINES}/{routine['id']}")).status_code == 404
    renamed = await alice.patch(f"{ROUTINES}/{routine['id']}", json={"name": "Renamed"})
    assert renamed.json()["name"] == "Renamed"
    assert (await alice.delete(f"{ROUTINES}/{routine['id']}")).status_code == 204
    assert (await alice.get(f"{ROUTINES}/{routine['id']}")).status_code == 404


async def test_category_crud_and_archive_on_delete(make_user):
    user = await make_user()
    created = await user.post(
        "/api/v1/categories", json={"name": "Doomscrolling", "color": "#FF0000", "kind": "wasted"}
    )
    assert created.status_code == 201
    dup = await user.post(
        "/api/v1/categories", json={"name": "Doomscrolling", "color": "#FF0000", "kind": "wasted"}
    )
    assert dup.status_code == 409
    bad_color = await user.post(
        "/api/v1/categories", json={"name": "X", "color": "red", "kind": "wasted"}
    )
    assert bad_color.status_code == 422

    # Unused category: hard delete.
    unused = created.json()["id"]
    resp = await user.delete(f"/api/v1/categories/{unused}")
    assert resp.json() == {"id": unused, "deleted": True, "archived": False}

    # Category used by a block: archived instead.
    office = await user.category_id("Office")
    await user.post(ROUTINES, json={"name": "W", "blocks": [block(office, "Work", 540, 60)]})
    resp = await user.delete(f"/api/v1/categories/{office}")
    assert resp.json() == {"id": office, "deleted": False, "archived": True}

    visible = {c["id"] for c in (await user.get("/api/v1/categories")).json()}
    assert office not in visible
    everything = await user.get("/api/v1/categories", params={"include_archived": True})
    assert office in {c["id"] for c in everything.json()}
