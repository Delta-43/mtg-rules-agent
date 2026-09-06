# accounts_db (scaffolding)

Postgres models/migrations for the future accounts/tiers/billing pivot —
see the root `docs/PLAN.md`'s "Future: accounts, tiers & billing pivot" section
for the full design. **Not imported by `app_api` yet.** Nothing here
changes the app's behavior today; it's groundwork so that work is smaller
later.

## Why Postgres, and why Supabase specifically

The main backend's existing SQLite file (`data/conversations/conversations.db`)
stays exactly as-is — it keeps holding LangGraph's checkpointer tables and
`usage_counters` (the Discord bot's / other API-key callers' quota). Account
data (identity, subscriptions, per-user history index, billing) is a
different kind of data — it needs real relational integrity, and it's the
one part of this app where losing data actually means losing paying
customers' state — so it gets its own database instead of overloading the
single-SQLite-file model further.

Self-hosted **Supabase** was chosen because it's itself just a Docker
Compose stack (fits this project's containerize-everything approach), but
only two of its ~10 official containers are actually used here:

- `supabase-db` — Postgres, holding this package's tables.
- `supabase-auth` — GoTrue, Supabase's auth service. It owns identity
  entirely (its own `auth.users` schema, OAuth against Google/Discord/
  GitHub, and native cross-provider account linking by verified email) —
  this package's tables never duplicate a `users` table, they only
  reference `auth.users.id` as a plain `user_id` UUID column with no hard
  cross-schema foreign key (keeps this package's own migrations independent
  of GoTrue's internal schema versioning).

Deliberately **not** run: PostgREST, Realtime, Storage, imgproxy, Kong, the
Studio dashboard, or the analytics service — none of them are needed for
"OAuth login + a few relational tables read/written by our own FastAPI
backend." The main backend talks to Postgres directly via SQLAlchemy and
verifies GoTrue-issued JWTs locally (shared secret) instead of using
Supabase's REST/gateway layer at all.

## Tables

`models.py` defines four tables in the `public` schema:
`subscriptions`, `conversation_index` (the sidecar seam into LangGraph's
SQLite checkpointer — see the comment on that class for why), `user_hourly_
usage` (the flat rolling-hour quota counter), and `stripe_webhook_events`
(webhook-delivery idempotency).

## Trying it standalone

```bash
# Bring up just the two containers this package needs:
docker compose --profile accounts up -d supabase-db supabase-auth

# Set SUPABASE_DB_URL in your environment (see .env.example), then:
pip install -r requirements.txt
alembic -c accounts_db/alembic.ini upgrade head
```

`python -c "import accounts_db.models"` should also succeed with no
Postgres connection at all — model *definitions* don't need a live
database.

**Verified live this session**: `docker compose --profile accounts up -d
supabase-db` pulls and boots cleanly, and `alembic -c accounts_db/alembic.ini
upgrade head`/`downgrade base` both work correctly against it (all four
tables created/dropped as designed) using the plain `postgres` superuser —
this package's own migrations don't need any Supabase-specific role.

**Found and worth knowing before Phase 1**: `supabase-auth` (GoTrue) does
*not* boot successfully against a bare `supabase-db` container started this
way — it fails with `role "supabase_auth_admin" does not exist"`. The
`supabase/postgres` image's bundled `migrate.sh` init step expects
Supabase's own role/schema bootstrap SQL (`roles.sql`, `jwt.sql`, plus a
few migration-schema files) to already be mounted into
`/docker-entrypoint-initdb.d/` — normally supplied by Supabase's own
official `docker-compose.yml` (`docker/volumes/db/*.sql` in
`supabase/supabase`), which this trimmed-down setup deliberately doesn't
pull in wholesale. Getting `supabase-auth` actually working is Phase 1
work (vendor the specific init SQL files GoTrue's role/schema needs,
mount them into `supabase-db`, and set the `JWT_SECRET`/`JWT_EXP` env vars
`roles.sql`/`jwt.sql` expect) — not a Phase 0 scaffolding gap.
