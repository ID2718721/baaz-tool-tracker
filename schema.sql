-- Включаем UUID
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. Справочники
CREATE TABLE tms_locations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL
);

CREATE TABLE tms_warehouses (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    location_id UUID REFERENCES tms_locations(id)
);

CREATE TABLE tms_employees (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    badge_number TEXT UNIQUE NOT NULL,
    full_name TEXT NOT NULL,
    gender TEXT CHECK (gender IN ('муж', 'жен')),
    birth_date DATE,
    hire_date DATE DEFAULT CURRENT_DATE,
    location_id UUID REFERENCES tms_locations(id)
);

-- 2. Инструментарий
CREATE TABLE tms_tool_categories (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL
);

CREATE TABLE tms_tool_types (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    model_name TEXT NOT NULL,
    category_id UUID REFERENCES tms_tool_categories(id),
    specs JSONB,
    min_stock INT DEFAULT 5
);

CREATE TABLE tms_tools (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    type_id UUID REFERENCES tms_tool_types(id),
    warehouse_id UUID REFERENCES tms_warehouses(id),
    inventory_number TEXT,
    serial_number TEXT,
    status TEXT DEFAULT 'available' CHECK (status IN ('available', 'in_use', 'maintenance', 'scrapped')),
    wear_count INT DEFAULT 0,
    last_check DATE
);

-- 3. Контур Б (Интеграция с CMMS)
CREATE TABLE tms_requisitions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_reference_id UUID UNIQUE NOT NULL,
    warehouse_id UUID REFERENCES tms_warehouses(id),
    external_order_id UUID, -- Связь с CMMS
    status TEXT DEFAULT 'new',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    technician_name TEXT,
    cancelled_at TIMESTAMP WITH TIME ZONE,
    cancel_reason TEXT
);

CREATE TABLE tms_requisition_lines (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    requisition_id UUID REFERENCES tms_requisitions(id) ON DELETE CASCADE,
    line_client_id UUID NOT NULL,
    catalog_item_id UUID REFERENCES tms_tool_types(id),
    tool_id UUID REFERENCES tms_tools(id), -- Конкретный экземпляр (привязывается при резерве)
    status TEXT DEFAULT 'pending'
);

-- 1. ТРИГГЕР: Лимит выдачи (Max 5 инструментов на руки)
CREATE OR REPLACE FUNCTION tms_check_tool_limit() RETURNS TRIGGER AS $$
BEGIN
    IF (SELECT COUNT(*) FROM tms_requisition_lines 
        WHERE requisition_id = NEW.requisition_id AND status = 'issued') >= 5 THEN
        RAISE EXCEPTION 'Превышен лимит выдачи: один сотрудник не может иметь более 5 активных инструментов';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_tool_limit
BEFORE UPDATE ON tms_requisition_lines
FOR EACH ROW WHEN (NEW.status = 'issued' AND OLD.status != 'issued')
EXECUTE FUNCTION tms_check_tool_limit();


-- 2. ТРИГГЕР: Авто-перевод в ремонт (на основе комментария кладовщика)
ALTER TABLE tms_requisition_lines ADD COLUMN condition_on_return TEXT;

CREATE OR REPLACE FUNCTION tms_auto_maintenance_status() RETURNS TRIGGER AS $$
BEGIN
    -- Если в примечании есть слова "заточ", "ремонт", "сломан", "неисправ"
    IF NEW.condition_on_return ILIKE '%заточ%' OR 
       NEW.condition_on_return ILIKE '%ремонт%' OR 
       NEW.condition_on_return ILIKE '%сломан%' THEN
        
        UPDATE tms_tools 
        SET status = 'maintenance' 
        WHERE id = NEW.tool_id;
        
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_auto_maintenance
AFTER UPDATE ON tms_requisition_lines
FOR EACH ROW WHEN (NEW.status = 'returned' AND NEW.condition_on_return IS NOT NULL)
EXECUTE FUNCTION tms_auto_maintenance_status();


-- 3. ТРИГГЕР: Запрет выдачи неисправного инструмента
CREATE OR REPLACE FUNCTION tms_check_tool_availability() RETURNS TRIGGER AS $$
BEGIN
    IF (SELECT status FROM tms_tools WHERE id = NEW.tool_id) != 'available' THEN
        RAISE EXCEPTION 'Невозможно выдать инструмент: текущий статус — %', 
        (SELECT status FROM tms_tools WHERE id = NEW.tool_id);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_check_availability
BEFORE UPDATE ON tms_requisition_lines
FOR EACH ROW WHEN (NEW.status = 'reserved') -- Проверка в момент бронирования серийника
EXECUTE FUNCTION tms_check_tool_availability();

-- 1. Очистка (необязательно, но полезно для чистого старта)
-- DELETE FROM tms_tools; DELETE FROM tms_tool_types; DELETE FROM tms_warehouses; DELETE FROM tms_locations;

-- 2. Добавляем Локации (Цеха)
INSERT INTO tms_locations (id, name) VALUES 
(uuid_generate_v4(), 'Механический цех №1'),
(uuid_generate_v4(), 'Сборочный цех №2'),
(uuid_generate_v4(), 'Инструментальный отдел');

-- 3. Добавляем Склады (ИРК)
-- Используем подзапросы, чтобы привязать склады к цехам
INSERT INTO tms_warehouses (id, name, location_id) VALUES 
(uuid_generate_v4(), 'ИРК-1 (Мехцех)', (SELECT id FROM tms_locations WHERE name = 'Механический цех №1' LIMIT 1)),
(uuid_generate_v4(), 'ИРК-2 (Сборка)', (SELECT id FROM tms_locations WHERE name = 'Сборочный цех №2' LIMIT 1)),
(uuid_generate_v4(), 'Центральный склад инструмента', (SELECT id FROM tms_locations WHERE name = 'Инструментальный отдел' LIMIT 1));

-- 4. Добавляем Сотрудников (для тестов выдачи)
INSERT INTO tms_employees (id, badge_number, full_name, gender, birth_date, location_id) VALUES 
(uuid_generate_v4(), '1001', 'Иванов Иван Иванович', 'муж', '1980-05-15', (SELECT id FROM tms_locations WHERE name = 'Механический цех №1' LIMIT 1)),
(uuid_generate_v4(), '1002', 'Петрова Анна Сергеевна', 'жен', '1968-03-20', (SELECT id FROM tms_locations WHERE name = 'Сборочный цех №2' LIMIT 1)), -- пенсионерка для запроса
(uuid_generate_v4(), '1003', 'Сидоров Алексей Петрович', 'муж', '2005-10-10', (SELECT id FROM tms_locations WHERE name = 'Механический цех №1' LIMIT 1)); -- молодой сотрудник

-- 5. Категории инструмента
INSERT INTO tms_tool_categories (id, name) VALUES 
(uuid_generate_v4(), 'Режущий инструмент'),
(uuid_generate_v4(), 'Мерительный инструмент'),
(uuid_generate_v4(), 'Слесарно-монтажный инструмент');

-- 6. Типы инструмента (Номенклатура)
INSERT INTO tms_tool_types (id, model_name, category_id, specs, min_stock) VALUES 
(uuid_generate_v4(), 'Сверло твердосплавное 12мм', (SELECT id FROM tms_tool_categories WHERE name = 'Режущий инструмент' LIMIT 1), '{"material": "ВК8", "gost": "10903-77"}', 10),
(uuid_generate_v4(), 'Микрометр МК-25 0.01', (SELECT id FROM tms_tool_categories WHERE name = 'Мерительный инструмент' LIMIT 1), '{"range": "0-25mm", "accuracy": "0.01"}', 5),
(uuid_generate_v4(), 'Штангенциркуль ШЦ-I-125', (SELECT id FROM tms_tool_categories WHERE name = 'Мерительный инструмент' LIMIT 1), '{"range": "0-125mm"}', 8),
(uuid_generate_v4(), 'Ключ динамометрический 1/2"', (SELECT id FROM tms_tool_categories WHERE name = 'Слесарно-монтажный инструмент' LIMIT 1), '{"torque": "40-210 Nm"}', 3);

-- 7. Конкретные экземпляры инструмента (TOOLS)
INSERT INTO tms_tools (id, type_id, warehouse_id, inventory_number, serial_number, status, wear_count, last_check) VALUES 
(uuid_generate_v4(), (SELECT id FROM tms_tool_types WHERE model_name = 'Микрометр МК-25 0.01' LIMIT 1), (SELECT id FROM tms_warehouses WHERE name = 'ИРК-1 (Мехцех)' LIMIT 1), 'БААЗ-00142', 'SN-2024-001', 'available', 0, '2024-01-10'),
(uuid_generate_v4(), (SELECT id FROM tms_tool_types WHERE model_name = 'Микрометр МК-25 0.01' LIMIT 1), (SELECT id FROM tms_warehouses WHERE name = 'ИРК-1 (Мехцех)' LIMIT 1), 'БААЗ-00143', 'SN-2024-002', 'available', 2, '2023-11-15'),
(uuid_generate_v4(), (SELECT id FROM tms_tool_types WHERE model_name = 'Сверло твердосплавное 12мм' LIMIT 1), (SELECT id FROM tms_warehouses WHERE name = 'ИРК-1 (Мехцех)' LIMIT 1), 'БААЗ-00501', NULL, 'available', 5, NULL),
(uuid_generate_v4(), (SELECT id FROM tms_tool_types WHERE model_name = 'Штангенциркуль ШЦ-I-125' LIMIT 1), (SELECT id FROM tms_warehouses WHERE name = 'ИРК-2 (Сборка)' LIMIT 1), 'БААЗ-00888', 'SN-999-XYZ', 'maintenance', 10, '2024-06-01');

-- Таблица пользователей
CREATE TABLE tms_users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    employee_id UUID REFERENCES tms_employees(id),
    warehouse_id UUID REFERENCES tms_warehouses(id), -- За каким складом закреплен (для кладовщика)
    login TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT CHECK (role IN ('admin', 'clerk', 'master')) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Добавим тестового админа (пароль захешируем позже через код, пока просто заглушка)
-- Логин: admin / Пароль: admin123
INSERT INTO tms_users (login, password_hash, role) 
VALUES ('admin', 'pbkdf2:sha256:250000$admin_hash', 'admin');

-- Отдел ИТ и сотрудник для учётной записи admin
INSERT INTO tms_locations (name)
SELECT 'Отдел ИТ'
WHERE NOT EXISTS (SELECT 1 FROM tms_locations WHERE name = 'Отдел ИТ');

INSERT INTO tms_employees (badge_number, full_name, gender, location_id)
SELECT '0001', 'Васильев Алексей Игоревич', 'муж', l.id
FROM tms_locations l
WHERE l.name = 'Отдел ИТ'
  AND NOT EXISTS (SELECT 1 FROM tms_employees WHERE badge_number = '0001');

UPDATE tms_users u
SET employee_id = e.id
FROM tms_employees e
WHERE u.login = 'admin'
  AND e.badge_number = '0001';