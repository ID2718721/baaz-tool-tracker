# АИС TMS — Система управления инструментом ОАО «БААЗ»

Веб-приложение для учёта, выдачи, возврата и аналитики инструмента на производстве. Разработано для ОАО «БААЗ» (г. Барановичи).

## Возможности

- Учёт экземпляров инструмента по складам (ИРК)
- Выдача и возврат (кладовщик), интеграция с заявками CMMS
- Справочники номенклатуры и организационная структура
- Аналитика: пенсионеры, просроченная поверка, износ
- Экспорт отчётов в Excel и актов списания в Word
- Ролевая модель: администратор, мастер, кладовщик

## Стек

FastAPI · Supabase (PostgreSQL) · Jinja2 · JWT (HttpOnly Cookie)

Подробнее: [docs/architecture.md](docs/architecture.md)

## Быстрый старт

### Требования

- Python 3.11+
- Аккаунт [Supabase](https://supabase.com) с развёрнутой схемой (`schema.sql`)

### 1. Клонирование и окружение

```bash
git clone https://github.com/YOUR_ORG/baaz-tms.git
cd baaz_tms

python -m venv venv

# Windows
venv\Scripts\activate

# Linux / macOS
source venv/bin/activate

pip install -r requirements.txt
```

### 2. Настройка `.env`

```bash
cp .env.example .env
```

Заполните переменные:

| Переменная | Описание |
|------------|----------|
| `SUPABASE_URL` | URL проекта Supabase |
| `SUPABASE_KEY` | Service role key |
| `JWT_SECRET_KEY` | Секрет для подписи JWT (длинная случайная строка) |
| `TMS_INTEGRATION_SECRET` | Секрет CMMS (опционально для dev) |

> Локальный `.env` имеет приоритет над системными переменными окружения.

### 3. База данных

Выполните SQL из файла `schema.sql` в Supabase SQL Editor.

Создайте хеш пароля администратора:

```bash
python create_hash.py
# Вставьте полученный hash в tms_users для login = admin
```

Демо-учётки после `supabase db reset` (см. `docs/database.md`): **admin**/**clerk**/**master**, пароль `{login}123`. Пересоздать хэши: `python create_hash.py`.

### 4. Запуск

```bash
uvicorn main:app --reload
```

Приложение: [http://127.0.0.1:8000](http://127.0.0.1:8000)

- Страница входа: `/login`
- Health check: `/health`
- OpenAPI (dev): `/docs`

## Скриншоты

<!-- TODO: замените заглушки на реальные URL после публикации -->

| Экран | Описание |
|-------|----------|
| ![Главная](docs/screenshots/home.png) | Главная страница (ролевой дашборд) |
| ![Инвентарь](docs/screenshots/inventory.png) | Реестр инструмента |
| ![Заявки](docs/screenshots/requisitions.png) | Заявки CMMS и внутренние |
| ![Аналитика](docs/screenshots/analytics.png) | Аналитика и экспорт отчётов |
| ![Пользователи](docs/screenshots/admin-users.png) | Управление пользователями |

> Папка `docs/screenshots/` — добавьте PNG и обновите ссылки в таблице.

## Структура проекта

```
baaz_tms/
├── app/           # Backend-приложение
├── templates/     # HTML-шаблоны Jinja2
├── docs/          # Документация
├── schema.sql     # Схема БД
├── main.py        # Точка входа
└── requirements.txt
```

## Документация

- [Архитектура](docs/architecture.md)
- [База данных и триггеры](docs/database.md)
- [Роли и права](docs/roles_and_permissions.md)
- [Интеграция CMMS](docs/integration.md)

## Лицензия

Проприетарное ПО ОАО «БААЗ». Распространение — по согласованию с правообладателем.
