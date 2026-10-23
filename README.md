# Life Mirror — Routine vs Reality

Plan your ideal day as a routine, log what actually happened, and see the gap.

```
backend/   FastAPI + PostgreSQL API (Phase 1)
mobile/    (Phase 2+)
web/       (Phase 2+)
```

## Running the backend

Requires Python 3.12+ and Docker (or any Postgres 16+ you can point at).

```bash
# 1. Database (also creates the lifemirror_test DB on first start)
docker compose up -d db

# 2. Python env
cd backend
python -m venv .venv            # or: uv venv --python 3.12
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -e ".[dev]"         # or: uv pip install -e ".[dev]"
cp .env.example .env            # then set JWT_SECRET

# 3. Schema
alembic upgrade head

# 4. Run
uvicorn app.main:app --reload
```

Open http://localhost:8000/docs for the interactive API docs; `GET /healthz` checks the DB.

### Tests and lint

```bash
cd backend
pytest              # needs the db container; uses TEST_DATABASE_URL (lifemirror_test)
ruff check . && ruff format --check .
```

The test suite drops and rebuilds the `public` schema of the **test** database by
running the Alembic migrations, so never point `TEST_DATABASE_URL` at real data.

If your docker volume already existed before `backend/scripts/create-test-db.sql`
was added, create the test DB once by hand:
`docker compose exec db createdb -U lifemirror lifemirror_test`.

### Configuration

All settings come from environment variables or `backend/.env`:

| Variable | Default |
| --- | --- |
| `DATABASE_URL` | `postgresql+asyncpg://lifemirror:lifemirror@localhost:5432/lifemirror` |
| `TEST_DATABASE_URL` | `…/lifemirror_test` |
| `JWT_SECRET` | dev placeholder — **set this** |
| `ACCESS_TOKEN_MINUTES` | `15` |
| `REFRESH_TOKEN_DAYS` | `30` |

## API overview (`/api/v1`)

| Area | Endpoints |
| --- | --- |
| Auth | `POST /auth/register`, `POST /auth/login` (OAuth2 form), `POST /auth/refresh`, `POST /auth/logout`, `GET/PATCH /me` |
| Categories | `GET/POST /categories`, `GET/PATCH/DELETE /categories/{id}` (delete archives if in use) |
| Routines | `GET/POST /routines`, `GET/PATCH/DELETE /routines/{id}`, `PUT /routines/{id}/blocks`, `GET /routines/for-date?date=` |
| Logs | `GET /logs?from=&to=`, `GET/PATCH /logs/{date}`, `POST /logs/{date}/entries`, `PATCH/DELETE /logs/{date}/entries/{id}`, `POST /logs/{date}/accept-plan` |

Key behaviours:

- **Time model.** Routine blocks are stored as `start_minute` from local midnight
  (0–2879; ≥1440 means the next day) plus a duration. When a day's log is first
  opened, the matching routine is snapshotted into absolute UTC timestamps using
  the user's IANA timezone, so later routine edits don't rewrite history.
- **No overlapping entries.** A deferred `EXCLUDE USING gist` constraint guarantees
  a user never has two entries at once. Writes follow *newest edit wins*: a new or
  edited entry deletes, trims or splits whatever it overlaps, in one transaction.
- **Offline-friendly.** `client_id` on entry creation makes retries idempotent.
- **Refresh tokens** are opaque, stored as SHA-256 hashes, and rotated on every use.
  Re-using a rotated token revokes all of that user's refresh tokens.
