"""
Knowledge Base — نص حر (مش FAQ منظم) بيوصف سياسات HR الأساسية،
عشان الـ Agent يقدر يرد على أسئلة روتينية للموظفين من غيره ما يرجع لـ HR Manager
في كل حاجة. HR Manager بيعدّله من تبويب Settings.
"""

import json
import os
from config import DATA_DIR

KB_PATH = os.path.join(DATA_DIR, "knowledge_base.json")

DEFAULT_KB = """أمثلة على سياسات الشركة (عدّل ده من تبويب Settings):

- ميعاد استلام الإيميلات: من 9 صباحًا لـ 6 مساءً بتوقيت القاهرة، أيام العمل بس.
- لو الموظف طلب تأجيل يوم واحد بس ولسه قبل الديدلاين الأصلي بيومين على الأقل، الرد الافتراضي: موافقة تلقائية.
- لو الموظف سأل "أبعت التقرير فين؟" الإجابة: نفس الإيميل المذكور في الطلب الأصلي.
- أي طلب تأجيل أكتر من يومين، أو أي استثناء من سياسة الشركة، لازم يرجع لـ HR Manager - ممنوع الموافقة عليه تلقائيًا.
"""


def get_knowledge_base() -> str:
    if not os.path.exists(KB_PATH):
        return DEFAULT_KB
    with open(KB_PATH, encoding="utf-8") as f:
        return json.load(f).get("content", DEFAULT_KB)


def set_knowledge_base(content: str) -> None:
    with open(KB_PATH, "w", encoding="utf-8") as f:
        json.dump({"content": content}, f, ensure_ascii=False, indent=2)
