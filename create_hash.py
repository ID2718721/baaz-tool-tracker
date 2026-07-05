"""Генерация bcrypt-хэшей демо-паролей для users.password_hash (supabase/seed.sql)."""

from app.core.security import hash_password

DEMO_USERS = (
    ("admin", "admin123"),
    ("clerk", "clerk123"),
    ("master", "master123"),
)

if __name__ == "__main__":
    for login, password in DEMO_USERS:
        hashed = hash_password(password)
        print(f"\n{login} / {password}")
        print(f"  hash: {hashed}")
        print(f"  SQL: UPDATE users SET password_hash = '{hashed}' WHERE login = '{login}';")
