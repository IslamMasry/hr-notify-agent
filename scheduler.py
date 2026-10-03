"""
Scheduler — يدير مهمة واحدة متكررة (فحص الامتثال) بفترة زمنية قابلة للتعديل
من الواجهة، من غير ما نحتاج نعيد تشغيل السيرفر.
"""

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

scheduler = BackgroundScheduler()
_job = None
JOB_ID = "compliance_check"


def start(interval_minutes: int, func):
    """يبدأ أو يعيد جدولة المهمة بفترة جديدة. بيلغي أي جدولة سابقة أول ما يشتغل."""
    global _job
    stop()
    if not scheduler.running:
        scheduler.start()
    _job = scheduler.add_job(
        func,
        IntervalTrigger(minutes=interval_minutes),
        id=JOB_ID,
        replace_existing=True,
        max_instances=1,
    )


def stop():
    """يوقف الجدولة الحالية لو موجودة."""
    global _job
    try:
        scheduler.remove_job(JOB_ID)
    except Exception:
        pass
    _job = None


def get_next_run_iso():
    if _job is None:
        return None
    next_run = getattr(_job, "next_run_time", None)
    return next_run.isoformat() if next_run else None


def is_running() -> bool:
    return _job is not None
