from app.services.auth_service import DEFAULT_CATEGORIES

LOGIN = "/api/v1/auth/login"
REFRESH = "/api/v1/auth/refresh"


async def test_healthz(client):
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_register_returns_tokens_and_seeds_categories(make_user):
    user = await make_user()
    assert user.tokens["token_type"] == "bearer"
    assert user.tokens["expires_in"] == 15 * 60

    resp = await user.get("/api/v1/categories")
    assert resp.status_code == 200
    names = {c["name"] for c in resp.json()}
    assert names == {name for name, *_ in DEFAULT_CATEGORIES}


async def test_register_duplicate_email_conflicts(client, make_user):
    await make_user("dup@example.com")
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "DUP@example.com", "password": "another password", "display_name": "x"},
    )
    assert resp.status_code == 409


async def test_register_rejects_unknown_timezone(client):
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "tz@example.com",
            "password": "long enough",
            "display_name": "tz",
            "timezone": "Mars/Olympus",
        },
    )
    assert resp.status_code == 422


async def test_login_with_form(client, make_user):
    await make_user("login@example.com")
    ok = await client.post(
        LOGIN, data={"username": "login@example.com", "password": "correct horse battery"}
    )
    assert ok.status_code == 200
    assert ok.json()["access_token"]

    bad = await client.post(LOGIN, data={"username": "login@example.com", "password": "nope"})
    assert bad.status_code == 401
    unknown = await client.post(LOGIN, data={"username": "who@example.com", "password": "x"})
    assert unknown.status_code == 401


async def test_me_get_and_patch(make_user):
    user = await make_user("me@example.com")
    me = await user.get("/api/v1/me")
    assert me.status_code == 200
    assert me.json()["timezone"] == "UTC"
    assert me.json()["day_start_minute"] == 240

    resp = await user.patch(
        "/api/v1/me", json={"timezone": "Asia/Kolkata", "display_name": "Mayur"}
    )
    assert resp.status_code == 200
    assert resp.json()["timezone"] == "Asia/Kolkata"
    assert resp.json()["display_name"] == "Mayur"

    bad = await user.patch("/api/v1/me", json={"timezone": "Not/AZone"})
    assert bad.status_code == 422


async def test_requires_valid_access_token(client, make_user):
    user = await make_user()
    assert (await client.get("/api/v1/me")).status_code == 401
    garbage = await client.get("/api/v1/me", headers={"Authorization": "Bearer nope"})
    assert garbage.status_code == 401
    # A refresh token is opaque and must never work as an access token.
    as_bearer = await client.get(
        "/api/v1/me", headers={"Authorization": f"Bearer {user.tokens['refresh_token']}"}
    )
    assert as_bearer.status_code == 401


async def test_refresh_rotates_and_old_token_is_rejected(client, make_user):
    user = await make_user()
    old = user.tokens["refresh_token"]

    first = await client.post(REFRESH, json={"refresh_token": old})
    assert first.status_code == 200
    new_pair = first.json()
    assert new_pair["refresh_token"] != old
    me = await client.get(
        "/api/v1/me", headers={"Authorization": f"Bearer {new_pair['access_token']}"}
    )
    assert me.status_code == 200

    # Re-using the rotated token fails...
    replay = await client.post(REFRESH, json={"refresh_token": old})
    assert replay.status_code == 401
    # ...and is treated as theft: the token issued from it is revoked too.
    after_theft = await client.post(REFRESH, json={"refresh_token": new_pair["refresh_token"]})
    assert after_theft.status_code == 401


async def test_refresh_with_unknown_token(client):
    resp = await client.post(REFRESH, json={"refresh_token": "never-issued"})
    assert resp.status_code == 401


async def test_logout_revokes_refresh_token(client, make_user):
    user = await make_user()
    resp = await client.post("/api/v1/auth/logout", json=user.tokens)
    assert resp.status_code == 204
    again = await client.post(REFRESH, json={"refresh_token": user.tokens["refresh_token"]})
    assert again.status_code == 401
