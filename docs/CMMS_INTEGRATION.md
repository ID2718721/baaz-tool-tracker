# Интеграция с BAAZ CMMS (ТОиР)

Клиентская документация для **BAAZ Tool Tracker**. Серверная (репозиторий **baaz-cmms**): `docs/TOOL_TRACKER_INTEGRATION.md`.

## Режимы Mock / Live

| Переменная | Значение |
|------------|----------|
| `CMMS_INTEGRATION_MODE` | `mock` (default) \| `live` |
| `CMMS_SUPABASE_URL` | URL проекта CMMS Supabase |
| `CMMS_SUPABASE_KEY` | **publishable/anon** key CMMS (read `integration.v_*`) |
| `CMMS_INTEGRATION_SECRET` | shared B: TMS → CMMS (REP-API-1) |
| `CMMS_FUNCTIONS_URL` | `{CMMS_SUPABASE_URL}/functions/v1` (без `/integration-tms-create-request`) |
| `TMS_INTEGRATION_SECRET` | shared A: CMMS → TMS (ISS-API, REP-EVT-1) |

Mock: `app/integration/fixtures/*.json` — зеркало CMMS fixtures.

## Настройка ключей и секретов (сторона TMS)

Парная инструкция для CMMS: `baaz-cmms/docs/TOOL_TRACKER_INTEGRATION.md` (раздел «Настройка ключей и секретов (сторона CMMS)»).

### Типы credentials

| Тип | Назначение | Где задаётся (TMS) |
|-----|------------|---------------------|
| **Service role** TMS | Backend FastAPI → БД TMS | `.env` → `SUPABASE_KEY` |
| **Publishable key** CMMS | Read-only PostgREST `integration.v_*` | `.env` → `CMMS_SUPABASE_KEY` |
| **`TMS_INTEGRATION_SECRET`** (shared A) | CMMS → TMS: ISS-API, REP-EVT-1 | `.env`; дублируется в CMMS **TmsIntegrationSecret** |
| **`CMMS_INTEGRATION_SECRET`** (shared B) | TMS → CMMS: REP-API-1 | `.env`; дублируется в CMMS Edge secrets |
| **`JWT_SECRET_KEY`** | Сессия веб-UI TMS | `.env`; **не** связан с интеграцией |

Integration-секреты — **отдельные случайные строки**, не подставлять `service_role` / publishable key Supabase.

### Связка между системами

```
shared-secret-A  →  TMS .env:       TMS_INTEGRATION_SECRET
                 →  CMMS Settings:  TmsIntegrationSecret

shared-secret-B  →  TMS .env:       CMMS_INTEGRATION_SECRET
                 →  CMMS Edge:      CMMS_INTEGRATION_SECRET
```

### Локально (dev)

Скопировать [`.env.example`](../.env.example) → `.env`.

**Минимальный Live без проверки Bearer** (секреты пустые — auth отключён в коде):

```env
# --- Supabase TMS (своя БД, порт 55321) ---
SUPABASE_URL=http://127.0.0.1:55321
SUPABASE_KEY=<service_role из `supabase status` в baaz-tool-tracker>

JWT_SECRET_KEY=dev-jwt-change-me
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=480
ACCESS_TOKEN_COOKIE_NAME=tms_access_token
COOKIE_SECURE=false
COOKIE_SAMESITE=lax

# --- Integration (пусто = dev без Bearer) ---
TMS_INTEGRATION_SECRET=
CMMS_INTEGRATION_SECRET=

# --- CMMS (контур А + read views) ---
CMMS_INTEGRATION_MODE=live
CMMS_SUPABASE_URL=http://127.0.0.1:54321
CMMS_SUPABASE_KEY=<publishable/anon из `supabase status` в baaz-cmms>
CMMS_FUNCTIONS_URL=http://127.0.0.1:54321/functions/v1
```

Ключи: `supabase status` в каждом репо. Studio для локалки не нужен.

**С включённой проверкой** — задать два разных значения A и B; то же B — в CMMS `supabase secrets set CMMS_INTEGRATION_SECRET=…`; A — в CMMS Settings → TmsIntegrationSecret.

**CMMS (сторона клиента):** Settings → TMS **Live**, URL `http://127.0.0.1:8000`, TmsIntegrationSecret = A (или пусто).

### Production

Пример `.env` на сервере TMS:

```env
# --- Supabase TMS ---
SUPABASE_URL=https://tms-prod.supabase.co
SUPABASE_KEY=sb_secret_...

# --- Сессия TMS ---
JWT_SECRET_KEY=<случайная_строка_32+>
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=480
ACCESS_TOKEN_COOKIE_NAME=tms_access_token
COOKIE_SECURE=true
COOKIE_SAMESITE=lax

# --- Integration ---
TMS_INTEGRATION_SECRET=<shared-secret-A>
CMMS_INTEGRATION_SECRET=<shared-secret-B>

# --- CMMS ---
CMMS_INTEGRATION_MODE=live
CMMS_SUPABASE_URL=https://cmms-prod.supabase.co
CMMS_SUPABASE_KEY=sb_publishable_...
CMMS_FUNCTIONS_URL=https://cmms-prod.supabase.co/functions/v1
```

На стороне CMMS дополнительно:

- Edge: `CMMS_INTEGRATION_SECRET=<shared-secret-B>`
- App Settings: `TmsIntegrationSecret=<shared-secret-A>`, `TmsBaseUrl=https://tms.example.com`, `TmsIntegrationMode=Live`

### Генерация shared-секретов

```powershell
[Convert]::ToBase64String((1..32 | ForEach-Object { Get-Random -Maximum 256 }) -as [byte[]])
```

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Два **разных** значения для A и B. Не коммитить в git.

## Схема TMS

Миграции `supabase/migrations/`:

| Файл | Содержимое |
|------|------------|
| `010_tables_catalog.sql` | `locations`, `tools`, … (без префикса `tms_`) |
| `020_tables_requisitions.sql` | `requisitions`, `requisition_lines` |
| `050_integration_cmms.sql` | `cmms_work_order_links`, `cmms_repair_links` |

CMMS-метаданные — **link-таблицы**, не ALTER core.

## HTTP API (контур Б, ISS-API)

Base: `http://127.0.0.1:8000/api/v1/integration/cmms`

| ID | Method | Path |
|----|--------|------|
| ISS-API-1 | POST | `/tool-requisitions` |
| ISS-API-2 | POST | `/cancel-tool-requisitions` |
| ISS-API-3 | GET | `/warehouses` |
| ISS-API-4 | GET | `/warehouse-catalog?warehouse_id=` |
| ISS-API-5 | GET | `/tool-requisition?cmms_request_id=` |
| REP-EVT-1 | POST | `/repair-request-status` |

Auth (если `TMS_INTEGRATION_SECRET` задан): `Authorization: Bearer <shared-secret-A>`. Заголовок `apikey` CMMS может передаваться, но не проверяется (достаточно Bearer). Пустой секрет в dev — проверка пропускается.

Реализация: [`app/api/endpoints/integration_cmms.py`](../app/api/endpoints/integration_cmms.py), [`app/services/cmms_integration_service.py`](../app/services/cmms_integration_service.py).

## Контур А (TMS → CMMS)

| ID | Method | URL |
|----|--------|-----|
| REP-API-1 | POST | `{CMMS_FUNCTIONS_URL}/integration-tms-create-request` |
| REP-API-2 | POST | `{CMMS_FUNCTIONS_URL}/integration-tms-inventory-received` |
| REP-API-3 | GET | `{CMMS}/rest/v1/v_inventory_requests?inventory_id=eq.{uuid}` + `Accept-Profile: integration` |
| REP-API-4 | GET | `v_inventory_work_reports` |
| REP-API-5 | GET | `{CMMS}/rest/v1/v_repair_departments?order=name.asc` + `Accept-Profile: integration` |

### Передача inventory: склад ↔ отдел

| Этап | TMS (`tools.status`) | CMMS (`requests.status`) |
|------|----------------------|---------------------------|
| Отправка в ТОиР | `pending_repair` | `new` |
| Принятие отделом + назначение | — | `accepted` |
| **Забор:** диспетчер «Инструмент получен» | `maintenance` (REP-EVT-1) | `in_progress` |
| **Доставка:** кладовщик «Передан в отдел» | `maintenance` | `in_progress` (REP-API-2) |
| Закрытие заявки | `pending_return` (REP-EVT-1) | `closed` |
| Приёмка на склад | `available` | — |

REP-API-1 дополнительно: `inventory_handoff_mode` (`pickup_at_warehouse` \| `deliver_to_department`), `inventory_warehouse_name`; в CMMS `repair_zone=workshop`.

TMS API (кладовщик, свой склад):

- `POST /api/v1/tools/{id}/handover-to-repair` — режим deliver, CMMS `accepted`
- `POST /api/v1/tools/{id}/accept-return-from-repair` — после `pending_return`

UI: `/inventory` → «Отправить в ТОиР» (`POST /api/v1/tools/{id}/send-to-cmms`, роли **`clerk`** и **`master`**); в модалке — **ремонтный отдел** + **способ передачи**. При наличии `cmms_repair_links` — «Заявка ТОиР» → `/inventory/{tool_id}/cmms-repair`.

REP-EVT-1 (`in_progress`, `closed`, `rejected`, `cancelled`): см. таблицу передачи выше; до получения инструмента (`new`/`accepted`) → TMS `available`, после работ → `pending_return`.

### Устранение «Function not found» (404)

TMS вызывает `POST {CMMS_FUNCTIONS_URL}/integration-tms-create-request`. Ошибка **Function not found** от Kong/Edge Runtime — функция не зарегистрирована, а не неверный slug в клиенте.

**Частые причины:**

1. Edge Runtime CMMS поднят только с `admin-users` (после `supabase functions serve admin-users`). В логах `supabase_edge_runtime_baaz-cmms` видна одна строка `…/admin-users`. **Исправление:** в репо CMMS — `supabase stop` → `supabase start` (или полный перезапуск стека, не single-function serve).
2. `CMMS_FUNCTIONS_URL` указывает на TMS Supabase (`55321`) вместо CMMS (`54321`).
3. В `CMMS_FUNCTIONS_URL` уже указан полный путь с именем функции — клиент нормализует, но база должна быть `…/functions/v1`.

**Проверка curl (локально):**

```powershell
curl -X POST "http://127.0.0.1:54321/functions/v1/integration-tms-create-request" `
  -H "Content-Type: application/json" `
  -H "apikey: <publishable CMMS>" `
  -H "Authorization: Bearer <CMMS_INTEGRATION_SECRET или пусто в dev>" `
  -d '{"client_reference_id":"00000000-0000-4000-8000-000000000099","inventory_id":"d1000000-0000-4000-8000-000000000001","inventory_kind":"tool","inventory_name":"Test","request_type":"inspection","title":"curl test"}'
```

Ожидается `201`/`200` с `request_id`, не `Function not found`.

## Clerk UI

- `/requisitions` — вкладки CMMS / внутренние (`cmms_work_order_links` vs без link)
- `POST /requisitions/{id}/cancel` — отмена кладовщиком

## Fixtures

| TMS | CMMS |
|-----|------|
| `app/integration/fixtures/inventory_requests.json` | `…/inventory_requests.json` |
| `app/integration/fixtures/inventory_work_reports.json` | (REP-API-3, demo UUID `d1000000-…0001`) |
| `app/integration/fixtures/repair_departments.json` | view `integration.v_repair_departments` (REP-API-4) |
| `app/integration/fixtures/create_repair_request_response.json` | — |

Общие UUID согласуются через `baaz-cmms/scripts/seed-tt-integration-data.mjs`.

## Manual checklist

1. `supabase db reset` в обоих проектах
2. TMS: `uvicorn main:app --reload --port 8000`
3. CMMS Mock: Tool Requisition без TMS
4. CMMS Live + TMS: ISS-API-1 → clerk reserve/issue → ISS-API-5
5. TMS pickup: send → `pending_repair` → CMMS accept → «Инструмент получен» → `in_progress`, TMS `maintenance`
6. TMS deliver: send → «Передан в отдел» → CMMS `in_progress`
7. Закрытие CMMS → TMS `pending_return` → «Принят на склад» → `available`
8. Отмена до передачи (`new`/`accepted`) → TMS `available`
