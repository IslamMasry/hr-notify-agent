"""
Inbox Checker — بيدور في صندوق الوارد (عبر IMAP) على إيميل جاي من موظف معين
وفيه كلمة مفتاحية في العنوان، بعد تاريخ معين. ده بديل بسيط لتكامل حقيقي مع
نظام تذاكر أو workflow engine، مناسب للديمو والتست.
"""

import os
import imaplib
import email
from email.header import decode_header
from datetime import datetime

MOCK_MODE = os.getenv("MOCK_INBOX", "false").lower() == "true"

IMAP_HOST = os.getenv("IMAP_HOST", "imap.gmail.com")
IMAP_USER = os.getenv("SMTP_USER", "")       # بنستخدم نفس حساب الـ SMTP للتبسيط
IMAP_PASSWORD = os.getenv("SMTP_PASSWORD", "")  # لازم App Password زي ما شرحنا


def _decode(value: str) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    return "".join(
        p.decode(enc or "utf-8", errors="ignore") if isinstance(p, bytes) else p
        for p, enc in parts
    )


def _mock_check(employee_email: str, keyword: str) -> dict:
    # عشان الديمو يبان متنوع: أي إيميل فيه "sara" هيتحسب إنه بعت، الباقي لسه
    submitted = "sara" in employee_email.lower()
    return {
        "submitted": submitted,
        "note": f"[MOCK] {'لقينا إيميل مطابق' if submitted else 'مفيش إيميل مطابق لسه'}",
    }


def check_submission(employee_email: str, keyword: str, since_date: str) -> dict:
    """
    بيدور في صندوق الوارد على إيميل من employee_email، فيه keyword في العنوان،
    بعد since_date (بصيغة YYYY-MM-DD). بيرجع {"submitted": bool, "note": str}.
    """
    if MOCK_MODE:
        return _mock_check(employee_email, keyword)

    try:
        since_imap = datetime.strptime(since_date, "%Y-%m-%d").strftime("%d-%b-%Y")

        conn = imaplib.IMAP4_SSL(IMAP_HOST)
        conn.login(IMAP_USER, IMAP_PASSWORD)
        conn.select("INBOX")

        # IMAP SEARCH: من هذا المرسل، بعد التاريخ ده
        status, data = conn.search(None, f'(FROM "{employee_email}" SINCE {since_imap})')
        if status != "OK":
            conn.logout()
            return {"submitted": False, "note": "فشل البحث في صندوق الوارد"}

        message_ids = data[0].split()
        for msg_id in reversed(message_ids):  # الأحدث الأول
            _, msg_data = conn.fetch(msg_id, "(RFC822)")
            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)
            subject = _decode(msg.get("Subject", ""))
            if keyword in subject:
                conn.logout()
                return {"submitted": True, "note": f"لقينا إيميل بعنوان: {subject}"}

        conn.logout()
        return {"submitted": False, "note": "مفيش إيميل مطابق لسه"}

    except Exception as e:
        return {"submitted": False, "note": f"خطأ في فحص الإيميل: {e}"}


def _get_body_text(msg) -> str:
    """يستخرج النص العادي من رسالة إيميل (بيتجاهل الأجزاء الـ HTML/المرفقات)."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and not part.get("Content-Disposition"):
                try:
                    return part.get_payload(decode=True).decode(errors="ignore")
                except Exception:
                    continue
        return ""
    try:
        return msg.get_payload(decode=True).decode(errors="ignore")
    except Exception:
        return ""


def _mock_latest_reply(employee_email: str) -> dict | None:
    # عشان الديمو يبان متنوع: كل موظف بيرجع سلوك مختلف
    if "sara" in employee_email.lower():
        return {"subject": "تقرير مارس", "body": "اتفضل التقرير في المرفقات.", "date": "2026-08-27"}
    if "ahmed" in employee_email.lower():
        return {"subject": "استفسار", "body": "أبعت التقرير على نفس الإيميل ده ولا فيه إيميل تاني؟", "date": "2026-08-28"}
    if "john" in employee_email.lower():
        return {"subject": "delay request", "body": "Can I get 3 extra days? I'm traveling.", "date": "2026-08-29"}
    return None


def get_latest_reply(employee_email: str, since_date: str) -> dict | None:
    """
    بيرجع آخر رد فعلي من الموظف (subject + body + date) بعد since_date، أو None لو مفيش رد.
    ده أوسع من check_submission - بيرجع المحتوى كامل عشان Claude يقدر يصنّفه.
    """
    if MOCK_MODE:
        return _mock_latest_reply(employee_email)

    try:
        since_imap = datetime.strptime(since_date, "%Y-%m-%d").strftime("%d-%b-%Y")
        conn = imaplib.IMAP4_SSL(IMAP_HOST)
        conn.login(IMAP_USER, IMAP_PASSWORD)
        conn.select("INBOX")

        status, data = conn.search(None, f'(FROM "{employee_email}" SINCE {since_imap})')
        if status != "OK" or not data[0]:
            conn.logout()
            return None

        message_ids = data[0].split()
        latest_id = message_ids[-1]  # آخر رسالة (الأحدث)
        _, msg_data = conn.fetch(latest_id, "(RFC822)")
        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)
        conn.logout()

        return {
            "subject": _decode(msg.get("Subject", "")),
            "body": _get_body_text(msg).strip(),
            "date": msg.get("Date", ""),
        }
    except Exception as e:
        return {"subject": "", "body": "", "date": "", "error": str(e)}
