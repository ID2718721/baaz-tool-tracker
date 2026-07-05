"""Однократное наполнение: Отдел ИТ, сотрудник Васильев, привязка admin."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core.supabase import get_supabase_client


def main() -> None:
    supabase = get_supabase_client()

    loc_resp = (
        supabase.table("tms_locations")
        .select("id")
        .eq("name", "Отдел ИТ")
        .limit(1)
        .execute()
    )
    if loc_resp.data:
        location_id = loc_resp.data[0]["id"]
        print(f"Локация «Отдел ИТ» уже есть: {location_id}")
    else:
        ins = supabase.table("tms_locations").insert({"name": "Отдел ИТ"}).select("id").execute()
        location_id = ins.data[0]["id"]
        print(f"Создана локация «Отдел ИТ»: {location_id}")

    emp_resp = (
        supabase.table("tms_employees")
        .select("id, full_name")
        .eq("badge_number", "0001")
        .limit(1)
        .execute()
    )
    if emp_resp.data:
        employee_id = emp_resp.data[0]["id"]
        print(f"Сотрудник 0001 уже есть: {emp_resp.data[0]['full_name']} ({employee_id})")
    else:
        ins = (
            supabase.table("tms_employees")
            .insert(
                {
                    "badge_number": "0001",
                    "full_name": "Васильев Алексей Игоревич",
                    "gender": "муж",
                    "location_id": location_id,
                }
            )
            .select("id")
            .execute()
        )
        employee_id = ins.data[0]["id"]
        print(f"Создан сотрудник Васильев А.И.: {employee_id}")

    admin_resp = (
        supabase.table("tms_users")
        .select("id, login, employee_id")
        .eq("login", "admin")
        .limit(1)
        .execute()
    )
    if not admin_resp.data:
        print("Пользователь admin не найден — пропуск привязки")
        return

    admin = admin_resp.data[0]
    supabase.table("tms_users").update({"employee_id": employee_id}).eq("id", admin["id"]).execute()
    print(f"Пользователь admin привязан к employee_id={employee_id}")


if __name__ == "__main__":
    main()
