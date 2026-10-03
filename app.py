"""
واجهة ويب بسيطة لتشغيل تاسك التبليغ:
- تعرض قائمة الموظفين وحالة كل واحد
- تولّد مسودات عبر Claude
- تبعت فعليًا بعد المراجعة (approve per employee)
- تعرض الـ audit log

تشغيل: uvicorn app:app --reload
"""

import json
import os
import sqlite3
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from fastapi.requests import Request
from fastapi.middleware.cors import CORSMiddleware

from task_definition import TASK
from claude_client import draft_notification_email, classify_employee_reply
from tools.email_sender import send_email
from tools.call_tool import place_call, get_call_status
from tools.inbox_checker import check_submission, get_latest_reply
from tools.knowledge_base import get_knowledge_base, set_knowledge_base
from tools.transcribe_tool import transcribe_audio
from audit_log import log_action, init_db, get_campaigns_summary
from config import AUDIT_DB_PATH, MANAGER_NOTIFY_EMAIL
from datetime import datetime, timezone
import scheduler as sched
from orchestrator import orchestrate
import uuid

app = FastAPI(title="HR Notify Agent")

# CORS: افتراضيًا مفتوح لأي origin (مناسب للتست ولو الفرونت إند مستضاف لوحده على هوست تاني).
# للإنتاج، حط ALLOWED_ORIGINS في .env بدومينك بالظبط (مفصول بفاصلة لو أكتر من واحد):
#   ALLOWED_ORIGINS=https://hr.yourcompany.com
# من غير ما تحتاج تعدّل الكود أو تعمل deploy تاني.
_allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "").strip()
_allowed_origins = [o.strip() for o in _allowed_origins_env.split(",") if o.strip()] or ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.on_event("startup")
def _startup():
    init_db()


@app.get("/api/task")
def get_task():
    """يرجع تفاصيل التاسك الحالية - بيستخدمها الفرونت إند حتى لو مستضاف لوحده على هوست تاني."""
    return TASK


# In-memory store للمسودات (كافي للتست؛ في الإنتاج ده هيبقى DB table)
DRAFTS: dict[str, dict] = {}
CALLS: dict[str, dict] = {}  # email -> {call_id, status, transcript}
COMPLIANCE: dict[str, dict] = {}  # email -> {submitted, note, checked_at}
PENDING_QUESTIONS: dict[str, dict] = {}  # email -> {summary, reply_text, task_title} - محتاج رد HR Manager

# بدل ما نكون مربوطين بتاسك ثابتة واحدة، بنسجل لكل موظف آخر تاسك اتواصلنا معاه
# بيها فعليًا (من الشات أو من أي مسار تاني) - ده اللي بيدّي الـ Agent السياق
# اللازم عشان يفهم رده لو رد بعدين، من غير ما نفترض "التاسك الوحيدة" globally.
LAST_TASK_FOR_EMPLOYEE: dict[str, dict] = {}  # email -> {"task": {...}, "since_date": "YYYY-MM-DD"}
SCHEDULE_SETTINGS: dict = {"interval_minutes": 60, "enabled": False, "last_run": None, "last_run_count": None}
PENDING_PLANS: dict = {}  # plan_id -> plan dict (awaiting approval)
CHAT_HISTORY: list = []  # محادثة الـ Chat tab المتواصلة - بتتصفر بـ /api/chat/reset


def load_employees():
    # بيستخدم نفس مصدر tools/employee_store.py (بيحترم DATA_DIR للنشر) - مفيش
    # مسار مكرر أو مختلف ممكن يلخبط بين الاثنين
    from tools.employee_store import list_employees
    return list_employees()


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
        request=request, name="index.html", context={"task": TASK}
    )


@app.get("/api/employees")
def get_employees():
    employees = load_employees()
    result = []
    for emp in employees:
        state = DRAFTS.get(emp["email"], {"status": "pending"})
        call_state = CALLS.get(emp["email"], {"call_status": "not_called"})
        compliance_state = COMPLIANCE.get(emp["email"], {"submitted": None, "note": ""})
        result.append({**emp, **state, **call_state, **compliance_state})
    return result


@app.post("/api/generate")
def generate_drafts():
    employees = load_employees()
    for emp in employees:
        name, email, lang = emp["name"], emp["email"], emp["language"]
        try:
            draft = draft_notification_email(name, lang, TASK)
            DRAFTS[email] = {
                "status": "draft_ready",
                "subject": draft["subject"],
                "body": draft["body"],
                "error": None,
            }
        except Exception as e:
            DRAFTS[email] = {
                "status": "draft_failed",
                "subject": "",
                "body": "",
                "error": str(e),
            }
    return get_employees()


@app.post("/api/send/{email}")
def send_one(email: str):
    employees = {e["email"]: e for e in load_employees()}
    if email not in employees:
        raise HTTPException(404, "الموظف غير موجود")

    draft = DRAFTS.get(email)
    if not draft or draft.get("status") != "draft_ready":
        raise HTTPException(400, "لازم تولّد مسودة جاهزة الأول")

    name = employees[email]["name"]
    try:
        send_email(email, draft["subject"], draft["body"])
        DRAFTS[email]["status"] = "sent"
        log_action(name, email, TASK["title"], draft["subject"], draft["body"], "sent")
        return {"status": "sent"}
    except Exception as e:
        DRAFTS[email]["status"] = "send_failed"
        DRAFTS[email]["error"] = str(e)
        log_action(name, email, TASK["title"], draft["subject"], draft["body"], "send_failed", str(e))
        raise HTTPException(500, f"فشل الإرسال: {e}")


@app.post("/api/send-all")
def send_all():
    """
    يبعت كل المسودات الجاهزة (draft_ready) دفعة واحدة.
    ده أكشن جماعي - الموافقة هنا هي ضغطة الزرار نفسها (مع تأكيد من الواجهة قبل النداء)،
    وكل إيميل بيتسجل في audit log لوحده بالظبط زي الإرسال الفردي.
    """
    employees = load_employees()
    results = []
    for emp in employees:
        email = emp["email"]
        draft = DRAFTS.get(email)
        if not draft or draft.get("status") != "draft_ready":
            continue
        try:
            send_email(email, draft["subject"], draft["body"])
            DRAFTS[email]["status"] = "sent"
            log_action(emp["name"], email, TASK["title"], draft["subject"], draft["body"], "sent")
            results.append({"email": email, "status": "sent"})
        except Exception as e:
            DRAFTS[email]["status"] = "send_failed"
            DRAFTS[email]["error"] = str(e)
            log_action(emp["name"], email, TASK["title"], draft["subject"], draft["body"], "send_failed", str(e))
            results.append({"email": email, "status": "failed", "error": str(e)})
    return {"results": results}


@app.get("/api/audit")
def get_audit():
    conn = sqlite3.connect(AUDIT_DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM audit_log ORDER BY id DESC LIMIT 50"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/campaigns-summary")
def campaigns_summary():
    """
    ملخص كل التاسكات (campaigns) اللي اتنفذت في أي وقت - سواء التاسك الثابتة
    أو أي أمر اتنفذ من تبويب Chat. ده أساس شاشة Monitoring الحقيقية.
    """
    return get_campaigns_summary()


@app.post("/api/call/{email}")
def call_one(email: str):
    """
    يبدأ مكالمة تفاعلية فعلية للموظف. زي الإيميل بالظبط - ده الأكشن الفعلي،
    يعني الضغط على الزرار في الواجهة هو نفسه الـ approval.
    """
    employees = {e["email"]: e for e in load_employees()}
    if email not in employees:
        raise HTTPException(404, "الموظف غير موجود")

    emp = employees[email]
    phone = emp.get("phone", "").strip()
    if not phone:
        raise HTTPException(400, "مفيش رقم تليفون مسجل للموظف ده")

    try:
        task = _get_relevant_task(email)
        result = place_call(emp["name"], phone, emp["language"], task)
        CALLS[email] = {
            "call_status": result["status"],
            "call_id": result["id"],
            "transcript": result.get("note", ""),
            "task_title": task["title"],
        }
        log_action(
            emp["name"], email, task["title"], "[voice call]", "",
            f"call_{result['status']}", channel="call",
        )
        return CALLS[email]
    except Exception as e:
        CALLS[email] = {"call_status": "call_failed", "call_id": None, "transcript": ""}
        log_action(emp["name"], email, TASK["title"], "[voice call]", "", "call_failed", str(e), channel="call")
        raise HTTPException(500, f"فشلت المكالمة: {e}")


@app.get("/api/call-status/{email}")
def call_status(email: str):
    """يحدّث حالة المكالمة (polling) - مفيد لما المكالمة تخلص ويظهر الـ transcript."""
    state = CALLS.get(email)
    if not state or not state.get("call_id"):
        raise HTTPException(404, "مفيش مكالمة اتعملت للموظف ده لسه")

    employees = {e["email"]: e for e in load_employees()}
    emp = employees.get(email, {"name": email, "language": "ar"})
    _refresh_single_call(email, emp)
    return CALLS[email]


def _get_relevant_task(email: str) -> dict:
    """
    التاسك اللي نستخدمها كسياق لتصنيف رد/مكالمة الموظف ده - آخر تاسك اتواصلنا
    معاه بيها فعليًا. لو مفيش (لسه محدش كلمه)، نرجع للتاسك المدمجة الافتراضية
    كـ fallback بس عشان مايحصلش خطأ، مش لأنها "التاسك الوحيدة" النظام.
    """
    entry = LAST_TASK_FOR_EMPLOYEE.get(email)
    return entry["task"] if entry else TASK


def notify_manager_by_email(employee_name: str, channel: str, classification: dict,
                             content_text: str, vapi_summary: str = "") -> None:
    """
    بتبعت إيميل فعلي لـ HR Manager (MANAGER_NOTIFY_EMAIL) أول ما رد أو مكالمة
    محتاجة قراره - بدل ما يعتمد بس على إشعار المتصفح (اللي محتاج الصفحة تكون
    فاتحة) أو مراجعة الواجهة يدويًا. بتتنادى من أي نقطة تصعيد، سواء إيميل أو مكالمة.
    """
    if not MANAGER_NOTIFY_EMAIL:
        return  # مفيش إيميل متسجل نبعتله - سيبها من غير ما تكسر باقي المنطق

    channel_ar = "مكالمة تليفونية" if channel == "call" else "إيميل"
    subject = f"🔔 محتاج قرارك: {employee_name} ({channel_ar})"

    summary_block = classification.get("manager_summary") or "—"
    vapi_block = f"\n\nملخص Vapi التلقائي:\n{vapi_summary}" if vapi_summary else ""

    body = f"""مرحبًا،

فيه {channel_ar} من {employee_name} محتاج قرارك:

التصنيف: {classification.get('classification', 'غير محدد')}
الملخص: {summary_block}{vapi_block}

النص الكامل:
{content_text}

---
افتح تبويب Monitor في التطبيق عشان ترد مباشرة.
"""
    try:
        send_email(MANAGER_NOTIFY_EMAIL, subject, body)
    except Exception as e:
        # فشل إرسال التنبيه نفسه متسجلش نظام التصعيد الأساسي - بس نسجله في audit
        log_action("system", MANAGER_NOTIFY_EMAIL, "manager_notification", subject, "",
                   "notify_email_failed", str(e), channel="email")


def _refresh_single_call(email: str, emp: dict) -> None:
    """يحدّث حالة مكالمة واحدة (polling + تصنيف المحتوى لو خلصت) - دالة عامة
    مش مربوطة بتاسك ثابتة، بتستخدم آخر تاسك فعلية اتواصلنا بيها مع الموظف ده."""
    state = CALLS.get(email)
    if not state or not state.get("call_id"):
        return

    task = _get_relevant_task(email)
    task_title = state.get("task_title", task.get("title", "—"))

    result = get_call_status(state["call_id"])
    CALLS[email]["call_status"] = result["status"]
    CALLS[email]["transcript"] = result.get("transcript", "")
    CALLS[email]["outcome"] = result.get("outcome", "")
    CALLS[email]["outcome_label_ar"] = result.get("outcome_label_ar", "")
    CALLS[email]["vapi_summary"] = result.get("vapi_summary", "")

    if result["status"] != "ended":
        return

    log_action(
        emp["name"], email, task_title, "[voice call]",
        result.get("transcript", ""), "call_ended", channel="call",
        call_outcome=result.get("outcome_label_ar", result.get("outcome", "")),
    )

    transcript = result.get("transcript", "")
    if not transcript or CALLS[email].get("content_classified"):
        return

    CALLS[email]["content_classified"] = True
    knowledge_base = get_knowledge_base()
    classification = classify_employee_reply(transcript, emp["name"], task, knowledge_base, emp.get("language", "ar"))
    CALLS[email]["content_classification"] = classification["classification"]

    log_action(
        emp["name"], email, task_title, f"[call content: {classification['classification']}]",
        transcript, f"call_classified_{classification['classification']}", channel="call",
        call_outcome=result.get("outcome_label_ar", ""),
    )

    if classification.get("needs_manager_input"):
        PENDING_QUESTIONS[email] = {
            "employee_name": emp["name"],
            "summary": classification.get("manager_summary", ""),
            "reply_text": transcript,
            "reply_subject": f"[Call] {task_title}",
            "task_title": task_title,
            "classification": classification["classification"],
            "channel": "call",
        }
        notify_manager_by_email(
            emp["name"], "call", classification, transcript,
            vapi_summary=result.get("vapi_summary", ""),
        )
    elif email in PENDING_QUESTIONS and PENDING_QUESTIONS[email].get("channel") == "call":
        del PENDING_QUESTIONS[email]


@app.post("/api/monitor/check-updates")
def check_updates():
    """
    فحص شامل عام لكل حاجة - مش مربوط بتاسك واحدة: بيحدّث حالة أي مكالمة لسه
    شغالة (queued/in-progress)، وبيفحص صناديق الوارد لأي موظف اتواصلنا معاه
    فعليًا (عن طريق آخر تاسك مسجلة له). ده الزرار الوحيد اللي محتاجه HR Manager
    عشان يتابع كل حاجة من مكان واحد.
    """
    return _run_check_updates()


def _run_check_updates() -> dict:
    """المنطق الفعلي - دالة عادية عشان تتنادى من الـ endpoint ومن الجدولة التلقائية بنفس الطريقة."""
    employees = {e["email"]: e for e in load_employees()}

    # ١. حدّث أي مكالمة لسه معلّقة
    calls_checked = 0
    for email, state in list(CALLS.items()):
        if state.get("call_status") in ("queued", "in-progress") and state.get("call_id"):
            emp = employees.get(email, {"name": email, "language": "ar"})
            _refresh_single_call(email, emp)
            calls_checked += 1

    # ٢. افحص صناديق الوارد لأي موظف عنده تاسك مسجلة فعليًا
    emails_checked = 0
    knowledge_base = get_knowledge_base()
    for email, entry in list(LAST_TASK_FOR_EMPLOYEE.items()):
        emp = employees.get(email)
        if not emp:
            continue
        task = entry["task"]
        reply = get_latest_reply(email, entry["since_date"])
        if reply is None:
            continue

        emails_checked += 1
        reply_text = reply.get("body") or reply.get("subject", "")
        classification = classify_employee_reply(reply_text, emp["name"], task, knowledge_base, emp["language"])
        is_submitted = classification["classification"] == "submitted"
        COMPLIANCE[email] = {
            "submitted": is_submitted, "note": classification.get("reasoning", ""),
            "overdue": False, "reply_classification": classification["classification"],
            "needs_manager_input": classification.get("needs_manager_input", False),
        }

        if classification.get("can_auto_reply") and classification.get("auto_reply_text"):
            try:
                send_email(email, f"Re: {reply.get('subject', task['title'])}", classification["auto_reply_text"])
                log_action(emp["name"], email, task["title"], f"[auto-reply: {classification['classification']}]",
                           classification["auto_reply_text"], "auto_replied", channel="email")
            except Exception as e:
                log_action(emp["name"], email, task["title"], "[auto-reply failed]", "", "auto_reply_failed", str(e), channel="email")

        if classification.get("needs_manager_input"):
            PENDING_QUESTIONS[email] = {
                "employee_name": emp["name"], "summary": classification.get("manager_summary", ""),
                "reply_text": reply_text, "reply_subject": reply.get("subject", ""),
                "task_title": task["title"], "classification": classification["classification"],
                "channel": "email",
            }
            log_action(emp["name"], email, task["title"], f"[escalated: {classification['classification']}]",
                       reply_text, "needs_manager_input", channel="email")
            notify_manager_by_email(emp["name"], "email", classification, reply_text)
        elif email in PENDING_QUESTIONS and PENDING_QUESTIONS[email].get("channel") == "email":
            del PENDING_QUESTIONS[email]

    SCHEDULE_SETTINGS["last_run"] = datetime.now(timezone.utc).isoformat()
    SCHEDULE_SETTINGS["last_run_count"] = calls_checked + emails_checked
    return {"calls_checked": calls_checked, "emails_checked": emails_checked}


# ============ حملة طلب التقرير + المتابعة التلقائية ============

def _is_overdue() -> bool:
    try:
        deadline = datetime.fromisoformat(TASK["deadline_iso"])
        return datetime.now() > deadline
    except Exception:
        return False


@app.post("/api/campaign/call-all")
def campaign_call_all():
    """يبدأ مكالمة أولى لكل الموظفين اللي عندهم رقم تليفون، تطلب منهم يبعتوا التقرير."""
    employees = load_employees()
    results = []
    for emp in employees:
        phone = emp.get("phone", "").strip()
        if not phone:
            continue
        try:
            result = place_call(emp["name"], phone, emp["language"], TASK, is_followup=False)
            CALLS[emp["email"]] = {
                "call_status": result["status"], "call_id": result["id"],
                "transcript": result.get("note", ""),
            }
            log_action(emp["name"], emp["email"], TASK["title"], "[initial call]", "",
                       f"call_{result['status']}", channel="call")
            results.append({"email": emp["email"], "status": result["status"]})
        except Exception as e:
            CALLS[emp["email"]] = {"call_status": "call_failed", "call_id": None, "transcript": ""}
            log_action(emp["name"], emp["email"], TASK["title"], "[initial call]", "", "call_failed", str(e), channel="call")
            results.append({"email": emp["email"], "status": "failed", "error": str(e)})
    return {"results": results}


@app.post("/api/campaign/check-compliance")
def campaign_check_compliance():
    """يفحص صندوق الوارد لكل موظف: هل بعت التقرير ولا لسه."""
    return _run_compliance_check()


def _run_compliance_check() -> dict:
    """
    المنطق الفعلي لفحص الامتثال - بيجيب آخر رد فعلي من كل موظف (مش بس يدور على
    كلمة في العنوان)، يصنّفه عبر Claude، ويقرر: يرد لوحده على الروتيني، ولا يصعّد
    لـ HR Manager. دالة مستقلة عشان تتنادى من الـ endpoint ومن الـ scheduler.
    """
    employees = load_employees()
    overdue = _is_overdue()
    knowledge_base = get_knowledge_base()
    results = []

    for emp in employees:
        email_addr = emp["email"]
        reply = get_latest_reply(email_addr, TASK["check_since_date"])

        if reply is None:
            # مفيش رد خالص لسه
            COMPLIANCE[email_addr] = {
                "submitted": False, "note": "مفيش رد لسه", "overdue": overdue,
                "reply_classification": None, "needs_manager_input": False,
            }
            results.append({"email": email_addr, **COMPLIANCE[email_addr]})
            continue

        reply_text = reply.get("body") or reply.get("subject", "")
        classification = classify_employee_reply(reply_text, emp["name"], TASK, knowledge_base, emp["language"])

        is_submitted = classification["classification"] == "submitted"
        COMPLIANCE[email_addr] = {
            "submitted": is_submitted,
            "note": classification.get("reasoning", ""),
            "overdue": overdue and not is_submitted,
            "reply_classification": classification["classification"],
            "needs_manager_input": classification.get("needs_manager_input", False),
        }

        # لو تقدر ترد لوحدك على حاجة روتينية - ابعت الرد فورًا وسجله
        if classification.get("can_auto_reply") and classification.get("auto_reply_text"):
            try:
                send_email(email_addr, f"Re: {reply.get('subject', TASK['title'])}", classification["auto_reply_text"])
                log_action(emp["name"], email_addr, TASK["title"], f"[auto-reply: {classification['classification']}]",
                           classification["auto_reply_text"], "auto_replied", channel="email")
                COMPLIANCE[email_addr]["note"] += " (تم الرد تلقائيًا)"
            except Exception as e:
                log_action(emp["name"], email_addr, TASK["title"], "[auto-reply failed]", "", "auto_reply_failed", str(e), channel="email")

        # لو محتاج تدخل HR Manager - صعّده
        if classification.get("needs_manager_input"):
            PENDING_QUESTIONS[email_addr] = {
                "employee_name": emp["name"],
                "summary": classification.get("manager_summary", ""),
                "reply_text": reply_text,
                "reply_subject": reply.get("subject", ""),
                "task_title": TASK["title"],
                "classification": classification["classification"],
                "channel": "email",
            }
            log_action(emp["name"], email_addr, TASK["title"], f"[escalated: {classification['classification']}]",
                       reply_text, "needs_manager_input", channel="email")
            notify_manager_by_email(emp["name"], "email", classification, reply_text)
        elif email_addr in PENDING_QUESTIONS and PENDING_QUESTIONS[email_addr].get("channel") != "call":
            del PENDING_QUESTIONS[email_addr]  # اتحل، شيله من قائمة الانتظار

        results.append({"email": email_addr, **COMPLIANCE[email_addr]})

    SCHEDULE_SETTINGS["last_run"] = datetime.now(timezone.utc).isoformat()
    SCHEDULE_SETTINGS["last_run_count"] = len(results)
    log_action(
        "system", "-", TASK["title"], "[scheduled compliance check]", "",
        f"checked_{len(results)}_employees", channel="scheduler",
    )
    return {"overdue": overdue, "results": results}


# ============ الأسئلة المحتاجة رد HR Manager ============

@app.get("/api/pending-questions")
def get_pending_questions():
    return [{"email": email, **data} for email, data in PENDING_QUESTIONS.items()]


@app.post("/api/pending-questions/{email}/answer")
def answer_pending_question(email: str, payload: dict):
    """
    HR Manager بيكتب رده هنا - بيتبعت كإيميل رد فعلي للموظف، ويتسجل في الـ audit،
    وبيتشال من قائمة الانتظار.
    """
    answer_text = payload.get("answer", "").strip()
    if not answer_text:
        raise HTTPException(400, "لازم تكتب رد")

    pending = PENDING_QUESTIONS.get(email)
    if not pending:
        raise HTTPException(404, "مفيش سؤال معلّق للموظف ده")

    try:
        subject = f"Re: {pending.get('reply_subject') or pending['task_title']}"
        send_email(email, subject, answer_text)
        log_action(pending["employee_name"], email, pending["task_title"],
                   "[manager reply]", answer_text, "manager_replied", channel="email")
        del PENDING_QUESTIONS[email]
        if email in COMPLIANCE:
            COMPLIANCE[email]["needs_manager_input"] = False
            COMPLIANCE[email]["note"] = "HR Manager رد يدويًا"
        return {"status": "sent"}
    except Exception as e:
        raise HTTPException(500, f"فشل إرسال الرد: {e}")


# ============ Knowledge Base (سياسات الشركة) ============

@app.get("/api/settings/knowledge-base")
def get_kb():
    return {"content": get_knowledge_base()}


@app.post("/api/settings/knowledge-base")
def update_kb(payload: dict):
    content = payload.get("content", "")
    set_knowledge_base(content)
    return {"content": content}


@app.post("/api/campaign/followup/{email}")
def campaign_followup(email: str):
    """يعمل مكالمة متابعة (follow-up) لموظف واحد لسه ملبعتش التقرير."""
    employees = {e["email"]: e for e in load_employees()}
    if email not in employees:
        raise HTTPException(404, "الموظف غير موجود")

    emp = employees[email]
    phone = emp.get("phone", "").strip()
    if not phone:
        raise HTTPException(400, "مفيش رقم تليفون مسجل للموظف ده")

    try:
        task = _get_relevant_task(email)
        result = place_call(emp["name"], phone, emp["language"], task, is_followup=True)
        CALLS[email] = {
            "call_status": result["status"], "call_id": result["id"],
            "transcript": result.get("note", ""), "task_title": task["title"],
        }
        log_action(emp["name"], email, task["title"], "[followup call]", "",
                   f"followup_{result['status']}", channel="call")
        return CALLS[email]
    except Exception as e:
        log_action(emp["name"], email, TASK["title"], "[followup call]", "", "followup_failed", str(e), channel="call")
        raise HTTPException(500, f"فشلت مكالمة المتابعة: {e}")


# ============ الجدولة التلقائية للتحقق من الامتثال ============

@app.get("/api/schedule")
def get_schedule():
    return {
        **SCHEDULE_SETTINGS,
        "next_run": sched.get_next_run_iso(),
        "is_running": sched.is_running(),
    }


@app.post("/api/schedule")
def update_schedule(payload: dict):
    """
    بيحدّث فترة الفحص التلقائي وحالته (تشغيل/إيقاف).
    body: {"interval_minutes": 30, "enabled": true}
    """
    interval = int(payload.get("interval_minutes", SCHEDULE_SETTINGS["interval_minutes"]))
    enabled = bool(payload.get("enabled", SCHEDULE_SETTINGS["enabled"]))

    if interval < 1:
        raise HTTPException(400, "الفترة لازم تكون دقيقة واحدة على الأقل")

    SCHEDULE_SETTINGS["interval_minutes"] = interval
    SCHEDULE_SETTINGS["enabled"] = enabled

    if enabled:
        sched.start(interval, _run_check_updates)
    else:
        sched.stop()

    return get_schedule()


# ============ Chat Orchestrator (ad-hoc commands) ============

@app.post("/api/chat")
def chat_command(payload: dict):
    """
    بياخد أمر HR Manager بلغة طبيعية، يحوله لخطة عبر الـ orchestrator،
    ويرجع الخطة للمراجعة (مبينفذش حاجة فعليًا هنا).
    المحادثة متواصلة عبر CHAT_HISTORY - الأوامر الجديدة بتاخد سياق الأوامر اللي قبلها.
    body: {"message": "كلم فريق المبيعات وذكرهم بموعد التقييم"}
    """
    global CHAT_HISTORY
    message = payload.get("message", "").strip()
    if not message:
        raise HTTPException(400, "الرسالة فارغة")

    employees = load_employees()
    result = orchestrate(message, employees, history=CHAT_HISTORY)
    CHAT_HISTORY = result.get("history", CHAT_HISTORY)

    if result["type"] == "clarification":
        return {"type": "clarification", "text": result["text"]}

    # حوّل الإيميلات لأسماء عشان تتعرض واضحة في الواجهة
    emp_by_email = {e["email"]: e for e in employees}
    recipients_detail = [
        {"email": em, "name": emp_by_email.get(em, {}).get("name", em)}
        for em in result.get("recipient_emails", [])
    ]

    plan_id = str(uuid.uuid4())
    plan = {**result, "id": plan_id, "recipients_detail": recipients_detail, "status": "pending"}
    PENDING_PLANS[plan_id] = plan
    return plan


@app.post("/api/chat/reset")
def chat_reset():
    """يبدأ محادثة جديدة من الصفر - مفيد لما المدير يبدأ موضوع مختلف تمامًا."""
    global CHAT_HISTORY
    CHAT_HISTORY = []
    return {"status": "reset"}


@app.post("/api/chat/execute/{plan_id}")
def chat_execute(plan_id: str):
    """ينفذ خطة اتوافق عليها من HR Manager - إيميل و/أو مكالمة لكل مستلم."""
    plan = PENDING_PLANS.get(plan_id)
    if not plan:
        raise HTTPException(404, "الخطة غير موجودة أو خلصت صلاحيتها")

    employees = {e["email"]: e for e in load_employees()}
    channel = plan["channel"]
    results = []

    # نبني task dict متوافق مع claude_client و call_tool الموجودين بالفعل
    ad_hoc_task = {
        "title": plan["title"], "announcement": plan["announcement"], "request": plan["request"],
        "deadline": plan["deadline"], "action_link": "",
        "sender_name": TASK["sender_name"], "sender_role": TASK["sender_role"],
    }
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for email in plan.get("recipient_emails", []):
        emp = employees.get(email)
        if not emp:
            results.append({"email": email, "status": "employee_not_found"})
            continue

        entry = {"email": email, "name": emp["name"]}
        # نسجل التاسك دي كـ "آخر تاسك اتواصلنا بيها مع الموظف ده" - أساس المتابعة العامة
        LAST_TASK_FOR_EMPLOYEE[email] = {"task": ad_hoc_task, "since_date": today_str}

        if channel in ("email", "both"):
            try:
                draft = draft_notification_email(emp["name"], emp["language"], ad_hoc_task)
                send_email(email, draft["subject"], draft["body"])
                log_action(emp["name"], email, plan["title"], draft["subject"], draft["body"],
                           "sent", channel="email")
                entry["email_status"] = "sent"
            except Exception as e:
                log_action(emp["name"], email, plan["title"], "[chat email]", "", "send_failed", str(e), channel="email")
                entry["email_status"] = f"failed: {e}"

        if channel in ("call", "both"):
            phone = emp.get("phone", "").strip()
            if not phone:
                entry["call_status"] = "no_phone_number"
            else:
                try:
                    call_result = place_call(emp["name"], phone, emp["language"], ad_hoc_task)
                    log_action(emp["name"], email, plan["title"], "[chat call]", "",
                               f"call_{call_result['status']}", channel="call")
                    entry["call_status"] = call_result["status"]
                    # مهم: نسجل المكالمة في CALLS العام عشان المتابعة التلقائية تلاقيها
                    CALLS[email] = {
                        "call_status": call_result["status"], "call_id": call_result["id"],
                        "transcript": "", "task_title": plan["title"],
                    }
                except Exception as e:
                    log_action(emp["name"], email, plan["title"], "[chat call]", "", "call_failed", str(e), channel="call")
                    entry["call_status"] = f"failed: {e}"

        results.append(entry)

    plan["status"] = "executed"

    # نضيف ملخص التنفيذ لتاريخ المحادثة عشان لو HR Manager سأل "حصل إيه؟" بعد كده يكون Claude عارف
    global CHAT_HISTORY
    CHAT_HISTORY = CHAT_HISTORY + [{
        "role": "assistant",
        "content": f"[System note: the approved plan '{plan['title_en']}' was executed. "
                    f"Results: {json.dumps(results, ensure_ascii=False)}]",
    }]

    return {"plan_id": plan_id, "results": results}


# ============ Settings: Employee Directory CRUD ============
# ملحوظة: دول بيستخدموا tools/employee_store.py بالكامل (نفس المصدر اللي load_employees()
# بيقرا منه) - قبل كده كان فيه نسخة تانية منفصلة (EMPLOYEES_CSV_PATH بمسار نسبي "employees.csv")
# ممكن تكتب في مكان مختلف عن اللي باقي التطبيق بيقرا منه، خصوصًا مع DATA_DIR في النشر.

from tools.employee_store import (
    list_employees as _es_list_employees,
    add_employee as _es_add_employee,
    update_employee as _es_update_employee,
    delete_employee as _es_delete_employee,
)


@app.get("/api/settings/employees")
def settings_list_employees():
    return _es_list_employees()


@app.post("/api/settings/employees")
def settings_add_employee(payload: dict):
    try:
        return _es_add_employee(payload)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.put("/api/settings/employees/{email}")
def settings_update_employee(email: str, payload: dict):
    try:
        return _es_update_employee(email, payload)
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.delete("/api/settings/employees/{email}")
def settings_delete_employee(email: str):
    try:
        _es_delete_employee(email)
        return {"deleted": email}
    except ValueError as e:
        raise HTTPException(404, str(e))


# ============ تحويل الصوت لنص (بديل عن Web Speech API) ============

@app.post("/api/transcribe")
async def transcribe(file: UploadFile = File(...)):
    """
    بياخد الصوت المسجل من المتصفح (MediaRecorder) ويرجع النص.
    مستقل تمامًا عن خدمات جوجل - بيعدي عبر سيرفرنا لـ OpenAI.
    """
    audio_bytes = await file.read()
    try:
        text = transcribe_audio(audio_bytes, file.filename or "audio.webm")
        return {"text": text}
    except Exception as e:
        raise HTTPException(500, f"فشل تحويل الصوت لنص: {e}")
