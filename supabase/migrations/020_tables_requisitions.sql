-- Заявки на выдачу инструмента (внутренние и через CMMS).

create table requisitions (
    id uuid primary key default gen_random_uuid(),
    client_reference_id uuid unique not null,
    warehouse_id uuid references warehouses (id),
    external_order_id uuid,
    status text default 'new',
    created_at timestamptz default now(),
    cancelled_at timestamptz,
    cancel_reason text
);

create table requisition_lines (
    id uuid primary key default gen_random_uuid(),
    requisition_id uuid references requisitions (id) on delete cascade,
    line_client_id uuid not null,
    kind text not null check (kind in ('catalog', 'free_text')),
    catalog_item_id uuid references tool_types (id),
    description text,
    quantity int not null default 1 check (quantity >= 1),
    tool_id uuid references tools (id),
    status text default 'pending',
    condition_on_return text
);

create index requisitions_external_order_id_idx on requisitions (external_order_id)
    where external_order_id is not null;
