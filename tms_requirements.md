# Техническое задание: АИС TMS (Tool Management System) для ОАО "БААЗ"

## 1. Общее описание
Система предназначена для автоматизации учета, выдачи и обслуживания инструментов и технологической оснастки. 
Система интегрируется с модулем CMMS (учет оборудования) для проверки оснований выдачи инструментов.

## 2. Технологический стек
- **Backend:** Python (FastAPI)
- **Database:** PostgreSQL (Supabase)
- **Auth:** Supabase Auth
- **ID Generation:** UUID (расширение uuid-ossp)
- **Prefix:** Все таблицы системы должны иметь префикс `tms_`

## 3. Структура базы данных (ER)

### 3.1. Ядро (Core)
- `tms_locations`: Физические места (Цех №1, Участок заточки). Поля: `id (uuid, PK)`, `name (string)`.
- `tms_warehouses`: Склады/Кладовые (ИРК-1, ИРК-2). Поля: `id (uuid, PK)`, `name (string)`, `location_id (uuid, FK)`.
- `tms_employees`: Сотрудники завода. Поля: `id (uuid, PK)`, `badge_number (string, unique)`, `full_name (string)`, `location_id (uuid, FK)`.

### 3.2. Инструментарий
- `tms_tool_categories`: Категории (Режущий, Мерительный). Поля: `id (uuid, PK)`, `name (string)`.
- `tms_tool_types`: Типы/Модели (Микрометр МК-25). Поля: `id (uuid, PK)`, `model_name (string)`, `category_id (uuid, FK)`.
- `tms_tools`: Конкретные экземпляры. 
    - Поля: `id (uuid, PK)`, `type_id (uuid, FK)`, `warehouse_id (uuid, FK)`.
    - `inventory_number (string, nullable)`, `serial_number (string, nullable)`.
    - `status (enum)`: 'available', 'in_use', 'maintenance', 'scrapped'.
    - `wear_count (int)`, `last_check (date)`.

### 3.3. Логи и пользователи
- `tms_users`: Пользователи системы. 
    - Поля: `id (uuid, PK)`, `employee_id (uuid, FK)`, `warehouse_id (uuid, FK, nullable)` - привязка кладовщика к складу.
    - `role`: 'admin', 'clerk', 'master'.
- `tms_issuance_log`: Журнал выдачи.
    - Поля: `id (uuid, PK)`, `tool_id (uuid, FK)`, `employee_id (uuid, FK)`, `issued_by (uuid, FK to users)`.
    - `issued_at (timestamp)`, `returned_at (timestamp, nullable)`.
    - `condition_on_return (string, nullable)`.
    - `external_order_id (uuid, nullable)` - связь с системой CMMS.

## 4. Бизнес-логика и Триггеры
1. **Блокировка выдачи:** Нельзя выдать инструмент, если его статус не 'available'.
2. **Авто-обслуживание:** Если при возврате `condition_on_return` содержит "требует заточки/ремонта", статус инструмента автоматически меняется на 'maintenance'.
3. **Лимит выдачи:** Триггер, запрещающий выдавать более 5 мерительных инструментов одному сотруднику одновременно.

## 5. Требования к API (Endpoints)
- `GET /tools/`: Список инструментов с фильтрацией по складу и статусу.
- `POST /issuance/issue`: Выдача инструмента (с проверкой `external_order_id`).
- `POST /issuance/return`: Возврат с обязательной фиксацией тех. состояния.
- `GET /analytics/overdue`: Список инструментов с истекшим сроком поверки.

## 6. Интеграция (см. integration_cmms.md)
- При выдаче инструмента проверять существование `order_id` в системе CMMS.