import os
import requests
from config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL, ANTHROPIC_URL

# لو المتغير ده True، مش هنكلم Anthropic API خالص - هنستخدم رد وهمي.
# مفيد للتست من غير ما تحتاج مفتاح حقيقي أو تدفع أي حاجة.
MOCK_MODE = os.getenv("MOCK_CLAUDE", "false").lower() == "true"


def _mock_draft(employee_name: str, language: str, task: dict) -> dict:
    """رد وهمي ثابت - بيحاكي شكل رد Claude الحقيقي بالظبط."""
    if language == "ar":
        subject = f"[MOCK] {task['title']}"
        body = (
            f"عزيزي/عزيزتي {employee_name}،\n\n"
            f"{task['announcement']}\n\n"
            f"{task['request']}\n\n"
            f"الديدلاين: {task['deadline']}\n"
            f"الرابط: {task.get('action_link', '')}\n\n"
            f"مع تحياتي،\n{task['sender_name']} - {task['sender_role']}\n\n"
            f"[هذه رسالة تجريبية - MOCK_CLAUDE=true]"
        )
    else:
        subject = f"[MOCK] {task['title']}"
        body = (
            f"Dear {employee_name},\n\n"
            f"{task['announcement']}\n\n"
            f"{task['request']}\n\n"
            f"Deadline: {task['deadline']}\n"
            f"Link: {task.get('action_link', '')}\n\n"
            f"Best regards,\n{task['sender_name']} - {task['sender_role']}\n\n"
            f"[This is a test message - MOCK_CLAUDE=true]"
        )
    return {"subject": subject, "body": body}


def draft_notification_email(employee_name: str, language: str, task: dict) -> dict:
    """
    بيستدعي Claude عشان يصيغ إيميل شخصي بناءً على تفاصيل التاسك.
    بيرجع dict فيه subject و body.
    لو MOCK_CLAUDE=true في .env، بيرجع رد وهمي من غير ما يكلم الـ API خالص.
    """
    if MOCK_MODE:
        return _mock_draft(employee_name, language, task)

    lang_instruction = (
        "اكتب الإيميل بالعربية الفصحى البسيطة، بأسلوب رسمي ومحترم."
        if language == "ar"
        else "Write the email in clear, professional English."
    )

    system_prompt = f"""أنت مساعد HR بتساعد في صياغة إيميلات رسمية للموظفين.
{lang_instruction}
لازم يكون فيه: تحية باسم الموظف، شرح الموضوع، الطلب المطلوب بوضوح، الديدلاين
بشكل بارز، ورابط الإجراء لو موجود. اختم باسم المرسل ومنصبه.
رجّع الرد بصيغة JSON فقط بدون أي نص إضافي، بالشكل ده:
{{"subject": "...", "body": "..."}}"""

    user_prompt = f"""اسم الموظف: {employee_name}
عنوان الموضوع: {task['title']}
الإعلان: {task['announcement']}
المطلوب من الموظف: {task['request']}
الديدلاين: {task['deadline']}
رابط الإجراء: {task.get('action_link', '')}
اسم المرسل: {task['sender_name']} - {task['sender_role']}"""

    response = requests.post(
        ANTHROPIC_URL,
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": ANTHROPIC_MODEL,
            "max_tokens": 1000,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        },
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()

    text = "".join(
        block.get("text", "") for block in data.get("content", []) if block.get("type") == "text"
    )

    import json
    cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(cleaned)


# ============ تفسير الأوامر الطبيعية (Command Interpreter) ============

def _mock_interpret(command_text: str, employees: list, language: str) -> dict:
    """رد وهمي للتست - بيستهدف أول موظفين اتنين، وبيختار channel=email بشكل ثابت."""
    targets = [e["email"] for e in employees[:2]]
    return {
        "needs_clarification": False,
        "clarification_question": None,
        "target_emails": targets,
        "channel": "email",
        "title": "[MOCK] Task from command",
        "announcement": f"[MOCK] بناءً على طلبك: {command_text}",
        "request": "[MOCK] من فضلك اتخذ الإجراء المطلوب",
        "deadline": "خلال 3 أيام",
        "deadline_iso": None,
    }


def interpret_command(command_text: str, employees: list, language: str,
                       sender_name: str = "منى حسن", sender_role: str = "HR Manager") -> dict:
    """
    بياخد أمر بلغة طبيعية من HR Manager + قائمة الموظفين الكاملة (بتفاصيلهم)،
    وبيرجع خطة منظمة (JSON): مين المستهدف، القناة (إيميل/مكالمة/الاتنين)،
    ومحتوى المهمة. لو الطلب غامض، بيرجع سؤال توضيحي بدل ما يخمن.
    """
    if MOCK_MODE:
        return _mock_interpret(command_text, employees, language)

    employees_json = [
        {"name": e["name"], "email": e["email"], "department": e.get("department", ""), "language": e.get("language", "en")}
        for e in employees
    ]

    system_prompt = f"""إنت مساعد HR بتحول أوامر HR Manager المكتوبة بلغة طبيعية لخطة عمل منظمة.

عندك قائمة كل الموظفين بتفاصيلهم (الاسم، الإيميل، القسم، اللغة). المدير هيكتب طلب زي
"كلم فريق المبيعات وذكرهم بتقرير الشهر" أو "ابعت لأحمد إيميل بخصوص كذا".

مهمتك:
1. تحدد مين من الموظفين المقصودين بالضبط (بناءً على القسم أو الاسم أو "الكل")
2. تحدد القناة المطلوبة: "email" أو "call" أو "both" - لو المدير مذكرش، افتراضيًا "email"
3. تصيغ تفاصيل المهمة: عنوان، إعلان (الموضوع)، طلب (المطلوب من الموظف)، وديدلاين

لو الطلب غامض (مثلاً قال "الفريق" ومفيش قسم بالاسم ده، أو "أحمد" وفيه أكتر من أحمد)،
لازم تسأل بدل ما تخمن - ارجع needs_clarification: true مع سؤال واضح ومحدد.

قائمة الموظفين المتاحة:
{employees_json}

رجّع الرد بصيغة JSON فقط بدون أي نص إضافي، بالشكل ده بالظبط:
{{
  "needs_clarification": false,
  "clarification_question": null,
  "target_emails": ["email1@example.com"],
  "channel": "email",
  "title": "...",
  "announcement": "...",
  "request": "...",
  "deadline": "...",
  "deadline_iso": null
}}

اكتب محتوى title/announcement/request/deadline بنفس لغة أمر المدير الأصلي."""

    response = requests.post(
        ANTHROPIC_URL,
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": ANTHROPIC_MODEL,
            "max_tokens": 1200,
            "system": system_prompt,
            "messages": [{"role": "user", "content": command_text}],
        },
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    text = "".join(
        block.get("text", "") for block in data.get("content", []) if block.get("type") == "text"
    )
    import json
    cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    result = json.loads(cleaned)
    result.setdefault("sender_name", sender_name)
    result.setdefault("sender_role", sender_role)
    return result


# ============ تصنيف رد الموظف + الرد التلقائي على الروتيني ============

def _mock_classify(employee_reply: str, employee_name: str, task: dict, language: str) -> dict:
    text = employee_reply.lower()
    if "اتفضل" in employee_reply or "attached" in text or "مرفق" in employee_reply:
        return {
            "classification": "submitted", "can_auto_reply": False, "auto_reply_text": None,
            "needs_manager_input": False, "manager_summary": None,
            "reasoning": "[MOCK] الرد فيه إشارة واضحة إن التقرير اتبعت",
        }
    if "فين" in employee_reply or "ايميل تاني" in employee_reply or "إيميل تاني" in employee_reply or "where" in text:
        return {
            "classification": "question", "can_auto_reply": True,
            "auto_reply_text": f"[MOCK] تمام يا {employee_name}، ابعته على نفس الإيميل اللي في الطلب الأصلي: {task.get('submission_email', '')}",
            "needs_manager_input": False, "manager_summary": None,
            "reasoning": "[MOCK] سؤال روتيني إجابته في التاسك نفسها",
        }
    if "3 extra days" in employee_reply or "أيام" in employee_reply:
        return {
            "classification": "delay_request", "can_auto_reply": False, "auto_reply_text": None,
            "needs_manager_input": True,
            "manager_summary": f"[MOCK] {employee_name} طلب تأجيل - محتاج قرارك",
            "reasoning": "[MOCK] طلب تأجيل أكتر من يوم واحد - محتاج موافقة المدير حسب السياسة",
        }
    return {
        "classification": "other", "can_auto_reply": False, "auto_reply_text": None,
        "needs_manager_input": True, "manager_summary": f"[MOCK] رد غير متوقع من {employee_name}",
        "reasoning": "[MOCK] الرد مش واضح",
    }


def classify_employee_reply(employee_reply: str, employee_name: str, task: dict,
                             knowledge_base: str, language: str) -> dict:
    """
    بياخد رد الموظف الفعلي + تفاصيل التاسك + سياسات الشركة (knowledge base)،
    وبيصنّف الرد ويقرر: نقدر نرد عليه لوحدنا، ولا لازم يتصعّد لـ HR Manager.

    القاعدة الأساسية: أي حاجة مش تسليم واضح أو سؤال روتيني إجابته موجودة
    في التاسك أو الـ knowledge base، لازم تتصعّد - مش نخمّن.
    """
    if MOCK_MODE:
        return _mock_classify(employee_reply, employee_name, task, language)

    system_prompt = f"""إنت مساعد HR بتصنّف ردود الموظفين على طلبات HR وتقرر هل تقدر ترد بنفسك ولا لأ.

تفاصيل الطلب الأصلي:
- العنوان: {task.get('title', '')}
- المطلوب: {task.get('request', '')}
- الديدلاين: {task.get('deadline', '')}

سياسات الشركة المتاحة (استخدمها للإجابة على الأسئلة الروتينية بس):
{knowledge_base}

صنّف رد الموظف لواحدة من الفئات دي:
- "submitted": سلّم المطلوب فعليًا (مرفق، تأكيد إرسال، إلخ)
- "question": سؤال عن تفاصيل التنفيذ
- "delay_request": طلب تأجيل أو استثناء
- "other": أي حاجة تانية غير متوقعة

القاعدة الحاسمة: لو تقدر ترد على السؤال بثقة **من نفس تفاصيل الطلب أو سياسات الشركة المذكورة فوق فقط**،
سيبك can_auto_reply=true واكتب الرد في auto_reply_text بنفس لغة رد الموظف.
لو مش متأكد، أو السياسة نفسها بتقول "يرجع لـ HR Manager"، أو الموضوع حساس أو استثنائي،
خلي can_auto_reply=false و needs_manager_input=true، واكتب ملخص قصير في manager_summary.

لما الشك، صعّد. متخمنش سياسة مش مذكورة صراحة.

رجّع JSON فقط بدون أي نص إضافي:
{{
  "classification": "submitted",
  "can_auto_reply": false,
  "auto_reply_text": null,
  "needs_manager_input": false,
  "manager_summary": null,
  "reasoning": "شرح قصير لقرارك"
}}"""

    user_message = f"اسم الموظف: {employee_name}\n\nرد الموظف:\n{employee_reply}"

    response = requests.post(
        ANTHROPIC_URL,
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": ANTHROPIC_MODEL,
            "max_tokens": 800,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_message}],
        },
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    text = "".join(
        block.get("text", "") for block in data.get("content", []) if block.get("type") == "text"
    )
    import json
    cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(cleaned)
