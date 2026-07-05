"""Временный скрипт: bcrypt-хэш пароля admin123 для tms_users.password_hash."""

from app.core.security import hash_password

if __name__ == "__main__":
    password = "admin123"
    hashed = hash_password(password)
    print(f"Пароль: {password}")
    print(f"Bcrypt hash:\n{hashed}")
    print("\nSQL для Supabase:")
    print(f"UPDATE tms_users SET password_hash = '{hashed}' WHERE login = 'admin';")
