# Роли и права доступа

Система использует три роли: **admin** (администратор), **master** (мастер инструментального хозяйства), **clerk** (кладовщик).

Проверка прав — через зависимости FastAPI в `app/api/deps.py`. HTML-страницы дополнительно ограничиваются в `pages.py` (`_require_roles`).

## Сводная таблица

| Ресурс / действие | Admin | Master | Clerk |
|-------------------|:-----:|:------:|:-----:|
| **Главная** (`/`) | ✅ дашборд | ✅ дашборд | ✅ дашборд |
| **Пользователи** (`/admin/users`) | ✅ CRUD | ❌ | ❌ |
| **Цеха и склады** (`/admin/structure`) | ✅ CRUD | ❌ | ❌ |
| **Справочник** (`/master/catalog`) | ✅ CRUD | ✅ CRUD | ❌ |
| **Структура** (`/master/structure`) | ✅ CRUD | ✅ CRUD | ❌ |
| **Инвентарь** (`/inventory`) | 👁 только просмотр | ✅ CRUD* | ✅ CRUD + выдача/возврат |
| **Заявки** (`/requisitions`) | ❌ | ❌ | ✅ резерв/выдача/возврат |
| **Аналитика** (`/analytics`) | ✅ | ✅ | ❌ |
| Excel: остатки склада | ❌** | ✅ | ✅ (свой склад) |
| Excel: списания | ✅ | ✅ | ✅ |
| Word: акт списания | 👁 (скачать) | 👁 | 👁 (для списанных) |

\* Master создаёт/редактирует/удаляет инструменты; удаление — только master.  
\** Admin видит инвентарь, но кнопка Excel на UI доступна кладовщику при одном складе.

## Детализация по ролям

### Admin (администратор)

**Страницы:** `/`, `/admin/users`, `/admin/structure`, `/inventory`, `/master/catalog`, `/master/structure`, `/analytics`

**API:**

| Метод | Путь | Действие |
|-------|------|----------|
| GET/POST/PUT/DELETE | `/api/v1/admin/users` | Управление пользователями |
| GET/POST/PUT/DELETE | `/api/v1/admin/locations` | Цеха (админ-API) |
| GET/POST/PUT/DELETE | `/api/v1/admin/warehouses` | Склады (админ-API) |
| POST/PUT/DELETE | `/api/v1/master/*` | Справочники и структура (режим admin) |
| GET | `/api/v1/analytics/*` | Аналитика |
| GET | `/api/v1/reports/export/*` | Отчёты |

**Ограничения:**

- Не может удалить собственную учётную запись.
- Инвентарь — только просмотр (`read_only=true` в шаблоне).
- Нет доступа к `/requisitions` и операциям выдачи.

### Master (мастер)

**Страницы:** `/`, `/master/catalog`, `/master/structure`, `/analytics`, `/inventory`

**API:**

| Метод | Путь | Действие |
|-------|------|----------|
| POST/PUT/DELETE | `/api/v1/master/locations` | Цеха |
| POST/PUT/DELETE | `/api/v1/master/warehouses` | Склады |
| POST/PUT/DELETE | `/api/v1/master/categories` | Категории инструмента |
| POST/PUT/DELETE | `/api/v1/master/tool-types` | Типы инструмента |
| GET/POST/PUT | `/api/v1/tools` | CRUD инструментов |
| DELETE | `/api/v1/tools/{id}` | Удаление инструмента |
| GET | `/api/v1/analytics/*` | Аналитика |
| GET | `/api/v1/reports/export/*` | Excel/Word |

**Ограничения:**

- Нет доступа к пользователям и admin-структуре.
- Нет заявок CMMS и внутренней выдачи (это зона кладовщика).

### Clerk (кладовщик)

**Страницы:** `/`, `/inventory`, `/requisitions`

**API:**

| Метод | Путь | Действие |
|-------|------|----------|
| GET/POST/PUT | `/api/v1/tools` | Инструменты своего склада |
| POST | `/api/v1/tools/internal/issue` | Внутренняя выдача сотруднику |
| POST | `/api/v1/tools/internal/return` | Приём возврата |
| POST | `/api/v1/requisitions/lines/{id}/reserve` | Резерв под CMMS-заявку |
| POST | `/api/v1/requisitions/{id}/issue` | Выдача комплекта |
| POST | `/api/v1/requisitions/lines/{id}/return` | Возврат по строке |
| GET | `/api/v1/reports/export/inventory/{warehouse_id}` | Excel остатков |

**Ограничения:**

- Видит только свой `warehouse_id` (фильтрация в API и UI).
- Не может удалять инструменты.
- Нет аналитики, справочников, управления пользователями.

## Матрица CRUD по сущностям

| Сущность | Admin | Master | Clerk |
|----------|-------|--------|-------|
| `tms_users` | CRUD | — | — |
| `tms_locations` | CRUD | CRUD | — |
| `tms_warehouses` | CRUD | CRUD | — |
| `tms_tool_categories` | CRUD | CRUD | — |
| `tms_tool_types` | CRUD | CRUD | — |
| `tms_tools` | R | CRUD | CRU (свой склад) |
| `tms_requisitions` | — | — | RU (операции) |
| Отчёты | R (export) | R (export) | R (inventory export) |

**Обозначения:** C — create, R — read, U — update, D — delete.

## Контекст шаблонов Jinja2

Передаётся из `_page_context()` в `pages.py`:

| Переменная | Admin | Master | Clerk |
|------------|-------|--------|-------|
| `is_admin` | true | false | false |
| `is_master` | false | true | false |
| `is_clerk` | false | false | true |
| `can_edit_tools` | false | true | true |
| `can_delete_tools` | false | true | false |
| `can_add_tools` | false | true | true |
| `read_only` (inventory) | true | false | false |
