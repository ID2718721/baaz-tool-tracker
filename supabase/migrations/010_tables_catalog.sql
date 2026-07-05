-- Справочники организации, номенклатура, экземпляры, пользователи.

create table locations (
    id uuid primary key default gen_random_uuid(),
    name text not null
);

create table warehouses (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    location_id uuid references locations (id)
);

create table employees (
    id uuid primary key default gen_random_uuid(),
    badge_number text unique not null,
    full_name text not null,
    gender text check (gender in ('муж', 'жен')),
    birth_date date,
    hire_date date default current_date,
    location_id uuid references locations (id)
);

create table tool_categories (
    id uuid primary key default gen_random_uuid(),
    name text not null
);

create table tool_types (
    id uuid primary key default gen_random_uuid(),
    model_name text not null,
    category_id uuid references tool_categories (id),
    specs jsonb,
    min_stock int default 5
);

create table tools (
    id uuid primary key default gen_random_uuid(),
    type_id uuid references tool_types (id),
    warehouse_id uuid references warehouses (id),
    inventory_number text,
    serial_number text,
    status text default 'available' check (status in (
        'available', 'in_use', 'maintenance', 'scrapped',
        'pending_repair', 'pending_return'
    )),
    wear_count int default 0,
    last_check date
);

create table users (
    id uuid primary key default gen_random_uuid(),
    employee_id uuid references employees (id),
    warehouse_id uuid references warehouses (id),
    login text unique not null,
    password_hash text not null,
    role text check (role in ('admin', 'clerk', 'master')) not null,
    created_at timestamptz default now()
);
