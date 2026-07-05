# Памятка: облачный Supabase + Supabase CLI (АИС TMS)

Краткий справочник по работе с **облачным** проектом Supabase для репозитория `baaz-tool-tracker`. Локальный Docker-стек (`supabase start`) здесь упоминается только для сравнения.

См. также: [database.md](database.md), [.env.example](../.env.example), `package.json` (скрипты `db:*`).

---

## Что где лежит

| Путь | Назначение |
|------|------------|
| `supabase/config.toml` | Конфиг CLI (`project_id`, порты локально, `db.major_version = 17`) |
| `supabase/migrations/` | **Источник правды** по схеме (порядок по префиксу `NNN_`) |
| `supabase/seed.sql` | Демо-данные; применяется при `db reset`, не при обычном `db push` |
| `supabase/.temp/` | Служебные файлы CLI после `link` (в `.gitignore`) |
| `.env` | URL и ключи для FastAPI (`SUPABASE_URL`, `SUPABASE_KEY`) |

Миграции TMS:

```
000_extensions.sql
010_tables_catalog.sql
020_tables_requisitions.sql
030_triggers.sql
040_grants.sql
050_integration_cmms.sql
```

---

## Требования

1. **Supabase CLI** — проверка: `supabase --version` (рекомендуется актуальная 2.x).
2. **Аккаунт** [supabase.com](https://supabase.com) и созданный **облачный проект**.
3. **PowerShell** (Windows) — команды ниже для него; из корня репозитория.

Установка CLI (если нет): [Supabase CLI](https://supabase.com/docs/guides/local-development/cli/getting-started).

---

## Первичная привязка облака

### 1. Вход в CLI

```powershell
supabase login
```

Откроется браузер; токен сохранится локально. Без браузера: `supabase login --no-browser` (CLI покажет ссылку).

Список проектов:

```powershell
supabase projects list
```

### 2. Данные из Dashboard

В [Supabase Dashboard](https://supabase.com/dashboard) → ваш проект:

| Что | Где взять |
|-----|-----------|
| **Project ref** | Settings → General → *Reference ID* (или из URL: `https://supabase.com/dashboard/project/<ref>`) |
| **Project URL** | Settings → API → *Project URL* → `https://<ref>.supabase.co` |
| **service_role key** | Settings → API → *service_role* (секрет, только backend) |
| **Database password** | Settings → Database → *Database password* (нужен для `link`, `db push`, dump) |

### 3. Link (один раз на машину / после смены проекта)

Из корня репозитория:

```powershell
supabase link
```

CLI запросит пароль БД. Флаг `--password` можно передать сразу (осторожно с историей команд).

После успеха в `supabase/.temp/` появится привязка; команды с флагом `--linked` идут в **облако**.

Проверка:

```powershell
supabase migration list --linked
```

### 4. `.env` приложения

```powershell
copy .env.example .env
```

Заполнить (значения из Dashboard):

```env
SUPABASE_URL=https://<ref>.supabase.co
SUPABASE_KEY=<service_role_key>
```

> **Важно:** TMS использует **service role** на backend — ключ не коммитить и не отдавать в браузер. В `.gitignore` уже есть `.env`.

---

## Ежедневные команды (облако)

Обёртки через pnpm (из корня репо):

| Задача | pnpm | Прямая CLI |
|--------|------|------------|
| Применить новые миграции | `pnpm db:push` | `supabase db push --linked` |
| Список миграций local/remote | — | `supabase migration list --linked` |
| Dry-run push | — | `supabase db push --linked --dry-run` |
| Дамп схемы public с облака | `pnpm db:dump:cloud` | `supabase db dump --linked --schema public -f supabase/schema.sql` |
| Сброс облака + миграции + seed | `pnpm db:reset:cloud` | `supabase db reset --linked` |

### Первый деплой схемы на пустой облачный проект

```powershell
supabase db push --linked
```

Применятся все файлы из `supabase/migrations/`, которых ещё нет в таблице истории на remote.

Затем — seed **не** входит в push. Варианты:

1. **Полный сброс** (удалит данные на remote):

   ```powershell
   supabase db reset --linked
   ```

   Выполнит миграции заново и `supabase/seed.sql`.

2. **Только seed вручную** — SQL Editor в Dashboard или psql, вставив содержимое `seed.sql`.

3. **Демо-логины** (после seed, см. [database.md](database.md)): `admin`/`admin123`, `clerk`/`clerk123`, `master`/`master123`. При смене пароля: `python create_hash.py` → `UPDATE users SET password_hash = … WHERE login = …`.

Дополнительно (опционально): `python scripts/seed_it_admin.py` — локация «Отдел ИТ» и привязка admin (устаревает при полном `db reset` — всё уже в `seed.sql`).

---

## Изменение схемы (рабочий цикл)

### Рекомендуемый путь (миграции в репозитории)

1. Правка существующего файла в `supabase/migrations/` **или** новая миграция:

   ```powershell
   supabase migration new add_something
   ```

2. Проверка локально (нужен Docker):

   ```powershell
   pnpm db:reset    # supabase db reset — локально + seed
   ```

3. Деплой в облако:

   ```powershell
   pnpm db:push
   ```

4. Сверка:

   ```powershell
   supabase migration list --linked
   ```

### Если правили схему в Dashboard (SQL Editor)

Подтянуть diff в файл миграции:

```powershell
supabase db pull --linked <имя_миграции>
```

Или сравнить linked vs локальные миграции:

```powershell
supabase db diff --linked
supabase db diff --linked -f <имя_новой_миграции>
```

После pull/diff — просмотреть SQL, закоммитить файл, снова `db push` обычно не нужен (remote уже совпадает), но local history должна быть в git.

---

## Опасные операции

| Команда | Эффект на облаке |
|---------|------------------|
| `supabase db reset --linked` | **Полное уничтожение** данных public + повторные миграции + seed |
| `supabase db push --linked --include-all` | Принудительно применить миграции, отсутствующие в remote history (осторожно при рассинхроне) |

Перед reset на shared/staging — бэкап:

```powershell
pnpm db:dump:cloud
```

Файл `supabase/schema.sql` в gitignore; храните дамп отдельно, если нужен.

---

## Сбой миграций и repair

Если remote history и фактическая схема разошлись (ручные правки, прерванный push):

```powershell
supabase migration list --linked
supabase migration repair --help
```

`repair` помечает версии в `supabase_migrations.schema_migrations` — используйте осознанно, сверяясь с Dashboard → Database → Migrations.

---

## Supabase MCP (Cursor / IDE)

В workspace может быть MCP-сервер Supabase (`execute_sql`, `list_tables`, `apply_migration`, `get_advisors`, …).

| Инструмент | Когда |
|------------|--------|
| `list_tables` / `execute_sql` | Быстрая проверка данных и запросов на **linked** проекте |
| `get_advisors` | Security/performance после изменения схемы |
| `apply_migration` | Удобно для remote, но **каждый вызов пишет запись в history** — для итераций лучше править `supabase/migrations/` и `db push` |

Для локальной разработки MCP не заменяет CLI: миграции в git → `db push --linked`.

---

## Типичные проблемы

### «Cannot connect» / timeout при link или push

- Проверить пароль БД (Settings → Database; при необходимости Reset database password).
- Попробовать прямое подключение: `supabase link --project-ref <ref> --skip-pooler`.
- Убедиться, что проект не **Paused** (Dashboard → Restore project).

### Версия Postgres не совпадает

В `supabase/config.toml`: `db.major_version = 17` должна совпадать с облаком (Dashboard → Database → Version).

### `db push`: migration already applied / ordering

Сравнить `supabase migration list --linked` — локальные файлы без пары на remote нужно push; лишние на remote — `repair` или согласование с командой.

### Приложение не видит таблицы

- `.env`: правильные `SUPABASE_URL` и **service_role** `SUPABASE_KEY`.
- После push — обновить PostgREST schema cache (обычно автоматически; при необходимости перезапуск проекта в Dashboard).
- TMS не использует Supabase Auth для пользователей приложения — таблица `users` своя; RLS/grants см. `040_grants.sql`.

### CLI на Windows

Команды выполнять из корня репозитория. При ошибках с Docker — для **облака** Docker не обязателен (нужен только для `supabase start` / локального `db reset`).

---

## Шпаргалка: local vs cloud

| | Локально (`--local`) | Облако (`--linked`) |
|--|----------------------|---------------------|
| Нужен Docker | Да | Нет |
| URL для `.env` | `http://127.0.0.1:55321` (см. `supabase status`) | `https://<ref>.supabase.co` |
| Сброс с seed | `pnpm db:reset` | `pnpm db:reset:cloud` ⚠️ |
| Push миграций | `supabase db push --local` | `pnpm db:push` |
| Порты API/DB | 55321 / 55322 (`config.toml`) | Dashboard |

---

## Полезные ссылки

- [Supabase CLI reference](https://supabase.com/docs/reference/cli/introduction)
- [Database migrations](https://supabase.com/docs/guides/deployment/database-migrations)
- [Linking / connecting to project](https://supabase.com/docs/guides/cli/managing-environments)

---

## Минимальный чеклист «облако готово»

- [ ] `supabase login`
- [ ] `supabase link --project-ref …`
- [ ] `.env` с URL и service_role
- [ ] `pnpm db:push` или `pnpm db:reset:cloud` на пустой БД
- [ ] `python create_hash.py` → hash для `admin`
- [ ] `uvicorn main:app --reload` → `/health`, вход **admin**/**clerk**/**master** (`{login}123`)
