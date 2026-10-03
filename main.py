"""
تشغيل التاسك: بلّغ الموظفين + اطلب منهم حاجة + ديدلاين.

استخدام:
    python main.py              # dry-run: يطبع المسودات بس، مبيبعتش حاجة
    python main.py --send       # يبعت فعليًا (استخدمها بحذر!)
"""

import csv
import sys

from task_definition import TASK
from claude_client import draft_notification_email
from tools.email_sender import send_email
from audit_log import log_action


def load_employees(path="employees.csv"):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def run(dry_run: bool = True):
    employees = load_employees()
    print(f"عدد الموظفين: {len(employees)} | dry_run={dry_run}\n{'='*50}")

    for emp in employees:
        name, email, lang = emp["name"], emp["email"], emp["language"]
        print(f"\n>> بيصيغ الإيميل لـ: {name} ({email})")

        try:
            draft = draft_notification_email(name, lang, TASK)
        except Exception as e:
            print(f"   [خطأ في الصياغة] {e}")
            log_action(name, email, TASK["title"], "", "", "draft_failed", str(e))
            continue

        subject, body = draft["subject"], draft["body"]
        print(f"   الموضوع: {subject}")
        print(f"   ---\n{body}\n   ---")

        if not dry_run:
            try:
                send_email(email, subject, body)
                log_action(name, email, TASK["title"], subject, body, "sent")
                print("   ✅ اتبعت فعليًا")
            except Exception as e:
                log_action(name, email, TASK["title"], subject, body, "send_failed", str(e))
                print(f"   ❌ فشل الإرسال: {e}")
        else:
            log_action(name, email, TASK["title"], subject, body, "dry_run_only")
            print("   💡 dry-run: لم يتم الإرسال فعليًا")


if __name__ == "__main__":
    dry_run = "--send" not in sys.argv
    run(dry_run=dry_run)
