"""
Orchestrator — بياخد أمر HR Manager بلغة طبيعية (نص أو منسوخ من الصوت) ويحوله
لخطة تنفيذية محددة: مين المستهدف، بأنهي قناة (إيميل/مكالمة/الاتنين)، وإيه المحتوى.

مهم: الـ orchestrator ده بيقترح بس - التنفيذ الفعلي بيحصل في endpoint منفصل
بعد موافقة HR Manager، نفس مبدأ HITL في باقي المشروع.
"""

import os
import json
import requests

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = "claude-sonnet-5-5"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
MOCK_MODE = os.getenv("MOCK_CLAUDE", "false").lower() == "true"

TOOLS = [
    {
        "name": "list_employees",
        "description": (
            "Get the full employee directory (name, email, department, language) "
            "to resolve who a request refers to (e.g. 'the sales team')."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "propose_plan",
        "description": (
            "Propose a concrete action plan once you have resolved specific employee "
            "emails from the directory. This does not execute anything - it's a proposal "
            "shown to the HR manager for approval."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "channel": {"type": "string", "enum": ["email", "call", "both"]},
                "recipient_emails": {"type": "array", "items": {"type": "string"}},
                "title": {"type": "string", "description": "Short title in Arabic"},
                "title_en": {"type": "string", "description": "Short title in English"},
                "announcement": {"type": "string", "description": "The context/announcement in Arabic"},
                "announcement_en": {"type": "string"},
                "request": {"type": "string", "description": "What the employee needs to do, in Arabic"},
                "request_en": {"type": "string"},
                "deadline": {"type": "string", "description": "Deadline phrase in Arabic, or 'N/A'"},
                "deadline_en": {"type": "string"},
                "reasoning": {
                    "type": "string",
                    "description": "One short sentence explaining how recipients were resolved, for transparency to the HR manager.",
                },
            },
            "required": [
                "channel", "recipient_emails", "title", "title_en", "announcement",
                "announcement_en", "request", "request_en", "deadline", "deadline_en", "reasoning",
            ],
        },
    },
]

SYSTEM_PROMPT = """You are an orchestrator for an HR AI co-worker system. The HR manager will
give you a task in plain language (Arabic or English). Your job is ONLY to figure out:
1. Who exactly should be contacted (resolve team/department names to real employees via list_employees)
2. Which channel to use: email, call, or both
3. What the message content should be (in both Arabic and English)

You must call list_employees first if the request references a group, team, or department rather
than named individuals. Once you have concrete employee emails, call propose_plan with the full plan.

If the request is too ambiguous to resolve (e.g. no matching department, unclear deadline), do NOT
call propose_plan - instead respond with a short clarifying question in plain text.

Never invent employee emails - only use ones returned by list_employees."""


def _mock_orchestrate(user_message: str, employees: list[dict]) -> dict:
    """رد وهمي بسيط للتست من غير API حقيقي - بيدور على كلمات مفتاحية بسيطة."""
    lower = user_message.lower()

    # حاول تلاقي قسم مذكور في الرسالة
    matched_dept = None
    for emp in employees:
        dept = emp.get("department", "")
        if dept and dept.lower() in lower:
            matched_dept = dept
            break

    if matched_dept:
        recipients = [e["email"] for e in employees if e.get("department") == matched_dept]
        reasoning = f"[MOCK] لقيت {len(recipients)} موظف في قسم {matched_dept}"
    else:
        recipients = [e["email"] for e in employees]
        reasoning = f"[MOCK] معرفتش أحدد قسم معين، هستهدف كل الموظفين ({len(recipients)})"

    channel = "both" if ("call" in lower or "اتصل" in lower or "مكالم" in lower) and \
        ("email" in lower or "ايميل" in lower or "إيميل" in lower) else \
        "call" if ("call" in lower or "اتصل" in lower or "مكالم" in lower) else "email"

    return {
        "type": "plan",
        "channel": channel,
        "recipient_emails": recipients,
        "title": "[MOCK] مهمة جديدة", "title_en": "[MOCK] New Task",
        "announcement": f"[MOCK] بناءً على طلبك: {user_message}",
        "announcement_en": f"[MOCK] Based on your request: {user_message}",
        "request": "[MOCK] من فضلك نفذ المطلوب", "request_en": "[MOCK] Please complete the requested action",
        "deadline": "خلال 3 أيام", "deadline_en": "within 3 days",
        "reasoning": reasoning,
    }


def _call_claude(messages: list[dict]) -> dict:
    response = requests.post(
        ANTHROPIC_URL,
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": ANTHROPIC_MODEL,
            "max_tokens": 1500,
            "system": SYSTEM_PROMPT,
            "tools": TOOLS,
            "messages": messages,
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def orchestrate(user_message: str, employees: list[dict], history: list[dict] | None = None) -> dict:
    """
    بيرجع واحد من اتنين:
    - {"type": "plan", ..., "history": [...]} خطة كاملة جاهزة للعرض والموافقة
    - {"type": "clarification", "text": "...", "history": [...]} سؤال توضيحي لو الطلب غامض

    "history" هي كل الرسائل (بما فيها tool calls/results) لحد اللحظة دي - بترجع
    عشان تتحفظ وتتبعت تاني في الطلب الجاي، عشان المحادثة تكون متواصلة ومتنساش
    السياق (زي "اعمل نفس الحاجة بس لفريق تاني" بعد خطة سابقة).
    """
    if MOCK_MODE:
        result = _mock_orchestrate(user_message, employees)
        return {**result, "history": (history or []) + [
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": f"[MOCK] {result.get('reasoning', '')}"},
        ]}

    messages = list(history or [])[-30:]  # نقص الطول عشان التاريخ يفضل معقول ومايكلفش توكنز زيادة
    messages.append({"role": "user", "content": user_message})

    for _ in range(5):  # حد أقصى لعدد جولات الـ tool use عشان نتجنب أي loop لانهائي
        data = _call_claude(messages)
        content_blocks = data.get("content", [])
        messages.append({"role": "assistant", "content": content_blocks})

        tool_use_blocks = [b for b in content_blocks if b.get("type") == "tool_use"]

        if not tool_use_blocks:
            # مفيش tool call - يبقى Claude بيسأل سؤال توضيحي أو بيرد نص عادي
            text = "".join(b.get("text", "") for b in content_blocks if b.get("type") == "text")
            return {"type": "clarification", "text": text or "محتاج توضيح أكتر للطلب.", "history": messages}

        tool_results = []
        plan_result = None
        for block in tool_use_blocks:
            if block["name"] == "list_employees":
                result_data = [
                    {"name": e["name"], "email": e["email"], "department": e.get("department", ""), "language": e.get("language", "ar")}
                    for e in employees
                ]
                tool_results.append({
                    "type": "tool_result", "tool_use_id": block["id"],
                    "content": json.dumps(result_data, ensure_ascii=False),
                })
            elif block["name"] == "propose_plan":
                plan_result = {"type": "plan", **block["input"]}
                # لازم نرد على الـ tool_use ده حتى لو خلصنا، عشان الـ messages history يفضل صالح
                tool_results.append({
                    "type": "tool_result", "tool_use_id": block["id"],
                    "content": "Plan proposed and shown to the HR manager for approval.",
                })

        messages.append({"role": "user", "content": tool_results})

        if plan_result:
            return {**plan_result, "history": messages}

    return {"type": "clarification", "text": "معرفتش أوصل لخطة واضحة - ممكن تعيد صياغة الطلب؟", "history": messages}
