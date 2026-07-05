-- Демо-данные для локальной разработки АИС TMS.

-- Локации (цеха)
insert into locations (id, name)
values
    (gen_random_uuid(), 'Механический цех №1'),
    (gen_random_uuid(), 'Сборочный цех №2'),
    (gen_random_uuid(), 'Инструментальный отдел');

-- Склады (ИРК) — фиксированный UUID ИРК-1 для интеграции с CMMS fixtures
insert into warehouses (id, name, location_id)
values
    ('a1000000-0000-4000-8000-000000000001', 'ИРК-1 (Мехцех)', (select id from locations where name = 'Механический цех №1' limit 1)),
    (gen_random_uuid(), 'ИРК-2 (Сборка)', (select id from locations where name = 'Сборочный цех №2' limit 1)),
    ('a1000000-0000-4000-8000-000000000003', 'Центральный склад инструмента', (select id from locations where name = 'Инструментальный отдел' limit 1));

-- Сотрудники
insert into employees (id, badge_number, full_name, gender, birth_date, location_id)
values
    (gen_random_uuid(), '1001', 'Иванов Иван Иванович', 'муж', '1980-05-15', (select id from locations where name = 'Механический цех №1' limit 1)),
    (gen_random_uuid(), '1002', 'Петрова Анна Сергеевна', 'жен', '1968-03-20', (select id from locations where name = 'Сборочный цех №2' limit 1)),
    (gen_random_uuid(), '1003', 'Сидоров Алексей Петрович', 'муж', '2005-10-10', (select id from locations where name = 'Механический цех №1' limit 1));

-- Категории инструмента
insert into tool_categories (id, name)
values
    (gen_random_uuid(), 'Режущий инструмент'),
    (gen_random_uuid(), 'Мерительный инструмент'),
    (gen_random_uuid(), 'Слесарно-монтажный инструмент');

-- Типы инструмента (номенклатура)
insert into tool_types (id, model_name, category_id, specs, min_stock)
values
    (gen_random_uuid(), 'Сверло твердосплавное 12мм', (select id from tool_categories where name = 'Режущий инструмент' limit 1), '{"material": "ВК8", "gost": "10903-77"}', 10),
    (gen_random_uuid(), 'Микрометр МК-25 0.01', (select id from tool_categories where name = 'Мерительный инструмент' limit 1), '{"range": "0-25mm", "accuracy": "0.01"}', 5),
    (gen_random_uuid(), 'Штангенциркуль ШЦ-I-125', (select id from tool_categories where name = 'Мерительный инструмент' limit 1), '{"range": "0-125mm"}', 8),
    (gen_random_uuid(), 'Ключ динамометрический 1/2"', (select id from tool_categories where name = 'Слесарно-монтажный инструмент' limit 1), '{"torque": "40-210 Nm"}', 3);

-- Экземпляры инструмента
insert into tools (id, type_id, warehouse_id, inventory_number, serial_number, status, wear_count, last_check)
values
    ('d1000000-0000-4000-8000-000000000001', (select id from tool_types where model_name = 'Микрометр МК-25 0.01' limit 1), (select id from warehouses where name = 'ИРК-1 (Мехцех)' limit 1), 'БААЗ-00142', 'SN-2024-001', 'available', 0, '2024-01-10'),
    (gen_random_uuid(), (select id from tool_types where model_name = 'Микрометр МК-25 0.01' limit 1), (select id from warehouses where name = 'ИРК-1 (Мехцех)' limit 1), 'БААЗ-00143', 'SN-2024-002', 'available', 2, '2023-11-15'),
    (gen_random_uuid(), (select id from tool_types where model_name = 'Сверло твердосплавное 12мм' limit 1), (select id from warehouses where name = 'ИРК-1 (Мехцех)' limit 1), 'БААЗ-00501', null, 'available', 5, null),
    (gen_random_uuid(), (select id from tool_types where model_name = 'Штангенциркуль ШЦ-I-125' limit 1), (select id from warehouses where name = 'ИРК-2 (Сборка)' limit 1), 'БААЗ-00888', 'SN-999-XYZ', 'maintenance', 10, '2024-06-01');

-- Отдел ИТ и сотрудник для учётной записи admin
insert into locations (name)
select 'Отдел ИТ'
where not exists (select 1 from locations where name = 'Отдел ИТ');

insert into employees (badge_number, full_name, gender, location_id)
select '0001', 'Васильев Алексей Игоревич', 'муж', l.id
from locations l
where l.name = 'Отдел ИТ'
  and not exists (select 1 from employees where badge_number = '0001');

-- Демо-учётные записи TMS (пароль: {login}123, bcrypt — см. create_hash.py)
-- admin — администратор (Отдел ИТ)
insert into users (login, password_hash, role)
values ('admin', '$2b$12$1eGCVNVt4jebUkOC6Im8Wemk1FDAod1FXeQiWRAEEsf9DuI3q4Rmy', 'admin');

update users u
set employee_id = e.id
from employees e
where u.login = 'admin'
  and e.badge_number = '0001';

-- clerk — кладовщик ИРК-1 (Мехцех), сотрудник 1001
insert into users (login, password_hash, role, employee_id, warehouse_id)
values (
    'clerk',
    '$2b$12$LscZCWb7aSOHPQL0uB35S.UGf2xlmLgdmoRP5eKSgu1KIDPkcNuSa',
    'clerk',
    (select id from employees where badge_number = '1001' limit 1),
    'a1000000-0000-4000-8000-000000000001'
);

-- master — мастер инструментального хозяйства
insert into employees (badge_number, full_name, gender, location_id)
select '2001', 'Козлов Сергей Николаевич', 'муж', l.id
from locations l
where l.name = 'Инструментальный отдел'
  and not exists (select 1 from employees where badge_number = '2001');

insert into users (login, password_hash, role, employee_id)
values (
    'master',
    '$2b$12$kBTIXn9DKPg2GZkBbhOIMuu2PBTbNLispapseCGHzNE6MXIjV.dqO',
    'master',
    (select id from employees where badge_number = '2001' limit 1)
);
