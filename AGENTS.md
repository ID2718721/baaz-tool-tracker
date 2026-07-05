# AGENTS.md

Guidance for AI coding agents in this repo. **For agents only** (English). Human product context may live in `README.md` and `docs/`; keep focus on **how to work in repo**.

Update as project evolves.

## Project overview

**BAAZ Tool Tracker (TMS)** — web **demonstration** app for tool inventory, issue/return, analytics, and CMMS repair handoff. University internship project for OAO «Baranovichsky auto-aggregate plant» (БААЗ). **No long-term maintenance** expectation; prioritize working functionality + clear structure over production hardening.

| Layer | Location | Responsibility |
|-------|----------|----------------|
| HTTP + HTML UI | `main.py`, `app/api/endpoints/pages.py`, `templates/` | FastAPI routes, Jinja2 server-rendered pages |
| REST API | `app/api/endpoints/` | JSON endpoints per role + CMMS integration |
| Domain + DB | `app/services/`, `app/integration/`, `app/models/schemas.py` | Business logic, CMMS client, Pydantic DTOs |
| Database | `supabase/` | Local/cloud PostgreSQL via Supabase CLI |

**Stack:** Python 3.11+, FastAPI, Jinja2, `supabase-py` (PostgREST, **service_role**), `python-jose` (JWT), `httpx` (sync CMMS calls), `pydantic-settings`, `openpyxl` / `xlsxwriter` / `python-docx` (reports). **No SPA**, **no async handlers** — sync route functions throughout.

**Auth:** custom JWT in HttpOnly cookie `tms_access_token` — **not** Supabase Auth. Users live in TMS `users` table (`login`, `password_hash`, `role`, `employee_id`, `warehouse_id`).

**Roles** (`users.role`, enforced in FastAPI — **no Postgres RLS**):

| Role | Permissions (summary) |
|------|------------------------|
| `admin` | Users, locations/warehouses, read-only inventory, analytics |
| `master` | Tool catalog, inventory CRUD, analytics, send to CMMS |
| `clerk` | Inventory + requisitions for **own warehouse**, send to CMMS |

**Connectivity:** online-only. Supabase unreachable → API/page errors; no offline cache.

**Local Supabase port:** **55321** (see `supabase/config.toml`) — avoids conflict with CMMS on **54321**. CMMS integration URLs in `.env` still point at CMMS on 54321.

## Repository layout

```
baaz-tool-tracker/
AGENTS.md
main.py                         # create_app(), router wiring, exception handlers
requirements.txt
package.json                    # pnpm shortcuts only (db:*, start) — no JS build
create_hash.py                  # bcrypt hash for seed / manual user insert
.env.example
scripts/
  start.ps1                     # venv + uvicorn main:app --reload
app/
  core/
    config.py                   # Settings (pydantic-settings), get_settings()
    security.py                 # JWT sign/decode
    supabase.py                 # get_supabase_client()
    db_utils.py                 # execute_supabase(), first_row()
    requisition_status.py       # derive_requisition_status() — single source of truth
    status_labels.py            # Russian labels + Jinja2 filter helpers
  api/
    deps.py                     # get_current_user, require_roles, role aliases
    endpoints/
      auth.py                   # /login, /logout
      pages.py                  # HTML routes (Jinja2)
      admin.py                  # /api/v1/admin/*
      master.py                 # /api/v1/master/*
      tools.py                  # /api/v1/tools/*
      requisitions.py           # /api/v1/requisitions/*
      analytics.py              # /api/v1/analytics/*
      reports.py                # /api/v1/reports/*
      integration_cmms.py       # /api/v1/integration/cmms/* (ISS-API, REP-EVT-1)
  integration/
    cmms_client.py              # ICmmsRepairClient, Mock / Live implementations
    fixtures/                   # JSON mirrors CMMS integration fixtures
  models/
    schemas.py                  # All Pydantic models + StrEnum types
  services/
    cmms_integration_service.py # ISS-API / REP-EVT-1 business logic
templates/                      # Jinja2 HTML
docs/
  CMMS_INTEGRATION.md           # Primary integration doc (TMS side)
  database.md
  roles_and_permissions.md
supabase/
  migrations/                   # Ordered thematic migrations — source of truth
  seed.sql
```

## Setup

**Prerequisites:** Python 3.11+, Docker Desktop, Supabase CLI, optional `pnpm` for script shortcuts.

```powershell
cd C:\Users\Chis\Desktop\baaz-tool-tracker
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
# or: pnpm setup

copy .env.example .env
# Fill SUPABASE_URL=http://127.0.0.1:55321 and SUPABASE_KEY from `supabase status`

supabase start
supabase db reset
```

**Demo accounts** (after `supabase db reset`, see `supabase/seed.sql` / `docs/database.md`):

| Login | Password | Role |
|-------|----------|------|
| `admin` | `admin123` | admin |
| `clerk` | `clerk123` | clerk |
| `master` | `master123` | master |

Regenerate bcrypt: `python create_hash.py` or `pnpm hash:admin`.

**Run server:**

```powershell
uvicorn main:app --reload
# or: pnpm start
```

App: `http://127.0.0.1:8000` · Login: `/login` · Health: `/health` · OpenAPI (debug): `/docs`

**CMMS integration (local):** see `docs/CMMS_INTEGRATION.md`. Default `CMMS_INTEGRATION_MODE=mock`. For Live with local CMMS: CMMS Supabase on 54321, TMS on 55321; empty `TMS_INTEGRATION_SECRET` / `CMMS_INTEGRATION_SECRET` disables Bearer checks in dev.

## Build and verification

No compile step. **Verification gate:** server starts and `/health` returns OK.

```powershell
uvicorn main:app --reload
# GET http://127.0.0.1:8000/health → {"status":"ok","service":"BAAZ TMS"}
```

- **No CI** / **no automated tests** unless user asks.
- **Do not** run `supabase db reset` on every change — user applies DB themselves.
- **No** enforced linters (`ruff`, `mypy`) unless user asks.
- **Parallel agents:** if unrelated files break the server, do not fix outside your task scope unless clearly caused by your edits.

## Database workflow

Local dev: **Docker + Supabase CLI**. Cloud: `supabase link` + `supabase db push` / `pnpm db:push` (see `docs/supabase_памятка.md` if present).

| Path | Purpose |
|------|---------|
| `supabase/migrations/` | Ordered thematic migrations — **source of truth** |
| `supabase/seed.sql` | Seed on `supabase db reset` |

**Migration layout** (`NNN_<domain>_<kind>.sql`):

| File | Contents |
|------|----------|
| `000_extensions.sql` | PostgreSQL extensions |
| `010_tables_catalog.sql` | `locations`, `warehouses`, `employees`, `tool_categories`, `tool_types`, `tools`, `users` |
| `020_tables_requisitions.sql` | `requisitions`, `requisition_lines` |
| `030_triggers.sql` | `trg_tool_limit`, `trg_auto_maintenance`, `trg_check_availability` |
| `040_grants.sql` | PostgREST grants (`service_role`, `anon`, `authenticated`) |
| `050_integration_cmms.sql` | `cmms_work_order_links`, `cmms_repair_links`, status sync trigger |

**No maintained `schema.sql`:** optional dump via `pnpm db:dump` (user-driven).

**Early development — edit migrations in place (default):**

- **Do not** add numbered migration for routine schema tweaks unless user asks.
- **Edit thematic file** owning the change.
- **Do not** run `supabase db reset` unless user asks.

**New** migration file only when user requests or change must apply incrementally to deployed DB that cannot reset.

**After migration changes** (when user applies):

1. Apply locally (`supabase db reset` or `supabase migration up`) — **user-driven**
2. Update `app/models/schemas.py` and affected endpoints/services
3. Keep CMMS fixture UUIDs in sync if integration tables/seed IDs change

**DB access:** all runtime I/O via `supabase-py` with **service_role** (`SUPABASE_KEY`). No ORM, no direct Postgres. No RLS policies — **application layer** enforces roles and clerk `warehouse_id` scope.

**Key invariants:**

- `derive_requisition_status()` in `app/core/requisition_status.py` — do **not** duplicate requisition status logic elsewhere.
- `cmms_repair_links.tool_id` — one open repair per tool.
- `requisitions.client_reference_id` — UNIQUE (CMMS idempotency).
- Demo tool UUID shared with CMMS fixtures: `d1000000-0000-4000-8000-000000000001`.

## Project boundaries

### `app/api/endpoints/pages.py` + `templates/`

- Server-rendered HTML only; role booleans in template context (`is_admin`, `can_send_to_cmms`, …).
- Page-level gating via `_require_roles()` in `pages.py`; API uses `require_roles` deps in `deps.py`.

### `app/api/endpoints/*.py` (JSON API)

- Table name constants at top of each file (e.g. `TABLE_TOOLS = "tools"`).
- Clerk endpoints must filter by `user.warehouse_id`.

### `app/integration/` + `app/services/cmms_integration_service.py`

- CMMS HTTP contract — see `docs/CMMS_INTEGRATION.md`.
- `create_cmms_repair_client(settings)` switches Mock vs Live; fixtures in `app/integration/fixtures/`.

### `app/models/schemas.py`

- Single file for all Pydantic models and `StrEnum` types — keep consistent with DB CHECK constraints.

## Architecture patterns

- **App factory:** `create_app()` in `main.py`; routers registered with prefixes.
- **Settings:** `get_settings()` cached (`lru_cache`); `.env` overrides system env (see `settings_customise_sources`).
- **JSON:** `TMSJSONResponse` serializes `UUID`, `date`, `datetime` to strings.
- **Auth deps:** `get_current_user` reads cookie or `Authorization: Bearer`; `require_roles(*roles)` factory.
- **DB helpers:** `execute_supabase()`, `first_row()` in `app/core/db_utils.py`.
- **Jinja2 filters:** `requisition_status_label`, `tool_status_label`, etc. from `app/core/status_labels.py`.
- **Comments / user-facing copy:** **Russian**; Conventional Commit prefix (`feat`/`fix`/…) may stay English.

### CMMS integration pitfalls

- **REP-API CMMS key:** `CMMS_SUPABASE_KEY` = CMMS **publishable/anon**, not service_role.
- **Integration secrets:** random strings — never reuse Supabase API keys as `TMS_INTEGRATION_SECRET` / `CMMS_INTEGRATION_SECRET`.
- **Edge Function 404 on CMMS:** full stack restart (`supabase stop` / `supabase start` in **baaz-cmms**), not single-function hot reload only.
- **Fixture sync:** when changing integration UUIDs, update both repos + run `baaz-cmms/scripts/seed-tt-integration-data.mjs`.

## Default agent behavior

1. **Do what user asked** — stay scoped; no drive-by refactors.
2. **Proceed without asking** for: pip dependency add, DB migration edits in place, `.env.example` updates.
3. **No commit or push** unless user explicitly requests.
4. **Consult docs** before changing integration contract — `docs/CMMS_INTEGRATION.md` + symmetric `baaz-cmms/docs/TOOL_TRACKER_INTEGRATION.md`.
5. Prefer **file references** over large inline code dumps in chat.

### Manual verification checklists

After implementing a **feature** or **bugfix**, end the message with a concise **manual testing checklist** (roles: `admin`, `master`, `clerk` where relevant).

- **Planned / multi-step work:** longer checklist — key pages, API flows, CMMS mock/live if touched.
- **Small fix:** 2–5 targeted steps.
- Skip for pure Q&A or docs-only edits with no runnable behavior change.

## Git workflow

- Primary branch: **`main`**.
- **Commit** only when user asks; **never push** unless requested.
- Respect `.gitignore` (`.env`, `venv/`, `__pycache__/`, generated `*.xlsx`/`*.docx`, `node_modules/`).
- **Never commit** `.env`, `.env.cloud`, or real API keys.

**Commit message format** (Russian body; English prefix optional):

```
feat: Краткое описание

- сделано A
- добавлено B
```

## Quick reference

| Task | Start here |
|------|------------|
| Add HTML page | `app/api/endpoints/pages.py` + `templates/` |
| Add REST endpoint | `app/api/endpoints/<domain>.py`, register in `main.py` if new router |
| Add Pydantic model | `app/models/schemas.py` |
| Env / settings | `app/core/config.py`, `.env.example` |
| DB schema change | Edit file in `supabase/migrations/` → update schemas + queries |
| CMMS integration | `docs/CMMS_INTEGRATION.md`, `integration_cmms.py`, `cmms_integration_service.py`, `cmms_client.py` |
| Role matrix | `docs/roles_and_permissions.md` |
| DB ER / seed accounts | `docs/database.md` |

## Out of scope (unless user says otherwise)

- Long-term production support, CI pipelines, automated test suites
- SPA frontend (React/Vue)
- Supabase Realtime / WebSockets
- Direct Postgres / SQLAlchemy
- Mobile clients
- ERP integrations beyond CMMS

---

## Page and API registry

**HTML pages** (`pages.py`):

| URL | Roles | Description |
|-----|-------|-------------|
| `/` | all | Role-specific home |
| `/login` | — | Auth |
| `/inventory` | admin (read-only), master, clerk | Tool inventory |
| `/inventory/{tool_id}/cmms-repair` | admin, master, clerk | CMMS repair detail |
| `/requisitions` | clerk | Issue/return |
| `/analytics` | admin, master | Analytics + reports |
| `/admin/users` | admin | User management |
| `/admin/structure` | admin | Locations + warehouses |
| `/master/catalog` | admin, master | Categories + types |
| `/master/structure` | admin, master | Organization structure |

**API routers** (prefix `/api/v1` unless noted):

| Module | Prefix | Auth |
|--------|--------|------|
| `auth` | — | public |
| `pages` | — | cookie session |
| `admin` | `/admin` | `require_admin_only` |
| `master` | `/master` | master or admin |
| `tools` | `/tools` | role-dependent |
| `requisitions` | `/requisitions` | clerk (+ master/admin where allowed) |
| `analytics` | `/analytics` | master or admin |
| `reports` | `/reports` | report access roles |
| `integration_cmms` | `/integration/cmms` | Bearer `TMS_INTEGRATION_SECRET` |

---

## Adjacent repo: BAAZ CMMS

Separate WinUI + Supabase repo; integration via HTTP + Edge Functions.

**When changing TMS ↔ CMMS contract** (migrations `050_integration_cmms.sql`, fixtures, ISS-API / REP-API payloads):

1. Update `docs/CMMS_INTEGRATION.md` (this repo).
2. Update `baaz-cmms/docs/TOOL_TRACKER_INTEGRATION.md` and CMMS Edge Functions / integration views.
3. Keep fixture JSON UUIDs symmetric (`app/integration/fixtures/` ↔ `baaz-cmms` Integrations/ToolTracker/Fixtures).

---

## Integration contract (summary)

Full detail: `docs/CMMS_INTEGRATION.md`. Symmetric doc: `baaz-cmms/docs/TOOL_TRACKER_INTEGRATION.md`.

| Direction | ID | Operation | Entry point |
|-----------|-----|-----------|-------------|
| CMMS → TMS | ISS-API-1…5 | Tool requisitions, catalog, status | `integration_cmms.py` |
| CMMS → TMS | REP-EVT-1 | Repair request status webhook | `integration_cmms.py` |
| TMS → CMMS | REP-API-1 | Create repair request (Edge Function) | `cmms_client.py` |
| TMS → CMMS | REP-API-2 | Inventory received (Edge Function) | `cmms_client.py` |
| TMS → CMMS | REP-API-3…5 | Read `integration.v_*` views | `cmms_client.py` |

| Mode | Config | Behavior |
|------|--------|----------|
| Mock | `CMMS_INTEGRATION_MODE=mock` | `MockCmmsRepairClient` + local fixtures |
| Live | `CMMS_INTEGRATION_MODE=live` | HTTP to CMMS Supabase + Edge Functions |

---

## Learned workspace facts

- Local Supabase API: **55321** (TMS); CMMS stays on **54321** when both stacks run on one machine.
- `pnpm` scripts in `package.json` are convenience only — runtime is Python/venv, not Node.
- Empty `TMS_INTEGRATION_SECRET` / `CMMS_INTEGRATION_SECRET` disables Bearer auth on integration endpoints (local dev).
- Tool repair status flow: `pending_repair` → CMMS workflow → `maintenance` → `pending_return` → `available` (see `docs/CMMS_INTEGRATION.md`).
