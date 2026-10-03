import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM_NAME

MOCK_MODE = os.getenv("MOCK_EMAIL", "false").lower() == "true"


def send_email(to_address: str, subject: str, body: str) -> None:
    if MOCK_MODE:
        return  # مبيبعتش حاجة فعليًا - مفيد للتست من غير حساب SMTP حقيقي

    msg = MIMEMultipart()
    msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_USER}>"
    msg["To"] = to_address
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_USER, [to_address], msg.as_string())
