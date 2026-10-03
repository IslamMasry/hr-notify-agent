import sqlite3
from datetime import datetime, timezone
from config import AUDIT_DB_PATH


def _get_conn():
    conn = sqlite3.connect(AUDIT_DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            channel TEXT NOT NULL DEFAULT 'email',
            employee_name TEXT NOT NULL,
            employee_email TEXT NOT NULL,
            task_title TEXT NOT NULL,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            status TEXT NOT NULL,
            error TEXT,
            call_outcome TEXT
        )
    """)
    # migration بسيطة لو الجدول كان موجود من نسخة أقدم
    cols = [r[1] for r in conn.execute("PRAGMA table_info(audit_log)").fetchall()]
    if "channel" not in cols:
        conn.execute("ALTER TABLE audit_log ADD COLUMN channel TEXT NOT NULL DEFAULT 'email'")
    if "call_outcome" not in cols:
        conn.execute("ALTER TABLE audit_log ADD COLUMN call_outcome TEXT")
    return conn


def init_db():
    """يتأكد إن الجدول موجود - يُستدعى عند بدء تشغيل السيرفر."""
    _get_conn().close()


def log_action(employee_name, employee_email, task_title, subject, body, status,
                error=None, channel="email", call_outcome=None):
    conn = _get_conn()
    conn.execute(
        """INSERT INTO audit_log
           (timestamp, channel, employee_name, employee_email, task_title, subject, body, status, error, call_outcome)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            datetime.now(timezone.utc).isoformat(),
            channel,
            employee_name,
            employee_email,
            task_title,
            subject,
            body,
            status,
            error,
            call_outcome,
        ),
    )
    conn.commit()
    conn.close()


def get_campaigns_summary() -> list[dict]:
    """
    بيرجع ملخص كل التاسكات (campaigns) اللي اتنفذت - مجمّعة بالعنوان، مش تاسك واحدة ثابتة.
    ده أساس شاشة الـ Monitoring الحقيقية اللي بتتابع كل حاجة، مش تاسك بعينها.
    """
    conn = _get_conn()
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT
            task_title,
            COUNT(*) as total_actions,
            SUM(CASE WHEN channel = 'email' THEN 1 ELSE 0 END) as email_count,
            SUM(CASE WHEN channel = 'call' THEN 1 ELSE 0 END) as call_count,
            MAX(timestamp) as last_action_at,
            MIN(timestamp) as first_action_at
        FROM audit_log
        WHERE task_title != '-'
        GROUP BY task_title
        ORDER BY last_action_at DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]
