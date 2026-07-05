-- Доступ PostgREST / service_role (локальный Supabase не выдаёт права автоматически).

grant usage on schema public to anon, authenticated, service_role;

grant select, insert, update, delete on table
    locations,
    warehouses,
    employees,
    tool_categories,
    tool_types,
    tools,
    requisitions,
    requisition_lines,
    users
to service_role;

grant select on table
    locations,
    warehouses,
    employees,
    tool_categories,
    tool_types,
    tools,
    requisitions,
    requisition_lines,
    users
to anon, authenticated;
