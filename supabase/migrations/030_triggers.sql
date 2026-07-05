-- Триггеры доменной логики выдачи инструмента.

create or replace function check_tool_limit()
returns trigger
language plpgsql
as $$
begin
    if (
        select count(*)
        from requisition_lines
        where requisition_id = new.requisition_id
          and status = 'issued'
    ) >= 5 then
        raise exception 'Превышен лимит выдачи: один сотрудник не может иметь более 5 активных инструментов';
    end if;
    return new;
end;
$$;

create trigger trg_tool_limit
before update on requisition_lines
for each row
when (new.status = 'issued' and old.status != 'issued')
execute function check_tool_limit();

create or replace function auto_maintenance_status()
returns trigger
language plpgsql
as $$
begin
    if new.condition_on_return ilike '%заточ%'
       or new.condition_on_return ilike '%ремонт%'
       or new.condition_on_return ilike '%сломан%' then
        update tools
        set status = 'maintenance'
        where id = new.tool_id;
    end if;
    return new;
end;
$$;

create trigger trg_auto_maintenance
after update on requisition_lines
for each row
when (new.status = 'returned' and new.condition_on_return is not null)
execute function auto_maintenance_status();

create or replace function check_tool_availability()
returns trigger
language plpgsql
as $$
begin
    if (select status from tools where id = new.tool_id) != 'available' then
        raise exception 'Невозможно выдать инструмент: текущий статус — %',
            (select status from tools where id = new.tool_id);
    end if;
    return new;
end;
$$;

create trigger trg_check_availability
before update on requisition_lines
for each row
when (new.status = 'reserved')
execute function check_tool_availability();
