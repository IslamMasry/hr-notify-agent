# سيناريو الديمو: طلب تقرير من مجموعة موظفين + متابعة تلقائية لحد الديدلاين

# التاسك الافتراضية اللي النظام بيبدأ بيها - المستخدم يقدر يغيّرها بالكامل
# عن طريق إعطاء أمر جديد لـ الـ Assistant (نص أو صوت)

TASK = {
    "type": "report_request",
    "title": "تقرير مارس الشهري",
    "title_en": "Monthly March Report",
    "announcement": (
        "الإدارة محتاجة تقرير شهر مارس من كل موظف."
    ),
    "announcement_en": "Management needs the March monthly report from every employee.",
    "request": (
        "من فضلك ابعت التقرير بتاعك على الإيميل الرسمي، وخلي عنوان الإيميل فيه كلمة "
        "\"تقرير مارس\" عشان يتصنف صح."
    ),
    "request_en": (
        "Please send your report by email, and make sure the subject line includes "
        "\"March Report\" so it can be tracked correctly."
    ),
    "deadline": "الأربعاء القادم، 2 سبتمبر 2026",
    "deadline_en": "Wednesday, September 2, 2026",
    "deadline_iso": "2026-09-02T23:59:59",
    "action_link": "",
    "sender_name": "محمد العاشق",
    "sender_name_en": "Mohamed El-Asheq",
    "sender_role": "HR Manager",
    "sender_role_en": "HR Manager",

    # إعدادات خاصة بمتابعة التقارير
    "submission_email": "kicouae.ai@gmail.com",  # الإيميل اللي الموظفين هيبعتوا عليه
    "subject_keyword": "تقرير مارس",  # الكلمة المفتاحية اللي بندور عليها في عنوان الإيميل
    "check_since_date": "2026-08-25",  # ندور على إيميلات بعد التاريخ ده بس
}
