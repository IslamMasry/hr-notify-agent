"""
Employee Store — CRUD كامل على employees.csv.
مفيش قاعدة بيانات هنا عمدًا (تبسيط للديمو) - الملف نفسه هو مصدر الحقيقة.
"""

import csv
import os
import shutil
from config import DATA_DIR

FIELDS = ["name", "email", "phone", "language", "department"]
CSV_PATH = os.path.join(DATA_DIR, "employees.csv")
_SEED_CSV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "employees.csv")


def list_employees() -> list[dict]:
    if not os.path.exists(CSV_PATH):
        # أول تشغيل على volume فاضي (نشر جديد) - انسخ الملف الأساسي من المشروع كـ seed
        if os.path.exists(_SEED_CSV_PATH):
            shutil.copy(_SEED_CSV_PATH, CSV_PATH)
        else:
            return []
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write_all(employees: list[dict]) -> None:
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for emp in employees:
            writer.writerow({k: emp.get(k, "") for k in FIELDS})


def add_employee(data: dict) -> dict:
    employees = list_employees()
    if any(e["email"] == data["email"] for e in employees):
        raise ValueError(f"موظف بنفس الإيميل موجود بالفعل: {data['email']}")
    new_emp = {k: data.get(k, "") for k in FIELDS}
    if not new_emp["name"] or not new_emp["email"]:
        raise ValueError("الاسم والإيميل مطلوبين")
    employees.append(new_emp)
    _write_all(employees)
    return new_emp


def update_employee(email: str, data: dict) -> dict:
    employees = list_employees()
    for i, emp in enumerate(employees):
        if emp["email"] == email:
            updated = {**emp, **{k: data[k] for k in FIELDS if k in data}}
            employees[i] = updated
            _write_all(employees)
            return updated
    raise ValueError(f"مفيش موظف بالإيميل ده: {email}")


def delete_employee(email: str) -> None:
    employees = list_employees()
    filtered = [e for e in employees if e["email"] != email]
    if len(filtered) == len(employees):
        raise ValueError(f"مفيش موظف بالإيميل ده: {email}")
    _write_all(filtered)
