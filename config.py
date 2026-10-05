import os

# مجلد البيانات الدائمة (CSV, SQLite, knowledge base) - في التشغيل المحلي بيبقى
# نفس مجلد المشروع تلقائيًا. في النشر (Railway/Render/إلخ)، اربطه بـ persistent
# volume عشان البيانات متتمسحش مع كل إعادة نشر:
#   DATA_DIR=/data
DATA_DIR = os.getenv("DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
os.makedirs(DATA_DIR, exist_ok=True)
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = "claude-sonnet-5-5"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "HR Department")

# الإيميل اللي التنبيهات (أسئلة/ردود محتاجة قرار HR Manager) بتتبعتله - افتراضيًا
# نفس حساب الإرسال (SMTP_USER)، لكن ممكن يبقى إيميل شخصي مختلف لو حابب
MANAGER_NOTIFY_EMAIL = os.getenv("MANAGER_NOTIFY_EMAIL", "") or SMTP_USER

IMAP_HOST = os.getenv("IMAP_HOST", "imap.gmail.com")

AUDIT_DB_PATH = os.path.join(DATA_DIR, "audit_log.sqlite3")
