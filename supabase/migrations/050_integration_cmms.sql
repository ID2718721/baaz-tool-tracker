-- Интеграция с CMMS: ссылки на наряды и заявки на ремонт.

create type cmms_work_order_kind as enum ('request', 'schedule');

create table cmms_work_order_links (
    requisition_id uuid primary key references requisitions (id) on delete cascade,
    cmms_work_order_id uuid not null,
    work_order_kind cmms_work_order_kind not null,
    cmms_work_order_number text,
    cmms_work_order_status text default 'new',
    cancelled_by text check (cancelled_by in ('dispatcher', 'storekeeper')),
    cancel_reason_text text,
    technician_badge text,
    technician_name text,
    last_synced_at timestamptz
);

create index cmms_work_order_links_work_order_idx
    on cmms_work_order_links (cmms_work_order_id, work_order_kind);

create table cmms_repair_links (
    id uuid primary key default gen_random_uuid(),
    tool_id uuid not null unique references tools (id),
    cmms_request_id uuid not null,
    cmms_request_number text,
    client_reference_id uuid not null unique,
    handoff_mode text check (handoff_mode in ('pickup_at_warehouse', 'deliver_to_department')),
    handoff_status text not null default 'pending' check (handoff_status in ('pending', 'completed')),
    warehouse_name text,
    handed_over_at timestamptz,
    handed_over_by uuid references users (id),
    returned_at timestamptz,
    returned_by uuid references users (id)
);

create or replace function sync_cmms_work_order_status()
returns trigger
language plpgsql
as $$
declare
    v_status text;
begin
    if new.cancelled_at is not null then
        v_status := 'cancelled';
    else
        v_status := new.status;
    end if;

    update cmms_work_order_links
    set cmms_work_order_status = v_status,
        last_synced_at = now()
    where requisition_id = new.id;
    return new;
end;
$$;

create trigger trg_sync_cmms_work_order_status
after insert or update of status, cancelled_at on requisitions
for each row
execute function sync_cmms_work_order_status();

grant select, insert, update, delete on table
    cmms_work_order_links,
    cmms_repair_links
to service_role;

grant select on table
    cmms_work_order_links,
    cmms_repair_links
to anon, authenticated;
