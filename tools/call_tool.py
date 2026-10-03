"""
Call Tool — مكالمات صوتية تفاعلية عبر Vapi.ai
Vapi بيدير الـ STT/TTS/turn-taking، وإحنا بس بنحدد الـ system prompt
(اللي بيتصاغ من نفس تفاصيل التاسك) ونختار Claude كـ LLM للمحادثة.

ملاحظات أداء مهمة (قراءة قبل أي تعديل):
- الـ latency في مكالمات Vapi بييجي من 3 مصادر رئيسية: وقت رد الـ LLM (TTFT)،
  إعدادات الـ turn-taking (متى النظام يحس إن الموظف خلص كلامه)، وسرعة الـ TTS.
- اخترنا موديل Claude سريع افتراضيًا (قابل للتغيير من .env) لتقليل TTFT.
- ضبطنا startSpeakingPlan/stopSpeakingPlan يدويًا لأن الإعدادات الافتراضية
  عند Vapi بتضيف تأخير حقيقي (ممكن يوصل لثانية ونص) قبل ما النظام يرد.
"""

import os
import requests
from tools.knowledge_base import get_knowledge_base

VAPI_API_KEY = os.getenv("VAPI_API_KEY", "")
VAPI_PHONE_NUMBER_ID = os.getenv("VAPI_PHONE_NUMBER_ID", "")
VAPI_BASE_URL = "https://api.vapi.ai"

# الموديل المستخدم في المكالمات الحية - سرعة الرد هنا أهم من العمق، فالافتراضي
# موديل سريع. غيّره من .env لو عايز موديل تاني (لازم يكون مدعوم عند Vapi كـ "anthropic").
CALL_MODEL = os.getenv("VAPI_CALL_MODEL", "claude-haiku-4-5-20251001")

# موديل الـ transcriber - nova-3 عند Deepgram بيدعم لغات أكتر من nova-2 (زي "multi"
# للتبديل التلقائي بين لغتين)، لكن للعربي تحديدًا لسه محتاج "whisper" تحديدًا
# (nova-2 و nova-3 مبيدعموش العربي في وقت كتابة الكود ده - راجع التوثيق لو الوضع اتغير).
TRANSCRIBER_MODEL_EN = os.getenv("VAPI_TRANSCRIBER_MODEL_EN", "nova-3")
TRANSCRIBER_MODEL_AR = os.getenv("VAPI_TRANSCRIBER_MODEL_AR", "nova-3")

# ملحوظة مهمة (سبتمبر 2026): Deepgram أضافوا دعم عربي حقيقي لـ Nova-3 في أواخر
# يناير 2026. جرّبنا الأول "multi" (وضع كشف لغتين تلقائي) ظنًا إن "ar" المباشرة
# مش مدعومة كويس، لكن طلع إن مشكلة القطع كانت سببها endCallPhrases مش اللغة نفسها.
# "multi" بيضحي بدقة التعرف على العربي عشان يقدر يكتشف لغتين مختلفتين، فالافتراضي
# دلوقتي "ar" (تعرف مخصص للعربي بس، دقة أعلى). جرب "ar-EG" لو عايز اللهجة المصرية
# تحديدًا. راجع docs.vapi.ai/providers/transcriber/deepgram لأحدث حالة.
TRANSCRIBER_LANGUAGE_AR = os.getenv("VAPI_TRANSCRIBER_LANGUAGE_AR", "ar")

MOCK_MODE = os.getenv("MOCK_CALLS", "false").lower() == "true"


def _build_system_prompt(employee_name: str, language: str, task: dict, is_followup: bool = False) -> str:
    """
    برومبت عام لأي مهمة HR (مش مقصور على "طلب تقرير") - صالح لتذكيرات، طلبات
    معلومات، تأكيد مواعيد، أو أي تواصل HR روتيني. لازم يفضل بجمل قصيرة وواضحة
    (بيتقرا بصوت، مش نص)، ولازم يكون فيه تعليمات صريحة لإنهاء المكالمة - ده
    أكتر جزء مهم عشان المكالمة متفضلش تلف في حلقة من غير سبب.
    """
    knowledge_base = get_knowledge_base()

    followup_note = {
        "ar": (
            f"\n\nملحوظة: دي مكالمة متابعة - إحنا كلمنا {employee_name} قبل كده عن نفس "
            f"الموضوع ولسه ملبعتش رد نهائي. اتكلم بنبرة ودودة بس أكتر إلحاحًا شوية."
            if is_followup else ""
        ),
        "en": (
            f"\n\nNote: this is a follow-up call - {employee_name} was already contacted "
            f"about this and hasn't given a final response yet. Be friendly but a bit more urgent."
            if is_followup else ""
        ),
    }[language if language in ("ar", "en") else "en"]

    if language == "ar":
        return f"""إنت مساعد HR بتكلم الموظف {employee_name} بالتليفون نيابة عن {task['sender_name']} ({task['sender_role']}).

# الأسلوب
- اتكلم بالعربية العامية البسيطة، جمل قصيرة (سطر أو سطرين كحد أقصى في كل رد).
- ماتكررش نفس المعلومة أكتر من مرة. لو الموظف فهم واستوعب، انتقل لإنهاء المكالمة على طول.
- في بداية المكالمة، قول بوضوح إنك مساعد آلي (AI) بتتصل نيابة عن {task['sender_name']}، مش إنسان حقيقي.

# هدف المكالمة
- تبلغ الموظف بـ: {task['announcement']}
- تطلب منه: {task['request']}
- توضحله الديدلاين: {task['deadline']}{followup_note}

# التعامل مع الأسئلة
سياسات الشركة المتاحة عندك (استخدمها بس، ماتخترعش حاجة مش مذكورة):
{knowledge_base}

لو سؤال روتيني إجابته موجودة فوق، رد عليه بثقة وباختصار **وكمّل المكالمة** - سؤال مش سبب لإنهاء
المكالمة أبدًا. لو حاجة مش موجودة، أو طلب استثناء، أو الموضوع حساس، قوله إنك هتوصّل السؤال لـ
{task['sender_name']} وترجعله بالرد، وبعدين اقفل زي ما هو موضح تحت.

# إزاي تقرر كل مرة الموظف يتكلم - بالترتيب ده بالظبط
1. **ده سؤال؟** (فيه "ليه"، "إزاي"، "امتى"، "مين"، "إيه"، أو نبرة استفسار) → جاوب من قسم "التعامل
   مع الأسئلة" فوق، وكمّل المكالمة. **متعتبروش تأكيد أو رفض حتى لو جزء منه شكله موافقة.**
2. **مسمعتهوش كويس أو الكلام مش واضح؟** → اسأله يعيد أو وضّح السؤال بصيغة أبسط. **متفترضش
   إنه وافق أو إنه عايز يقفل.**
3. **رد واضح (تأكيد/رفض/تأجيل/إنهاء)؟** → طبّق قاعدة "إنهاء المكالمة" تحت.

# إنهاء المكالمة - أهم قاعدة
**متقفلش المكالمة أبدًا قبل ما تسمع رد حقيقي من الموظف على الأقل مرة واحدة**، وماتقفلش وهو لسه
بيسأل سؤال أو انت لسه مبقتش متأكد من رده (شوف الترتيب فوق).

بعد ما تتأكد إن رده واضح (مش سؤال، ومش غامض)، أي واحدة من دول بتعتبر "المكالمة خلصت":
- الموظف أكّد إنه هينفذ المطلوب (حتى لو رد بسيط زي "تمام" أو "هابعته" أو "ماشي")
- الموظف رفض أو قال إنه مش هيقدر
- الموظف طلب تأجيل أو استثناء (سجّل طلبه، وقوله هيوصل لـ {task['sender_name']}، وخلاص اقفل)
- الموظف قال أي حاجة بتدل إنه عايز يقفل المكالمة ("خلاص"، "سلام"، "باي")

لما توصل لأي حالة من دول: قول جملة ختامية قصيرة جدًا، وبعدها **استخدم أداة إنهاء المكالمة
(end call function) فورًا** - متسبش المكالمة مفتوحة بعد الجملة الختامية.
**ممنوع تكرر تفاصيل الطلب تاني، وممنوع تعمل ملخص منطوق للمكالمة في الآخر** - أي حاجة
محتاجة توثيق هتترصد تلقائيًا من نص المكالمة نفسه، مش لازم تقولها بصوتك.

خلي المكالمة قصيرة ومباشرة من البداية للنهاية."""
    else:
        return f"""You are an HR assistant calling {employee_name} on behalf of {task['sender_name']} ({task['sender_role']}).

# Style
- Simple, short sentences - one or two lines per turn, maximum.
- Never repeat the same information twice. Once the employee understands, move to closing.
- At the start of the call, clearly state you are an AI assistant calling on behalf of
  {task['sender_name']}, not a real person.

# Purpose of the call
- Inform the employee about: {task['announcement']}
- Request: {task['request']}
- Deadline: {task['deadline']}{followup_note}

# Handling questions
Company policies available to you (use these only, don't invent anything not mentioned here):
{knowledge_base}

If a routine question is covered above, answer confidently and briefly **and continue the
call** - a question is never a reason to end the call. If something isn't covered, an
exception is requested, or the topic feels sensitive, say you'll pass it to
{task['sender_name']} and follow up, then close per the rule below.

# How to decide each time the employee speaks - in this exact order
1. **Is this a question?** (contains "why", "how", "when", "who", "what", or a questioning
   tone) → answer it from "Handling questions" above, and continue the call. **Do not treat
   it as a confirmation or decline even if part of it sounds affirmative.**
2. **Didn't hear it clearly, or it's ambiguous?** → ask them to repeat or rephrase. **Do not
   assume they confirmed or want to end the call.**
3. **Clear response (confirm/decline/delay/end signal)?** → apply the "Ending the call" rule below.

# Ending the call - the most important rule
**Never end the call before hearing at least one real response from the employee**, and never
end while they're still asking a question or while you're unsure what they said (see the order above).

Once you're sure their response is clear (not a question, not ambiguous), any of these means
the call is DONE:
- The employee confirms they'll do it (even a simple "okay" or "will do" counts)
- The employee declines or says they can't
- The employee asks for a delay or exception (note it, say it'll be passed to {task['sender_name']}, then close)
- The employee signals they want to end the call ("bye", "that's it", "thanks")

Once you reach any of these: say one short closing line, then **use the end-call function
immediately** - don't leave the call open after your closing line. **Do not repeat the request
details again, and do not give a spoken summary of the call at the end** - anything that needs
to be recorded will be extracted from the transcript automatically, you don't need to say it out loud.

Keep the whole call short and direct, start to finish."""


def _mock_call(employee_name, phone, task) -> dict:
    return {
        "id": "mock-call-id",
        "status": "queued",
        "note": f"[MOCK] كان هيتصل بـ {employee_name} على {phone} - المكالمة متبتنفذش فعليًا",
    }


def place_call(employee_name: str, phone: str, language: str, task: dict, is_followup: bool = False) -> dict:
    """
    يبدأ مكالمة صوتية تفاعلية فعلية عبر Vapi.
    بيرجع dict فيه call id وحالته الأولية (المكالمة بتتم بشكل غير متزامن).
    """
    if MOCK_MODE:
        return _mock_call(employee_name, phone, task)

    system_prompt = _build_system_prompt(employee_name, language, task, is_followup)
    if is_followup:
        first_message = (
            f"أهلاً {employee_name}، معاك تاني مساعد آلي نيابة عن {task['sender_name']}، بخصوص نفس الموضوع."
            if language == "ar"
            else f"Hi {employee_name}, this is the AI assistant calling again on behalf of {task['sender_name']}, about the same matter."
        )
    else:
        first_message = (
            f"أهلاً {employee_name}، معاك مساعد آلي بتكلمك نيابة عن {task['sender_name']}."
            if language == "ar"
            else f"Hi {employee_name}, this is an AI assistant calling on behalf of {task['sender_name']}."
        )

    # ملحوظة: كنا بنستخدم endCallPhrases (مطابقة نصية) لإنهاء المكالمة، لكن ده
    # سبب مشاكل حقيقية - المطابقة عند Vapi مش بسيطة زي substring متوقع، وأي عبارة
    # حتى لو محددة ممكن تتطابق مع كلام الموديل بشكل غير متوقع وتقفل المكالمة بدري
    # (endedReason: "assistant-said-end-call-phrase"). شلناها خالص واعتمدنا بس على
    # endCallFunctionEnabled - ده function call حقيقي بيقرره الموديل بوعي بناءً على
    # تعليمات البرومبت، مش مطابقة نص هشة.

    payload = {
        "phoneNumberId": VAPI_PHONE_NUMBER_ID,
        "customer": {"number": phone},
        "assistant": {
            "firstMessage": first_message,
            "firstMessageMode": "assistant-speaks-first",
            "model": {
                "provider": "anthropic",
                "model": CALL_MODEL,
                "messages": [{"role": "system", "content": system_prompt}],
                "temperature": 0.2,  # التوثيق بيوصي بقيمة منخفضة/صفر عشان الـ caching يشتغل ويقلل الـ latency
                "maxTokens": 200,  # ردود قصيرة = زمن توليد أقل = إحساس أسرع
            },
            "voice": {"provider": "vapi", "voiceId": "Elliot"},
            "transcriber": (
                {"provider": "deepgram", "model": TRANSCRIBER_MODEL_AR, "language": TRANSCRIBER_LANGUAGE_AR}
                if language == "ar"
                else {"provider": "deepgram", "model": TRANSCRIBER_MODEL_EN, "language": "en"}
            ),

            # ---- ضبط زمن الاستجابة (turn-taking) ----
            # الإعداد الافتراضي عند Vapi بينتظر فترة أطول قبل ما يعتبر إن الموظف خلص كلامه.
            # هنا بنقصر الفترة دي عشان الرد يحس إنه فوري، مع الحفاظ على مساحة كافية
            # لموظف بيتكلم عادي (مش قاطعينه في نص الجملة).
            "startSpeakingPlan": {
                "waitSeconds": 0.6,
                "smartEndpointingPlan": {"provider": "vapi"},
            },
            "stopSpeakingPlan": {
                "numWords": 2,
                "voiceSeconds": 0.2,
                "backoffSeconds": 0.8,
            },

            # ---- إنهاء المكالمة تلقائيًا ----
            # ده الحل الفعلي لمشكلة "المكالمة مبتنهيش" - بندي الـ assistant قدرة تقفل
            # المكالمة فعليًا (function call حقيقي)، مش بس تعليمة في البرومبت.
            "endCallFunctionEnabled": True,
            "silenceTimeoutSeconds": 20,   # لو سكت تمامًا 20 ثانية، اقفل المكالمة
            "maxDurationSeconds": 240,     # حد أقصى 4 دقايق لأي مكالمة - شبكة أمان

            # ---- تحليل المكالمة المدمج عند Vapi ----
            # بيشتغل تلقائيًا بعد ما المكالمة تخلص (بموديل Claude من عندهم)، وبيرجع
            # ملخص جاهز في call.analysis.summary - مفيد كطبقة إضافية موثوقة، لكن
            # التصنيف الأساسي (تسليم/سؤال/تأجيل) لسه بيعتمد على classify_employee_reply
            # بتاعنا احنا عشان يستخدم نفس الـ Knowledge Base ونفس منطق باقي المشروع.
            "analysisPlan": {
                "summaryPlan": {
                    "enabled": True,
                    "timeoutSeconds": 10,
                },
            },
        },
    }

    response = requests.post(
        f"{VAPI_BASE_URL}/call",
        headers={"Authorization": f"Bearer {VAPI_API_KEY}", "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    if not response.ok:
        # نظهر رسالة Vapi التفصيلية بدل "400 Bad Request" العامة اللي مش بتقول السبب
        raise Exception(f"Vapi error {response.status_code}: {response.text}")
    data = response.json()
    return {"id": data.get("id"), "status": data.get("status", "queued")}


def get_call_status(call_id: str) -> dict:
    """يجيب حالة المكالمة والـ transcript لو خلصت (للـ polling بدل webhook)."""
    if MOCK_MODE or call_id == "mock-call-id":
        return {
            "status": "ended", "transcript": "[MOCK] مفيش مكالمة حقيقية اتعملت",
            "endedReason": "mock", "outcome": "completed_normally",
            "outcome_label_ar": "خلصت طبيعي (تجريبي)", "vapi_summary": "[MOCK] ملخص تجريبي للمكالمة",
        }

    response = requests.get(
        f"{VAPI_BASE_URL}/call/{call_id}",
        headers={"Authorization": f"Bearer {VAPI_API_KEY}"},
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()
    ended_reason = data.get("endedReason", "")
    outcome, outcome_label_ar = classify_ended_reason(ended_reason)
    return {
        "status": data.get("status"),
        "transcript": data.get("transcript", ""),
        "endedReason": ended_reason,
        "outcome": outcome,
        "outcome_label_ar": outcome_label_ar,
        "vapi_summary": (data.get("analysis") or {}).get("summary", ""),
    }


# ============ تصنيف نهاية المكالمة ============
# Vapi بيرجع عشرات الأكواد التقنية (endedReason) - هنا بنحولها لحالات مفهومة
# لـ HR Manager بدل ما يقرا كود تقني زي "pipeline-error-vapifault-transport-never-connected"

_OUTCOME_MAP = [
    # (كلمة مفتاحية في الكود, الفئة, التسمية بالعربي)
    ("customer-ended-call", "completed_normally", "الموظف أنهى المكالمة (طبيعي)"),
    ("assistant-ended-call", "completed_normally", "المكالمة خلصت طبيعي (الـ agent قفلها)"),
    ("assistant-said-end-call-phrase", "completed_normally", "المكالمة خلصت طبيعي (عبارة إنهاء)"),
    ("voicemail", "no_answer", "دخلت على الرسائل الصوتية - محدش رد"),
    ("customer-did-not-answer", "no_answer", "الموظف لم يرد"),
    ("no-answer", "no_answer", "الموظف لم يرد"),
    ("silence-timed-out", "no_response_on_line", "الخط اتفتح بس محدش اتكلم (صمت)"),
    ("phone-call-provider-closed-websocket", "line_dropped", "الخط انقطع فجأة"),
    ("call.start.error-get-transport", "technical_error", "خطأ تقني في إعداد الاتصال (راجع صلاحية الاتصال الدولي في Twilio)"),
    ("call.start.error-vapi-number-international", "technical_error", "الرقم المستخدم مش مسموح له بالاتصال الدولي"),
    ("call.start.error", "failed_before_start", "فشلت المكالمة قبل ما تبدأ"),
    ("pipeline-error-vapifault-transport", "line_dropped", "مشكلة في الاتصال - الخط انقطع"),
    ("pipeline-no-available-llm", "technical_error", "خطأ تقني (مشكلة في الـ AI)"),
    ("pipeline-error", "technical_error", "خطأ تقني أثناء المكالمة"),
    ("*-voice-failed", "audio_unclear", "مشكلة في جودة الصوت (TTS)"),
    ("voice-failed", "audio_unclear", "مشكلة في جودة الصوت (TTS)"),
    ("transcriber", "audio_unclear", "المكالمة مسمعتش الموظف كويس (مشكلة تعرّف على الصوت)"),
    ("vapifault", "technical_error", "خطأ تقني من نظام المكالمات"),
    ("customer-busy", "no_answer", "الخط مشغول"),
    ("exceeded-max-duration", "completed_normally", "المكالمة خلصت (وصلت للحد الأقصى للمدة)"),
    ("silence-timeout", "no_response_on_line", "الموظف سكت لفترة طويلة"),
]


def classify_ended_reason(ended_reason: str) -> tuple[str, str]:
    """بيحول كود endedReason التقني لفئة مفهومة + تسمية بالعربي."""
    if not ended_reason:
        return "unknown", "غير معروف - محتاج تراجع الـ transcript"

    lower = ended_reason.lower()
    for keyword, outcome, label in _OUTCOME_MAP:
        if keyword.strip("*-").lower() in lower:
            return outcome, label

    return "unknown", f"سبب غير مصنّف ({ended_reason}) - راجع التفاصيل"
