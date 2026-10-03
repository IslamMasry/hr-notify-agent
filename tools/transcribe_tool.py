"""
Transcribe Tool — بيحوّل الصوت المسجل من المتصفح لنص عبر OpenAI.
البديل ده مستقل تمامًا عن Web Speech API بتاعة جوجل - المتصفح بيبعت
الصوت لسيرفرنا احنا بس، والسيرفر هو اللي بيكلم OpenAI. يعني لو مشكلة
الشبكة كانت بسبب VPN أو فايروول بيمنع الوصول لجوجل تحديدًا، الحل ده
بيتجاوزها تمامًا.
"""

import os
import requests

MOCK_MODE = os.getenv("MOCK_TRANSCRIBE", "false").lower() == "true"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
TRANSCRIBE_MODEL = os.getenv("TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")
OPENAI_URL = "https://api.openai.com/v1/audio/transcriptions"


def transcribe_audio(file_bytes: bytes, filename: str = "audio.webm") -> str:
    """بياخد بايتات الصوت المسجل ويرجع النص المستخرج منه."""
    if MOCK_MODE:
        return "[MOCK] Call the sales team about the March report deadline"

    response = requests.post(
        OPENAI_URL,
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
        files={"file": (filename, file_bytes, "audio/webm")},
        data={"model": TRANSCRIBE_MODEL},
        timeout=30,
    )
    response.raise_for_status()
    return response.json().get("text", "").strip()
