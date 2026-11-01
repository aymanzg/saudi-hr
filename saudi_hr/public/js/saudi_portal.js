/* Saudi HR portal runtime - shared by /mobile-attendance and /saudi-admin.
 *
 * Owns the four things every portal page needs: language switching, panel
 * routing, toasts, and logout. Page-specific behaviour is never referenced
 * from here; a page registers it into the hook maps below. That keeps the
 * employee and admin surfaces on one implementation without either one
 * dragging the other's data calls along.
 *
 * No build step and no framework: this is ES5 on purpose, matching the
 * www pages that already ship.
 */

var CURRENT_LANG = "ar";

/* panel name -> function called when that panel becomes visible */
var SAUDI_PANEL_LOADERS = {};
/* called after the language changes, so a page can re-render dynamic markup */
var SAUDI_LANG_RENDERERS = [];
/* localStorage key holding the last visible panel, per page */
var SAUDI_PANEL_STORE_KEY = "saudi_hr_panel";

var LABELS = {
	ar: {
		hero_greeting: "مرحباً، ",
		hero_subtitle: "نتمنى لك يوماً مليئاً بالإنجاز والنجاح",
		leave_balance: "رصيد الإجازات",
		att_checked_in_now: "وقت تسجيل الدخول",
		att_checked_out: "تم تسجيل الانصراف",
		att_not_checked_in: "لم تسجل الحضور بعد",
		attendance: "تسجيل الدوام",
		view_all: "عرض الكل",
		days_remaining: "يوم متبقي",
		annual_leave: "إجازة سنوية",
		sick_leave: "إجازة مرضية",
		marriage_leave: "إجازة زواج",
		bereavement_leave: "إجازة وفاة",
		other_leave: "إجازات أخرى",
		recent_requests: "طلباتي الأخيرة",
		no_recent: "لا توجد طلبات حديثة",
		banner_title: "معاً نحو بيئة عمل أفضل",
		banner_subtitle: "نحن هنا لدعمك في رحلتك المهنية",
		leave_request: "طلب إجازة",
		service_request: "طلب خدمة",
		my_requests: "طلباتي",
		attendance_checkin: "تسجيل الحضور والانصراف",
		profile: "الملف الشخصي",
		back: "رجوع",
		select_employee: "اختر الموظف",
		no_data: "لا توجد بيانات",
		no_requests: "لا توجد طلبات",
		disciplinary_procedures: "إجراءات تأديبية",
		disc_date: "التاريخ",
		disc_ack: "الإقرار",
		disc_ack_btn: "إقرار",
		disc_objection: "اعتراض",
		disc_objection_ph: "اكتب اعتراضك...",
		disc_submit_objection: "تقديم اعتراض",
		disc_ack_done: "تم الإقرار",
		disc_objection_done: "تم تقديم الاعتراض",
		company_policy: "سياسة الشركة",
		company_policy_sub: "اطلع على لوائح وسياسات الشركة",
		company_policies: "سياسة الشركة",
		view_policy: "عرض / تحميل",
		no_policies: "لا توجد سياسات منشورة حالياً",
		policies_hero_title: "لوائح وسياسات الشركة",
		policies_hero_sub: "اطلع على السياسات المعتمدة وأقر بالاطلاع عليها",
		policies_search: "ابحث في السياسات",
		policies_total: "السياسات",
		policies_pending: "بانتظار الإقرار",
		policies_done: "تم الإقرار",
		policy_effective: "سارية من",
		policy_version: "الإصدار",
		policy_open: "عرض السياسة",
		policy_no_file: "لا يوجد ملف مرفق",
		policy_acknowledged: "تم الإقرار",
		policy_ack_pending: "بانتظار الإقرار",
		policy_ack_due: "قبل",
		policy_ack_btn: "إقرار بالاطلاع",
		policy_ack_hint: "اكتب العبارة التالية كما هي للتأكيد",
		policy_ack_confirm: "تأكيد",
		policy_ack_cancel: "إلغاء",
		policy_ack_success: "تم تسجيل إقرارك بنجاح",
		policy_more: "المزيد",
		policy_less: "أقل",
		policies_load_error: "تعذر تحميل السياسات",
		policies_retry: "إعادة المحاولة",
		payslips_title: "كشوف الراتب",
		payslips_empty: "لا توجد كشوف راتب معتمدة حتى الآن",
		payslips_load_error: "تعذر تحميل كشوف الراتب",
		payslips_net: "صافي الراتب",
		payslips_earnings: "الاستحقاقات",
		payslips_deductions: "الخصومات",
		payslips_total_earnings: "إجمالي الاستحقاقات",
		payslips_total_deductions: "إجمالي الخصومات",
		payslips_period: "الفترة",
		payslips_working_days: "أيام العمل",
		payslips_absence_days: "أيام الغياب",
		payslips_currency: "ر.س",
		payslip_basic_salary: "الراتب الأساسي",
		payslip_housing_allowance: "بدل السكن",
		payslip_transport_allowance: "بدل المواصلات",
		payslip_other_allowances: "بدلات أخرى",
		payslip_overtime_addition: "العمل الإضافي",
		payslip_adjustment_addition: "إضافات أخرى",
		payslip_gosi_employee_deduction: "التأمينات الاجتماعية",
		payslip_sick_leave_deduction: "خصم الإجازة المرضية",
		payslip_loan_deduction: "قسط القرض",
		payslip_absence_deduction: "خصم الغياب",
		payslip_late_deduction: "خصم التأخير",
		payslip_penalty_deduction: "خصم الجزاءات",
		payslip_violation_deduction: "خصم المخالفات",
		payslip_advance_deduction: "خصم السلف",
		payslip_other_deductions: "خصومات أخرى",
		payslip_adjustment_deduction: "تعديلات أخرى",
		policies_no_match: "لا توجد نتائج مطابقة",
		normal_leave: "إجازة عادية",
		mobile_leave: "طلب جوال",
		leave_type: "نوع الإجازة",
		leave_subtype: "نوع الإجازة الفرعي",
		request_type: "نوع الطلب",
		srv_work_permit_issuance: "إصدار رخصة عمل",
		srv_work_permit_renewal: "تجديد رخصة عمل",
		srv_residency_issuance: "إصدار إقامة",
		srv_residency_renewal: "تجديد إقامة",
		srv_service_transfer: "نقل خدمات",
		srv_exit_and_return: "خروج وعودة",
		srv_final_exit: "خروج نهائي",
		srv_profession_modification: "تعديل مهنة",
		srv_employee_data_update: "تحديث بيانات الموظف",
		srv_visa_issuance: "إصدار تأشيرة",
		srv_advance_salary: "سلفة",
		srv_salary_certificate: "شهادة تعريف بالراتب",
		srv_experience_certificate: "شهادة خبرة",
		srv_employee_loan: "قرض موظف",
		new_req_leave_hint: "إجازة سنوية، مرضية، خاصة، أمومة",
		new_req_service_hint: "سلفة، قرض، شهادات، رخص، إقامات",
		punch_title: "تسجيل الحضور",
		leave_reason_placeholder: "أضف وصفًا مختصرًا للطلب",
		from_date: "من تاريخ",
		to_date: "إلى تاريخ",
		description: "السبب",
		submit_request: "تقديم الطلب",
		amount: "المبلغ",
		new_value: "القيمة الجديدة",
		all: "الكل",
		pending: "قيد المراجعة",
		approved: "معتمد",
		rejected: "مرفوض",
		punch_title: "تسجيل الدوام",
		punch_subtitle: "اضغط على تسجيل الحضور أو الانصراف للتحديث المباشر",
		punch_in: "تسجيل دخول (IN)",
		punch_out: "تسجيل خروج (OUT)",
		today_log: "سجل اليوم",
		no_punches: "لا توجد تسجيلات اليوم",
		monthly_summary: "ملخص الحضور الشهري",
		monthly_log: "سجل الحضور اليومي",
		loading: "جارٍ التحميل...",
		summary_present: "حاضر",
		summary_absent: "غائب",
		summary_leave: "إجازة",
		summary_rest: "عطلة",
		mlog_present: "حاضر",
		mlog_late: "متأخر",
		mlog_absent: "غائب",
		mlog_leave: "إجازة",
		mlog_half: "نصف يوم",
		mlog_rest: "عطلة",
		mlog_upcoming: "قادم",
		mlog_pending: "معلق",
		mlog_other: "أخرى",
		next_in: "التالية: تسجيل حضور",
		next_out: "التالية: تسجيل انصراف",
		employee_id: "رقم الموظف",
		company: "الشركة",
		department: "القسم",
		branch: "الفرع",
		email: "البريد الإلكتروني",
		logout: "تسجيل الخروج",
		logout_confirm: "هل تريد تسجيل الخروج؟",
		nav_home: "الرئيسية",
		nav_requests: "طلباتي",
		nav_leave: "الإجازات",
		nav_attendance: "الحضور",
		nav_more: "المزيد",
		submitting: "جاري الإرسال...",
		submitted_ok: "تم إرسال الطلب بنجاح",
		submitted_err: "حدث خطأ أثناء الإرسال",
		punch_ok_in: "تم تسجيل الدخول بنجاح",
		punch_ok_out: "تم تسجيل الخروج بنجاح",
		since_checkin: "منذ تسجيل الدخول",
		step_gps: "التحقق من الموقع (GPS)",
		locating: "جاري تحديد الموقع...",
		gps_ok: "تم تحديد الموقع بنجاح ✓",
		gps_fail: "تعذّر الحصول على الموقع. يرجى السماح بإذن الموقع.",
		step_photo: "صورة التحقق (كاميرا)",
		photo_click: "اضغط لالتقاط صورة (مطلوبة)",
		photo_done: "تم التقاط الصورة ✓",
		photo_change: "إعادة التقاط الصورة",
		capture_btn: "التقاط الصورة",
		camera_ready: "انتظر فتح الكاميرا...",
		camera_unavailable: "الكاميرا غير متاحة في هذا المتصفح",
		camera_permission_error: "يُرجى السماح بالوصول إلى الكاميرا",
		camera_denied: "تعذّر فتح الكاميرا",
		step_voice: "التحقق الصوتي",
		voice_record: "🎙 اقرأ الأرقام بصوت عالٍ",
		voice_listening: "جاري الاستماع... اقرأ الأرقام الآن",
		voice_detected: "تم التقاط الرقم: ",
		voice_unavailable: "التحقق الصوتي غير متاح في هذا المتصفح",
		voice_manual: "أو أدخل الأرقام يدويًا",
		voice_required_warn: "يرجى إدخال الأرقام أو نطقها قبل التأكيد",
		confirm: "تأكيد التسجيل",
		cancel: "إلغاء",
		leave_annual: "إجازة سنوية",
		leave_sick: "إجازة مرضية",
		leave_special: "إجازة خاصة",
		leave_maternity: "إجازة أمومة وأبوة",
		leave_emergency: "إجازة طارئة",
		leave_punch_correction: "تصحيح البصمة",
		leave_hour_leave: "استئذان",
		new_req_hour_hint: "طلب استئذان لعدد ساعات خلال اليوم",
		switch_to_admin: "الموافقات",
		switch_to_self: "الخدمة الذاتية",
		hour_leave_date: "تاريخ الاستئذان",
		hour_leave_from: "من الساعة",
		hour_leave_to: "إلى الساعة",
		hour_leave_total: "إجمالي الساعات",
		hour_leave_balance: "رصيد الاستئذان",
		hour_leave_allowance: "الرصيد الشهري",
		hour_leave_used: "المستخدم",
		hour_leave_available: "المتاح",
		hour_unit: "ساعة",
		hour_leave_window_error: "يرجى التأكد من الفترة الزمنية",
		hour_leave_whole_hours: "يجب أن تكون الساعات عددًا صحيحًا وبحد أدنى ساعة",
		hour_leave_insufficient: "رصيد الاستئذان غير كافٍ",
		reason_label: "مبرر الطلب",
		annual_balance: "رصيد الإجازة السنوية",
		emergency_balance: "رصيد الإجازة الطارئة",
		emergency_remaining: "المتاح من الإجازة الطارئة",
		emergency_gate_warning: "لا يمكنك طلب إجازة طارئة لوجود رصيد في الإجازة السنوية، استخدم رصيدك السنوي أولاً.",
		emergency_quota_warning: "استنفدت رصيد الإجازة الطارئة لهذا العام.",
		emergency_days_short: "عدد الأيام المطلوبة يتجاوز الرصيد المتاح من الإجازة الطارئة.",
		current_checkin: "وقت الحضور المسجل",
		current_checkout: "وقت الخروج المسجل",
		no_checkin_found: "لا توجد بصمة تسجيل دخول في هذا التاريخ — أدخل وقت الحضور لتسجيله.",
		corrected_time_label: "وقت الحضور الصحيح",
		corrected_out_time_label: "وقت الخروج الصحيح",
		corrected_time_required: "الرجاء تحديد وقت الحضور الصحيح",
		future_date_not_allowed: "لا يمكن التصحيح لتاريخ لم يحدث بعد",
		punch_select_target: "اختر ما تريد تصحيحه",
		punch_target_in: "تصحيح الدخول",
		punch_target_out: "تصحيح الخروج",
		new_req_punch_hint: "تصحيح وقت الدخول أو الخروج",
		half_day: "نصف يوم",
		attachments_label: "مرفقات الطلب",
		choose_subtype: "اختر النوع...",
		subtype_required: "الرجاء اختيار نوع الإجازة",
		start_date_required: "الرجاء تحديد تاريخ بداية الإجازة",
		day_unit: "يوم",
		loading: "جارٍ التحميل...",
		view_details: "عرض التفاصيل",
		select_type: "اختر النوع",
		home_title: "الرئيسية",
		session_expired: "جلستك انتهت، يرجى إعادة تسجيل الدخول للمتابعة",
		login_now: "تسجيل الدخول",
		leave_tab_normal: "إجازة سنوية",
		leave_tab_sick: "إجازة مرضية",
		leave_tab_other: "إجازة أخرى",
		new_request: "تقديم طلب جديد",
		new_request_subtitle: "اختر نوع الطلب الذي تريد تقديمه",

		/* ─── Admin portal (/saudi-admin) ─── */
		admin_brand: "إدارة الموارد البشرية",
		admin_nav_dashboard: "لوحة التحكم",
		admin_nav_approvals: "الموافقات",
		admin_nav_employees: "الموظفون",
		admin_nav_report: "التقارير",
		admin_welcome: "مرحباً",
		admin_welcome_subtitle: "ملخص الحضور ومستحقات الإجازات",
		admin_stat_total_employees: "إجمالي الموظفين",
		admin_stat_active: "الموظفون النشطون",
		admin_stat_saudi: "الموظفون السعوديون",
		admin_stat_actionable: "بانتظار إجراء",

		admin_search_employees: "ابحث بالاسم أو الرقم أو الهوية...",
		admin_search_leave: "ابحث بالموظف أو رقم الطلب...",
		admin_add_employee: "إضافة موظف",
		admin_edit_employee: "تعديل بيانات الموظف",
		admin_edit: "تعديل",
		admin_employee_saved: "تم حفظ بيانات الموظف بنجاح",
		admin_employee_updated: "تم تحديث بيانات الموظف بنجاح",
		admin_employee_count: "عدد الموظفين",
		admin_no_employees: "لا يوجد موظفون مطابقون",
		admin_col_number: "الرقم",
		admin_col_name: "الاسم",
		admin_col_department: "القسم",
		admin_col_designation: "المسمى الوظيفي",
		admin_col_company: "الشركة",
		admin_col_nationality: "الجنسية",
		admin_col_status: "الحالة",
		admin_col_joining: "تاريخ الالتحاق",
		admin_col_actions: "إجراءات",

		admin_approvals_pending: "طلبات بانتظار إجراء",
		admin_approvals_all: "كل الطلبات",
		admin_no_requests: "لا توجد طلبات",
		admin_no_actionable: "لا توجد طلبات بانتظار إجراء",
		admin_pick_request: "اختر طلباً من القائمة لعرض تفاصيله",
		admin_requester: "الموظف",
		admin_leave_type: "نوع الطلب",
		admin_period: "الفترة",
		admin_days: "عدد الأيام",
		admin_status: "الحالة",
		admin_request_no: "رقم الطلب",
		admin_view_in_desk: "عرض في Desk",
		admin_view: "عرض",
		admin_action_done: "تم تنفيذ الإجراء بنجاح",
		admin_action_failed: "تعذر تنفيذ الإجراء",
		admin_restricted_row: "لا تملك صلاحية فتح هذا الطلب",
		admin_submitting: "جارٍ التنفيذ...",
		admin_employee_details: "بيانات الموظف",
		admin_employee_requests: "طلبات الموظف",
		admin_employee_requests_truncated: "يعرض أحدث الطلبات فقط",
		admin_attendance: "الحضور",
		admin_attendance_overview: "ملخص الحضور",
		admin_attendance_department_overview: "ملخص الحضور حسب القسم",
		admin_attendance_today: "حضور اليوم",
		admin_attendance_month: "هذا الشهر",
		admin_attendance_recent: "أيام الحضور الأخيرة",
		admin_attendance_day: "اليوم",
		admin_attendance_hours_label: "الدخول والخروج",
		admin_attendance_days: "أيام مسجلة",
		admin_attendance_present: "حاضر",
		admin_attendance_absent: "غائب",
		admin_attendance_half_day: "نصف يوم",
		admin_attendance_on_leave: "في إجازة",
		admin_attendance_late_days: "أيام تأخير",
		admin_attendance_late_minutes: "دقائق التأخير",
		admin_attendance_hours: "ساعات العمل",
		admin_attendance_in: "دخول",
		admin_attendance_out: "خروج",
		admin_attendance_checkin: "آخر تسجيل",
		admin_attendance_no_records: "لا توجد سجلات حضور",
		admin_attendance_truncated: "يعرض أحدث الأيام فقط",
		admin_attendance_not_readable: "لا تملك صلاحية قراءة سجلات الحضور",
		admin_attendance_employees: "الموظفون",
		admin_attendance_employee: "الموظف",
		admin_attendance_department: "القسم",
		admin_attendance_type: "الحركة",
		admin_attendance_time: "الوقت",
		admin_attendance_window: "الفترة",
		admin_attendance_today_punches: "تسجيلات اليوم",
		admin_nav_attendance: "الحضور",
		admin_attendance_period: "نوع التقرير",
		admin_attendance_period_month: "تقرير شهري",
		admin_attendance_period_range: "تقرير بنطاق تاريخ",
		admin_attendance_period_day: "تقرير يوم واحد",
		admin_attendance_day: "التاريخ",
		admin_attendance_all_companies: "كل الشركات",
		admin_attendance_daily_board: "حضور اليوم",
		admin_attendance_roster_expected: "المتوقع",
		admin_attendance_roster_checked_in: "سجّل الحضور",
		admin_attendance_roster_not_checked_in: "لم يسجل",
		admin_attendance_roster_on_leave: "في إجازة",
		admin_attendance_roster_off: "عطلة/راحة",
		admin_attendance_roster_empty: "لا يوجد موظفون لعرضهم",
		admin_attendance_roster_truncated: "يعرض أول الموظفين فقط",
		admin_attendance_scope: "نطاق التقرير",
		admin_attendance_all_employees: "كل الموظفين",
		admin_attendance_search_employee: "رقم الموظف أو الاسم",
		admin_attendance_of_employee: "حضور {name}",
		admin_attendance_from: "من تاريخ",
		admin_attendance_to: "إلى تاريخ",
		admin_unit_day: "يوم",
		admin_unit_days: "أيام",
		admin_unit_hour: "ساعة",
		admin_unit_hours: "ساعات",
		admin_unit_hour: "ساعة",
		admin_unit_hours: "ساعات",
		admin_unit_minute: "دقيقة",
		admin_unit_minutes: "دقائق",
		admin_col_total: "الإجمالي",
		admin_attendance_no_punches: "لا توجد تسجيلات اليوم",
		admin_attendance_no_departments: "لا توجد سجلات حضور في هذه الفترة",
		admin_attendance_status_present: "حاضر",
		admin_attendance_status_absent: "غائب",
		admin_attendance_status_half_day: "نصف يوم",
		admin_attendance_status_on_leave: "في إجازة",
		admin_attendance_status_holiday: "عطلة رسمية",
		admin_attendance_status_weekly_off: "راحة أسبوعية",
		admin_attendance_status_missing: "لا يوجد سجل",
		admin_attendance_status_in_progress: "قيد الدوام",
		admin_attendance_status_not_checked_in: "لم يسجل الحضور",
		admin_attendance_day_note: "الملاحظة",
		admin_attendance_actions: "إجراء",
		admin_attendance_correct_title: "تصحيح حضور",
		admin_attendance_correct_new_checkin: "وقت الدخول الجديد",
		admin_attendance_correct_hint: "سيتم نقل تسجيل الدخول الفعلي لهذا اليوم إلى الوقت الجديد",
		admin_attendance_correct_new_checkout: "وقت الخروج الجديد",
		admin_attendance_correct_out_hint: "سيتم نقل تسجيل الخروج الفعلي لهذا اليوم إلى الوقت الجديد",
		admin_attendance_corrected_hint: "تم تصحيح هذا اليوم من قبل، ويمكن تصحيحه مرة أخرى. الحفظ سيحدّث نفس الطلب.",
		admin_attendance_correct_note: "الملاحظة",
		admin_attendance_correct_add_note: "إضافة ملاحظة",
		admin_attendance_correct_edit: "تصحيح",
		admin_attendance_add_missing: "إضافة الحضور",
		admin_attendance_corrected: "مصحح",
		admin_attendance_correct_saved: "تم حفظ التصحيح",
		admin_attendance_remove: "حذف",
		admin_attendance_remove_confirm: "سيتم حذف سجل هذا اليوم وبصماته نهائيًا. هل تريد المتابعة؟",
		admin_attendance_removed: "تم حذف سجل اليوم",
		admin_attendance_register_absence: "تسجيل غياب",
		admin_attendance_absence_hint: "سيتم تسجيل هذا اليوم كحالة غياب مغلقة، ويُخصم من الراتب.",
		admin_attendance_absence_type: "نوع الغياب",
		admin_attendance_absence_note: "ملاحظة (اختياري)",
		admin_attendance_absence_saved: "تم تسجيل حالة الغياب",
		admin_attendance_absence_chip: "حالة غياب",
		admin_field_joining_date: "تاريخ الالتحاق",
		admin_field_leaving_date: "تاريخ المغادرة",
		admin_field_personal_email: "البريد الشخصي",
		admin_field_iban: "الآيبان",

		// HR Service Request.request_type stores raw option values, so the
		// inbox would otherwise show "visa_issuance" instead of a label.
		srv_work_permit_issuance: "إصدار تصريح عمل",
		srv_work_permit_renewal: "تجديد تصريح عمل",
		srv_residency_issuance: "إصدار إقامة",
		srv_residency_renewal: "تجديد إقامة",
		srv_service_transfer: "نقل خدمات",
		srv_exit_and_return: "خروج وعودة",
		srv_final_exit: "خروج نهائي",
		srv_profession_modification: "تعديل المهنة",
		srv_employee_data_update: "تحديث بيانات الموظف",
		srv_visa_issuance: "إصدار تأشيرة",
		srv_advance_salary: "سلفة رواتب",
		srv_salary_certificate: "شهادة راتب",
		srv_experience_certificate: "شهادة خبرة",
		srv_employee_loan: "سلفة موظف",
		srv_job_confirmation: "خطاب تثبيت",
		srv_contract_copy: "نسخة عقد عمل",
		srv_payslip: "كشف راتب",
		srv_salary_benefits_statement: "بيان الراتب والمزايا",
		srv_addressed_letter: "خطاب موجه لجهة",
		srv_salary_transfer_letter: "خطاب تحويل راتب",
		srv_clearance: "المخالصة المالية",
		srv_end_of_service_cert: "شهادة نهاية خدمة",

		admin_state_draft: "مسودة",
		admin_state_pending: "بانتظار الموافقة",
		admin_state_approved: "معتمدة",
		admin_state_rejected: "مرفوضة",
		admin_state_cancelled: "ملغاة",
		admin_state_unknown: "غير محدد",
		admin_wstate_draft: "مسودة",
		admin_wstate_pending_hr_review: "بانتظار مراجعة الموارد البشرية",
		admin_wstate_rejected_by_hr: "مرفوض من الموارد البشرية",
		admin_wstate_pending_hr_manager_review: "بانتظار مراجعة مدير الموارد البشرية",
		admin_wstate_rejected_by_hr_manager: "مرفوض من مدير الموارد البشرية",
		admin_wstate_pending_gm_review: "بانتظار مراجعة المدير العام",
		admin_wstate_rejected_by_gm: "مرفوض من المدير العام",
		admin_wstate_gm_approved: "معتمد من المدير العام",
		admin_wstate_completed: "مكتمل",
		admin_wstate_cancelled: "ملغى",
		send_for_approval: "إرسال للموافقة",
		request_sent: "تم إرسال الطلب",
		admin_report_truncated: "الأرقام تشمل أحدث {types} فقط، وقد تكون هناك طلبات أقدم.",

		admin_section_identity: "البيانات الأساسية",
		admin_section_work: "بيانات العمل",
		admin_section_national: "البيانات الوطنية",
		admin_field_number: "الرقم الوظيفي",
		admin_field_full_name: "الاسم الكامل",
		admin_field_full_name_en: "الاسم بالإنجليزية",
		admin_field_company: "الشركة",
		admin_field_department: "القسم",
		admin_field_designation: "المسمى الوظيفي",
		admin_field_branch: "الفرع",
		admin_field_grade: "الدرجة",
		admin_field_reports_to: "المدير المباشر",
		admin_field_employment_type: "نوع التوظيف",
		admin_field_gender: "الجنس",
		admin_field_dob: "تاريخ الميلاد",
		admin_field_doj: "تاريخ الالتحاق",
		admin_field_status: "حالة الموظف",
		admin_field_email: "البريد الإلكتروني",
		admin_field_mobile: "رقم الجوال",
		admin_field_nationality: "الجنسية",
		admin_field_id_type: "نوع الهوية",
		admin_field_id_number: "رقم الهوية",
		admin_field_id_expiry: "انتهاء الهوية",
		admin_select_placeholder: "— اختر —",
		save: "حفظ",
		admin_action_submit: "إرسال",
		admin_action_approve: "اعتماد",
		admin_action_reject: "رفض",
		admin_action_cancel: "إلغاء الطلب",
		admin_action_submit_request: "إرسال الطلب",
		admin_action_resubmit_request: "إعادة إرسال الطلب",
		admin_action_supervisor_approve: "اعتماد المشرف",
		admin_action_supervisor_reject: "رفض المشرف",
		admin_action_hr_approve: "اعتماد الموارد البشرية",
		admin_action_hr_reject: "رفض الموارد البشرية",
		admin_action_hr_manager_approve: "اعتماد مدير الموارد البشرية",
		admin_action_hr_manager_reject: "رفض مدير الموارد البشرية",
		admin_action_gm_approve: "اعتماد المدير العام",
		admin_action_gm_reject: "رفض المدير العام",
		admin_action_mark_completed: "إكمال الطلب",
		admin_employees_restricted: "لا تملك صلاحية عرض قائمة الموظفين",
		admin_confirm_action: "هل تريد تنفيذ \"{action}\" على الطلب {name}؟",
		admin_punch_original: "الأصلي",
		admin_punch_reason: "مبرر التصحيح",
		admin_nav_clearance: "إنهاء الخدمة",
		admin_nav_documents: "مستندات وخطابات",
		admin_badge_new: "تجريبي",
		admin_clearance_title: "مخالصة مالية",
		admin_documents_title: "مستندات وخطابات",
		admin_doc_pending: "بانتظار الاعتماد",
		admin_doc_progress: "قيد الإجراء",
		admin_doc_issued: "صادرة هذا الشهر",
		admin_doc_rejected: "مرفوضة",
		admin_doc_new_request: "طلب جديد",
		admin_doc_issue: "إصدار",
		admin_doc_auto: "إصدار تلقائي",
		admin_doc_approval: "يتطلب اعتماد",
		admin_doc_termination: "عند انتهاء الخدمة",
		admin_clearance_print: "طباعة",
		admin_clearance_submit: "إرسال للاعتماد",
		admin_clearance_net: "صافي مبلغ المخالصة",
		admin_clearance_earnings: "المستحقات",
		admin_clearance_deductions: "الخصومات",
		admin_offboarding_title: "إنهاء الخدمة / إخلاء الطرف",
		admin_offboarding_reason: "سبب انتهاء الخدمة",
		admin_offboarding_salary_type: "نوع دفع الأجر",
		admin_offboarding_notice_start: "تاريخ بدء الإشعار",
		admin_offboarding_start: "ابدأ إخلاء الطرف",
		admin_offboarding_cases: "حالات إخلاء الطرف",
		admin_offboarding_status_label: "الحالة",
		admin_offboarding_progress: "نسبة الإنجاز",
		admin_offboarding_open: "فتح",
		admin_offboarding_no_cases: "لا توجد حالات إخلاء طرف بعد",
		admin_offboarding_status_draft: "مسودة",
		admin_offboarding_status_progress: "قيد التنفيذ",
		admin_offboarding_status_cleared: "مخلى طرفه",
		admin_offboarding_status_hold: "موقوف",
		admin_offboarding_notice: "إشعار الإنهاء",
		admin_offboarding_no_notice: "لا يوجد إشعار إنهاء مرتبط",
		admin_offboarding_sla: "تسوية نهاية الخدمة",
		admin_offboarding_due: "تاريخ الاستحقاق",
		admin_offboarding_settle: "إغلاق التسوية",
		admin_offboarding_settlement: "المخالصة المالية",
		admin_offboarding_net_eosb: "صافي المكافأة",
		admin_offboarding_create_eosb: "إنشاء المخالصة",
		admin_offboarding_submit_eosb: "اعتماد وصرف المكافأة",
		admin_offboarding_checklist: "قائمة إخلاء الطرف",
		admin_offboarding_check_access: "إيقاف الصلاحيات",
		admin_offboarding_check_assets: "تسليم العهد",
		admin_offboarding_check_attendance: "اعتماد الحضور النهائي",
		admin_offboarding_check_payroll: "إغلاق الرواتب",
		admin_offboarding_check_eosb: "اكتمال المكافأة",
		admin_offboarding_check_leave: "اكتمال صرف الإجازة",
		admin_offboarding_check_interview: "اكتمال مقابلة الخروج",
		admin_offboarding_check_handover: "اكتمال التسليم",
		admin_offboarding_save_checklist: "حفظ القائمة",
		admin_offboarding_print: "طباعة",
		admin_offboarding_interview: "مقابلة الخروج",
		admin_offboarding_create_interview: "جدولة مقابلة الخروج",
		admin_offboarding_leave: "صرف رصيد الإجازات",
		admin_offboarding_create_leave: "صرف رصيد الإجازات",
		admin_offboarding_last_working_day: "آخر يوم عمل",
		admin_offboarding_company: "الشركة",
		admin_offboarding_linked: "مرتبط",
		admin_offboarding_not_linked: "غير مرتبط",
		admin_offboarding_started: "تم بدء إخلاء الطرف",
		admin_offboarding_saved: "تم الحفظ",
		admin_offboarding_updated: "تم تحديث الحالة",
		admin_offboarding_notes_placeholder: "ملاحظات إخلاء الطرف",
	},
	en: {
		hero_greeting: "Hello, ",
		hero_subtitle: "Wishing you a productive and successful day",
		leave_balance: "Leave Balance",
		att_checked_in_now: "Checked in at",
		att_checked_out: "Checked out",
		att_not_checked_in: "Not checked in yet",
		attendance: "Attendance",
		view_all: "View All",
		days_remaining: "days left",
		annual_leave: "Annual Leave",
		sick_leave: "Sick Leave",
		marriage_leave: "Marriage Leave",
		bereavement_leave: "Bereavement Leave",
		other_leave: "Other Leave",
		recent_requests: "Recent Requests",
		no_recent: "No recent requests",
		banner_title: "Together towards a better workplace",
		banner_subtitle: "We are here to support you in your career journey",
		leave_request: "Leave Request",
		service_request: "Service Request",
		my_requests: "My Requests",
		attendance_checkin: "Attendance Check-in",
		profile: "Profile",
		back: "Back",
		select_employee: "Select Employee",
		no_data: "No data",
		no_requests: "No requests",
		disciplinary_procedures: "Disciplinary Procedures",
		disc_date: "Date",
		disc_ack: "Acknowledged",
		disc_ack_btn: "Acknowledge",
		disc_objection: "Objection",
		disc_objection_ph: "Write your objection...",
		disc_submit_objection: "Submit Objection",
		disc_ack_done: "Acknowledgement recorded",
		disc_objection_done: "Objection submitted",
		normal_leave: "Normal Leave",
		mobile_leave: "Mobile Request",
		leave_type: "Leave Type",
		leave_subtype: "Leave Subtype",
		request_type: "Request Type",
		srv_work_permit_issuance: "Work Permit Issuance",
		srv_work_permit_renewal: "Work Permit Renewal",
		srv_residency_issuance: "Residency Issuance",
		srv_residency_renewal: "Residency Renewal",
		srv_service_transfer: "Service Transfer",
		srv_exit_and_return: "Exit and Return",
		srv_final_exit: "Final Exit",
		srv_profession_modification: "Profession Modification",
		srv_employee_data_update: "Employee Data Update",
		srv_visa_issuance: "Visa Issuance",
		srv_advance_salary: "Salary Advance",
		srv_salary_certificate: "Salary Certificate",
		srv_experience_certificate: "Experience Certificate",
		srv_employee_loan: "Employee Loan",
		new_req_leave_hint: "Annual, sick, special, maternity leave",
		new_req_service_hint: "Advances, loans, certificates, permits, residencies",
		punch_title: "Attendance Check-in",
		leave_reason_placeholder: "Add a short description of your request",
		from_date: "From Date",
		to_date: "To Date",
		description: "Reason",
		submit_request: "Submit Request",
		amount: "Amount",
		new_value: "New Value",
		all: "All",
		pending: "Pending",
		approved: "Approved",
		rejected: "Rejected",
		punch_title: "Attendance Check-in",
		punch_subtitle: "Click Check-in or Check-out for live update",
		punch_in: "Check In (IN)",
		punch_out: "Check Out (OUT)",
		today_log: "Today's Log",
		no_punches: "No punches today",
		monthly_summary: "Monthly Attendance Summary",
		monthly_log: "Daily Attendance Log",
		loading: "Loading...",
		summary_present: "Present",
		summary_absent: "Absent",
		summary_leave: "Leave",
		summary_rest: "Rest",
		mlog_present: "Present",
		mlog_late: "Late",
		mlog_absent: "Absent",
		mlog_leave: "Leave",
		mlog_half: "Half Day",
		mlog_rest: "Rest",
		mlog_upcoming: "Upcoming",
		mlog_pending: "Pending",
		mlog_other: "Other",
		next_in: "Next: Check in",
		next_out: "Next: Check out",
		employee_id: "Employee ID",
		company: "Company",
		department: "Department",
		branch: "Branch",
		email: "Email",
		logout: "Log out",
		logout_confirm: "Do you want to log out?",
		nav_home: "Home",
		nav_requests: "Requests",
		nav_leave: "Leave",
		nav_attendance: "Attendance",
		nav_more: "More",
		submitting: "Submitting...",
		submitted_ok: "Request submitted successfully",
		submitted_err: "An error occurred while submitting",
		punch_ok_in: "Checked in successfully",
		punch_ok_out: "Checked out successfully",
		since_checkin: "Since check-in",
		step_gps: "GPS Location Check",
		locating: "Locating you...",
		gps_ok: "Location confirmed ✓",
		gps_fail: "Could not get location. Please allow location access.",
		step_photo: "Verification Photo (Camera)",
		photo_click: "Tap to take a photo (required)",
		photo_done: "Photo captured ✓",
		photo_change: "Retake photo",
		capture_btn: "Capture photo",
		camera_ready: "Waiting for camera...",
		camera_unavailable: "Camera not available in this browser",
		camera_permission_error: "Please allow camera access",
		camera_denied: "Could not open camera",
		step_voice: "Voice Verification",
		voice_record: "🎙 Read the digits aloud",
		voice_listening: "Listening... read the digits now",
		voice_detected: "Heard: ",
		voice_unavailable: "Voice verification not supported in this browser",
		voice_manual: "Or type the digits manually",
		voice_required_warn: "Please say or type the digits before confirming",
		confirm: "Confirm Check-in",
		cancel: "Cancel",
		leave_annual: "Annual Leave",
		leave_sick: "Sick Leave",
		leave_special: "Special Leave",
		leave_maternity: "Maternity / Paternity Leave",
		leave_emergency: "Emergency Leave",
		leave_punch_correction: "Punch Correction",
		leave_hour_leave: "Permission",
		new_req_hour_hint: "Request permission for a few hours of the same day",
		switch_to_admin: "Approvals",
		switch_to_self: "Self Service",
		hour_leave_date: "Permission Date",
		hour_leave_from: "From Time",
		hour_leave_to: "To Time",
		hour_leave_total: "Total Hours",
		hour_leave_balance: "Permission Balance",
		hour_leave_allowance: "Monthly Allowance",
		hour_leave_used: "Used",
		hour_leave_available: "Available",
		hour_unit: "hours",
		hour_leave_window_error: "Please check the time range",
		hour_leave_whole_hours: "Whole hours only (minimum 1 hour)",
		hour_leave_insufficient: "Insufficient permission balance",
		reason_label: "Reason",
		annual_balance: "Annual Leave Balance",
		emergency_balance: "Emergency Leave Balance",
		emergency_remaining: "Emergency leave remaining",
		emergency_gate_warning: "You cannot take emergency leave while annual leave remains. Please use your annual leave first.",
		emergency_quota_warning: "You have used all of this year's emergency leave.",
		emergency_days_short: "The days requested are more than the emergency leave you have left.",
		current_checkin: "Recorded check-in",
		current_checkout: "Recorded check-out",
		no_checkin_found: "There is no check-in punch on that date — enter a time to register it.",
		corrected_time_label: "Correct check-in time",
		corrected_out_time_label: "Correct check-out time",
		corrected_time_required: "Please choose the corrected check-in time",
		future_date_not_allowed: "You cannot correct a day that has not happened yet",
		punch_select_target: "Choose what to correct",
		punch_target_in: "Correct check-in",
		punch_target_out: "Correct check-out",
		new_req_punch_hint: "Correct your check-in or check-out time",
		half_day: "Half Day",
		attachments_label: "Attachments",
		choose_subtype: "Choose type...",
		subtype_required: "Please choose the leave type",
		start_date_required: "Please choose the leave start date",
		day_unit: "day",
		loading: "Loading...",
		view_details: "View Details",
		select_type: "Select Type",
		home_title: "Home",
		session_expired: "Your session has expired. Please login again",
		login_now: "Login",
		leave_tab_normal: "Annual Leave",
		leave_tab_sick: "Sick Leave",
		leave_tab_other: "Other Leave",
		new_request: "New Request",
		new_request_subtitle: "Choose the type of request you want to submit",

		/* ─── Admin portal (/saudi-admin) ─── */
		admin_brand: "HR Administration",
		admin_nav_dashboard: "Dashboard",
		admin_nav_approvals: "Approvals",
		admin_nav_employees: "Employees",
		admin_nav_report: "Reports",
		admin_welcome: "Welcome",
		admin_welcome_subtitle: "Workforce summary and leave entitlement",
		admin_stat_total_employees: "Total Employees",
		admin_stat_active: "Active Employees",
		admin_stat_saudi: "Saudi Employees",
		admin_stat_actionable: "Awaiting Action",

		admin_search_employees: "Search by name, number or ID...",
		admin_search_leave: "Search by employee or request no...",
		admin_add_employee: "Add Employee",
		admin_edit_employee: "Edit Employee",
		admin_edit: "Edit",
		admin_employee_saved: "Employee saved successfully",
		admin_employee_updated: "Employee updated successfully",
		admin_employee_count: "Employee count",
		admin_no_employees: "No matching employees",
		admin_col_number: "Number",
		admin_col_name: "Name",
		admin_col_department: "Department",
		admin_col_designation: "Designation",
		admin_col_company: "Company",
		admin_col_nationality: "Nationality",
		admin_col_status: "Status",
		admin_col_joining: "Joining Date",
		admin_col_actions: "Actions",

		admin_approvals_pending: "Awaiting Action",
		admin_approvals_all: "All Requests",
		admin_no_requests: "No requests",
		admin_no_actionable: "Nothing awaiting your action",
		admin_pick_request: "Choose a request from the list to review it",
		admin_requester: "Employee",
		admin_leave_type: "Request Type",
		admin_period: "Period",
		admin_days: "Days",
		admin_status: "Status",
		admin_request_no: "Request No",
		admin_view_in_desk: "Open in Desk",
		admin_view: "View",
		admin_action_done: "Action completed",
		admin_action_failed: "The action could not be completed",
		admin_restricted_row: "You cannot open this request",
		admin_submitting: "Working...",
		admin_employee_details: "Employee Details",
		admin_employee_requests: "Employee Requests",
		admin_employee_requests_truncated: "Showing the most recent requests only",
		admin_attendance: "Attendance",
		admin_attendance_overview: "Attendance Overview",
		admin_attendance_department_overview: "Attendance by Department",
		admin_attendance_today: "Today's Attendance",
		admin_attendance_month: "This Month",
		admin_attendance_recent: "Recent Attendance Days",
		admin_attendance_day: "Day",
		admin_attendance_hours_label: "In / Out",
		admin_attendance_days: "Recorded Days",
		admin_attendance_present: "Present",
		admin_attendance_absent: "Absent",
		admin_attendance_half_day: "Half Day",
		admin_attendance_on_leave: "On Leave",
		admin_attendance_late_days: "Late Days",
		admin_attendance_late_minutes: "Late Minutes",
		admin_attendance_hours: "Working Hours",
		admin_attendance_in: "In",
		admin_attendance_out: "Out",
		admin_attendance_checkin: "Latest Punch",
		admin_attendance_no_records: "No attendance records",
		admin_attendance_truncated: "Showing the most recent days only",
		admin_attendance_not_readable: "You cannot read attendance records",
		admin_attendance_employees: "Employees",
		admin_attendance_employee: "Employee",
		admin_attendance_department: "Department",
		admin_attendance_type: "Movement",
		admin_attendance_time: "Time",
		admin_attendance_window: "Period",
		admin_attendance_today_punches: "Today's Punches",
		admin_nav_attendance: "Attendance",
		admin_attendance_period: "Report Type",
		admin_attendance_period_month: "Monthly Report",
		admin_attendance_period_range: "Date Range Report",
		admin_attendance_period_day: "Single Day Report",
		admin_attendance_day: "Date",
		admin_attendance_all_companies: "All Companies",
		admin_attendance_daily_board: "Today's Attendance",
		admin_attendance_roster_expected: "Expected",
		admin_attendance_roster_checked_in: "Checked In",
		admin_attendance_roster_not_checked_in: "Not Checked In",
		admin_attendance_roster_on_leave: "On Leave",
		admin_attendance_roster_off: "Holiday/Rest",
		admin_attendance_roster_empty: "No employees to show",
		admin_attendance_roster_truncated: "Showing the first employees only",
		admin_attendance_scope: "Report Scope",
		admin_attendance_all_employees: "All Employees",
		admin_attendance_search_employee: "Employee number or name",
		admin_attendance_of_employee: "Attendance — {name}",
		admin_attendance_from: "From Date",
		admin_attendance_to: "To Date",
		admin_unit_day: "day",
		admin_unit_days: "days",
		admin_unit_hour: "hour",
		admin_unit_hours: "hours",
		company_policy: "Company Policy",
		company_policy_sub: "View company rules & policies",
		view_policy: "View / Download",
		no_policies: "No policy available",
		company_policies: "Company Policies",
		policies_hero_title: "Company rules & policies",
		policies_hero_sub: "Read the approved policies and confirm you have reviewed them",
		policies_search: "Search policies",
		policies_total: "Policies",
		policies_pending: "Awaiting acknowledgement",
		policies_done: "Acknowledged",
		policy_effective: "Effective",
		policy_version: "Version",
		policy_open: "Open policy",
		policy_no_file: "No file attached",
		policy_acknowledged: "Acknowledged",
		policy_ack_pending: "Awaiting acknowledgement",
		policy_ack_due: "Due",
		policy_ack_btn: "Acknowledge",
		policy_ack_hint: "Type the phrase below exactly to confirm",
		policy_ack_confirm: "Confirm",
		policy_ack_cancel: "Cancel",
		policy_ack_success: "Acknowledgement recorded",
		policy_more: "More",
		policy_less: "Less",
		policies_load_error: "Could not load policies",
		policies_retry: "Retry",
		payslips_title: "Pay Slips",
		payslips_empty: "No approved pay slips yet",
		payslips_load_error: "Could not load pay slips",
		payslips_net: "Net Salary",
		payslips_earnings: "Earnings",
		payslips_deductions: "Deductions",
		payslips_total_earnings: "Total Earnings",
		payslips_total_deductions: "Total Deductions",
		payslips_period: "Period",
		payslips_working_days: "Working Days",
		payslips_absence_days: "Absence Days",
		payslips_currency: "SAR",
		payslip_basic_salary: "Basic Salary",
		payslip_housing_allowance: "Housing Allowance",
		payslip_transport_allowance: "Transport Allowance",
		payslip_other_allowances: "Other Allowances",
		payslip_overtime_addition: "Overtime",
		payslip_adjustment_addition: "Other Additions",
		payslip_gosi_employee_deduction: "GOSI",
		payslip_sick_leave_deduction: "Sick Leave Deduction",
		payslip_loan_deduction: "Loan Installment",
		payslip_absence_deduction: "Absence Deduction",
		payslip_late_deduction: "Late Deduction",
		payslip_penalty_deduction: "Penalty Deduction",
		payslip_violation_deduction: "Violation Deduction",
		payslip_advance_deduction: "Advance Deduction",
		payslip_other_deductions: "Other Deductions",
		payslip_adjustment_deduction: "Other Adjustments",
		policies_no_match: "No policies match your search",
		admin_unit_minute: "minute",
		admin_unit_minutes: "minutes",
		admin_col_total: "Total",
		admin_attendance_no_punches: "No punches today",
		admin_attendance_no_departments: "No attendance records in this period",
		admin_attendance_status_present: "Present",
		admin_attendance_status_absent: "Absent",
		admin_attendance_status_half_day: "Half Day",
		admin_attendance_status_on_leave: "On Leave",
		admin_attendance_status_holiday: "Official Holiday",
		admin_attendance_status_weekly_off: "Weekly Rest",
		admin_attendance_status_missing: "No record",
		admin_attendance_status_in_progress: "On Shift",
		admin_attendance_status_not_checked_in: "Not Checked In",
		admin_attendance_day_note: "Note",
		admin_attendance_actions: "Action",
		admin_attendance_correct_title: "Correct Attendance",
		admin_attendance_correct_new_checkin: "New check-in time",
		admin_attendance_correct_hint: "The real check-in punch for this day will be moved to the new time",
		admin_attendance_correct_new_checkout: "New check-out time",
		admin_attendance_correct_out_hint: "The real check-out punch for this day will be moved to the new time",
		admin_attendance_corrected_hint: "This day was corrected before and can be corrected again. Saving updates the same request.",
		admin_attendance_correct_note: "Note",
		admin_attendance_correct_add_note: "Add note",
		admin_attendance_correct_edit: "Correct",
		admin_attendance_add_missing: "Add attendance",
		admin_attendance_corrected: "Corrected",
		admin_attendance_correct_saved: "Correction saved",
		admin_attendance_remove: "Remove",
		admin_attendance_remove_confirm: "This deletes the day's record and its punches permanently. Continue?",
		admin_attendance_removed: "Day removed",
		admin_attendance_register_absence: "Register absence",
		admin_attendance_absence_hint: "This records the day as a closed absence case, deducted from salary.",
		admin_attendance_absence_type: "Absence type",
		admin_attendance_absence_note: "Note (optional)",
		admin_attendance_absence_saved: "Absence case registered",
		admin_attendance_absence_chip: "Absence case",
		admin_field_joining_date: "Joining Date",
		admin_field_leaving_date: "Leaving Date",
		admin_field_personal_email: "Personal Email",
		admin_field_iban: "IBAN",

		srv_work_permit_issuance: "Work Permit Issuance",
		srv_work_permit_renewal: "Work Permit Renewal",
		srv_residency_issuance: "Residency Issuance",
		srv_residency_renewal: "Residency Renewal",
		srv_service_transfer: "Service Transfer",
		srv_exit_and_return: "Exit & Re-entry",
		srv_final_exit: "Final Exit",
		srv_profession_modification: "Profession Modification",
		srv_employee_data_update: "Employee Data Update",
		srv_visa_issuance: "Visa Issuance",
		srv_advance_salary: "Advance Salary",
		srv_salary_certificate: "Salary Certificate",
		srv_experience_certificate: "Experience Certificate",
		srv_employee_loan: "Employee Loan",
		srv_job_confirmation: "Job Confirmation",
		srv_contract_copy: "Contract Copy",
		srv_payslip: "Payslip",
		srv_salary_benefits_statement: "Salary & Benefits Statement",
		srv_addressed_letter: "Addressed Letter",
		srv_salary_transfer_letter: "Salary Transfer Letter",
		srv_clearance: "Financial Clearance",
		srv_end_of_service_cert: "End of Service Certificate",

		admin_state_draft: "Draft",
		admin_state_pending: "Pending Approval",
		admin_state_approved: "Approved",
		admin_state_rejected: "Rejected",
		admin_state_cancelled: "Cancelled",
		admin_state_unknown: "Unknown",
		admin_wstate_draft: "Draft",
		admin_wstate_pending_hr_review: "Pending HR Review",
		admin_wstate_rejected_by_hr: "Rejected by HR",
		admin_wstate_pending_hr_manager_review: "Pending HR Manager Review",
		admin_wstate_rejected_by_hr_manager: "Rejected by HR Manager",
		admin_wstate_pending_gm_review: "Pending GM Review",
		admin_wstate_rejected_by_gm: "Rejected by GM",
		admin_wstate_gm_approved: "GM Approved",
		admin_wstate_completed: "Completed",
		admin_wstate_cancelled: "Cancelled",
		send_for_approval: "Send for approval",
		request_sent: "Request sent",
		admin_report_truncated: "Counts cover the newest {types} only; older requests exist.",

		admin_section_identity: "Personal Details",
		admin_section_work: "Employment",
		admin_section_national: "Saudi Identity",
		admin_field_number: "Employee Number",
		admin_field_full_name: "Full Name",
		admin_field_full_name_en: "Full Name (English)",
		admin_field_company: "Company",
		admin_field_department: "Department",
		admin_field_designation: "Designation",
		admin_field_branch: "Branch",
		admin_field_grade: "Grade",
		admin_field_reports_to: "Reports To",
		admin_field_employment_type: "Employment Type",
		admin_field_gender: "Gender",
		admin_field_dob: "Date of Birth",
		admin_field_doj: "Date of Joining",
		admin_field_status: "Employment Status",
		admin_field_email: "Work Email",
		admin_field_mobile: "Mobile",
		admin_field_nationality: "Nationality",
		admin_field_id_type: "ID Type",
		admin_field_id_number: "ID Number",
		admin_field_id_expiry: "ID Expiry",
		admin_select_placeholder: "— Select —",
		save: "Save",
		admin_action_submit: "Submit",
		admin_action_approve: "Approve",
		admin_action_reject: "Reject",
		admin_action_cancel: "Cancel Request",
		admin_action_submit_request: "Submit Request",
		admin_action_resubmit_request: "Resubmit Request",
		admin_action_supervisor_approve: "Supervisor Approve",
		admin_action_supervisor_reject: "Supervisor Reject",
		admin_action_hr_approve: "HR Approve",
		admin_action_hr_reject: "HR Reject",
		admin_action_hr_manager_approve: "HR Manager Approve",
		admin_action_hr_manager_reject: "HR Manager Reject",
		admin_action_gm_approve: "GM Approve",
		admin_action_gm_reject: "GM Reject",
		admin_action_mark_completed: "Mark Completed",
		admin_employees_restricted: "You do not have permission to view the employee list",
		admin_confirm_action: "Apply \"{action}\" to request {name}?",
		admin_punch_original: "Original",
		admin_punch_reason: "Correction reason",
		admin_nav_clearance: "Offboarding",
		admin_nav_documents: "Documents & Letters",
		admin_badge_new: "BETA",
		admin_clearance_title: "Financial Clearance",
		admin_documents_title: "Documents & Letters",
		admin_doc_pending: "Awaiting Approval",
		admin_doc_progress: "In Progress",
		admin_doc_issued: "Issued This Month",
		admin_doc_rejected: "Rejected",
		admin_doc_new_request: "New Request",
		admin_doc_issue: "Issue",
		admin_doc_auto: "Instant Auto-Issue",
		admin_doc_approval: "Requires Approval",
		admin_doc_termination: "Upon Service End",
		admin_clearance_print: "Print",
		admin_clearance_submit: "Submit for Approval",
		admin_clearance_net: "Net Settlement Amount",
		admin_clearance_earnings: "Earnings",
		admin_clearance_deductions: "Deductions",
		admin_offboarding_title: "Offboarding / Exit Clearance",
		admin_offboarding_reason: "Termination reason",
		admin_offboarding_salary_type: "Salary payment type",
		admin_offboarding_notice_start: "Notice start date",
		admin_offboarding_start: "Start exit clearance",
		admin_offboarding_cases: "Exit clearance cases",
		admin_offboarding_status_label: "Status",
		admin_offboarding_progress: "Progress",
		admin_offboarding_open: "Open",
		admin_offboarding_no_cases: "No exit clearance cases yet",
		admin_offboarding_status_draft: "Draft",
		admin_offboarding_status_progress: "In progress",
		admin_offboarding_status_cleared: "Cleared",
		admin_offboarding_status_hold: "On hold",
		admin_offboarding_notice: "Termination notice",
		admin_offboarding_no_notice: "No termination notice linked",
		admin_offboarding_sla: "Final settlement",
		admin_offboarding_due: "Due date",
		admin_offboarding_settle: "Settle",
		admin_offboarding_settlement: "Financial settlement",
		admin_offboarding_net_eosb: "Net end of service",
		admin_offboarding_create_eosb: "Create settlement",
		admin_offboarding_submit_eosb: "Submit settlement",
		admin_offboarding_checklist: "Exit checklist",
		admin_offboarding_check_access: "Access revoked",
		admin_offboarding_check_assets: "Assets returned",
		admin_offboarding_check_attendance: "Final attendance verified",
		admin_offboarding_check_payroll: "Payroll closed",
		admin_offboarding_check_eosb: "EOSB completed",
		admin_offboarding_check_leave: "Leave disbursement completed",
		admin_offboarding_check_interview: "Exit interview completed",
		admin_offboarding_check_handover: "Handover completed",
		admin_offboarding_save_checklist: "Save checklist",
		admin_offboarding_print: "Print",
		admin_offboarding_interview: "Exit interview",
		admin_offboarding_create_interview: "Schedule exit interview",
		admin_offboarding_leave: "Leave disbursement",
		admin_offboarding_create_leave: "Pay leave balance",
		admin_offboarding_last_working_day: "Last working day",
		admin_offboarding_company: "Company",
		admin_offboarding_linked: "Linked",
		admin_offboarding_not_linked: "Not linked",
		admin_offboarding_started: "Exit clearance started",
		admin_offboarding_saved: "Saved",
		admin_offboarding_updated: "Status updated",
		admin_offboarding_notes_placeholder: "Exit clearance notes",
	}
};


/* ─── Language ─────────────────────────────────────────────────────────────── */

function t(key) {
	return (LABELS[CURRENT_LANG] && LABELS[CURRENT_LANG][key]) || key;
}

function applyLang() {
	document.querySelectorAll("[data-i18n-key]").forEach(function(el) {
		var k = el.getAttribute("data-i18n-key");
		var v = LABELS[CURRENT_LANG] && LABELS[CURRENT_LANG][k];
		if (!v) return;
		if (el.tagName === "INPUT" || el.tagName === "TEXTAREA") {
			el.placeholder = v;
		} else if (el.querySelector("*")) {
			// keep embedded elements (e.g. <span id="hero-user-name"> in the
			// home greeting) and only translate the leading text node
			var nodes = el.childNodes;
			for (var i = 0; i < nodes.length; i++) {
				if (nodes[i].nodeType === 3 && nodes[i].nodeValue.trim()) {
					nodes[i].nodeValue = v;
					break;
				}
			}
		} else {
			el.textContent = v;
		}
	});

	// a search box needs its own wording, not the label it sits under, and it
	// must never fall back to the Arabic text baked into the markup
	document.querySelectorAll("[data-i18n-placeholder]").forEach(function(el) {
		var k = el.getAttribute("data-i18n-placeholder");
		var v = LABELS[CURRENT_LANG] && LABELS[CURRENT_LANG][k];
		if (v) el.placeholder = v;
	});

	var toggle = document.getElementById("lang-toggle");
	if (toggle) toggle.textContent = CURRENT_LANG === "ar" ? "EN" : "عربي";

	document.body.className = CURRENT_LANG === "en" ? "ltr" : "";

	SAUDI_LANG_RENDERERS.forEach(function(fn) {
		try {
			fn();
		} catch (e) {
			// a page renderer must not break language switching
		}
	});
}

function toggleLang() {
	CURRENT_LANG = CURRENT_LANG === "ar" ? "en" : "ar";
	try { localStorage.setItem("saudi_hr_lang", CURRENT_LANG); } catch(e) {}
	applyLang();
	// pages re-draw the content they built in JS, which applyLang cannot reach
	if (typeof onPortalLangChange === "function") onPortalLangChange();
}

/* Restore the saved language, then sweep the document. */
function initPortalLang() {
	try {
		var saved = localStorage.getItem("saudi_hr_lang");
		if (saved === "ar" || saved === "en") CURRENT_LANG = saved;
	} catch(e) {}
	applyLang();
}

/* ─── Routing ──────────────────────────────────────────────────────────────── */

function navigate(panel) {
	document.querySelectorAll(".saudi-panel").forEach(function(p) {
		p.classList.remove("saudi-panel--active");
	});
	var el = document.getElementById("panel-" + panel);
	if (el) el.classList.add("saudi-panel--active");

	document.querySelectorAll(".saudi-nav-item, .saudi-rail__item").forEach(function(n) {
		n.classList.remove("saudi-nav-item--active", "saudi-rail__item--active");
	});
	// bottom nav on mobile, side rail on desktop; mark whichever rendered
	document
		.querySelectorAll('.saudi-nav-item[data-panel="' + panel + '"], .saudi-rail__item[data-panel="' + panel + '"]')
		.forEach(function(n) {
			n.classList.add(
				n.classList.contains("saudi-rail__item")
					? "saudi-rail__item--active"
					: "saudi-nav-item--active"
			);
		});

	try { localStorage.setItem(SAUDI_PANEL_STORE_KEY, panel); } catch(e) {}

	if (SAUDI_PANEL_LOADERS[panel]) {
		SAUDI_PANEL_LOADERS[panel]();
	}
}

function restorePanel(defaultPanel) {
	var wanted = defaultPanel;
	try {
		var saved = localStorage.getItem(SAUDI_PANEL_STORE_KEY);
		// only honour a saved panel that this page actually has
		if (saved && document.getElementById("panel-" + saved)) wanted = saved;
	} catch(e) {}
	navigate(wanted);
}

/* ─── Feedback ─────────────────────────────────────────────────────────────── */

function showToast(msg, type) {
	var el = document.getElementById("saudi-toast");
	if (!el) return;
	el.textContent = msg;
	el.className = "saudi-toast saudi-toast--" + (type || "success") + " show";
	setTimeout(function() { el.className = "saudi-toast"; }, 3000);
}

/* A failed admin call means the session is gone, so point at the login form
   rather than leaving the page showing whatever loaded before. Pages without a
   banner simply have nothing to show. */
function showSessionBanner() {
	var el = document.getElementById("session-banner");
	if (el) el.style.display = "flex";
}

/* Pull a clean, unstyled message out of a frappe error response. */
function serverErrorMessage(err, fallback) {
	if (!err) return fallback;
	if (err._server_messages && err._server_messages.length) {
		try {
			var raw = err._server_messages[0];
			if (typeof raw === 'string') {
				var t = raw.trim();
				if (t.startsWith('{') || t.startsWith('[')) {
					var parsed = JSON.parse(t);
					if (parsed && parsed.message) {
						return String(parsed.message).replace(/<[^>]+>/g, '').trim();
					}
				}
				var cleaned = raw.replace(/\"/g, '"').replace(/\\n/g, ' ').replace(/<[^>]+>/g, '').trim();
				if (cleaned.startsWith('"') && cleaned.endsWith('"')) {
					cleaned = cleaned.slice(1, -1);
				}
				if (cleaned) return cleaned;
			} else if (typeof raw === 'object' && raw.message) {
				return String(raw.message).replace(/<[^>]+>/g, '').trim();
			}
		} catch (e) {}
	}
	if (err.message) return String(err.message).replace(/<[^>]+>/g, '').trim();
	if (err.exc) return String(err.exc).replace(/<[^>]+>/g, '').trim();
	return fallback;
}
function openMonthlyEmployeeAttendanceReport() {
	window.open("/app/query-report/Team%20Attendance%20Review", "_blank");
}

function openEmployeeMonthlyAttendanceSummaryModal() {
	try {
		if (typeof frappe === "undefined" || !frappe.ui || typeof frappe.ui.Dialog !== "function") {
			window.open("/app/query-report/Employee%20Monthly%20Attendance%20Summary", "_blank");
			return;
		}
		var d = new frappe.ui.Dialog({
			title: __("Employee Monthly Attendance Summary / تقرير الحضور الشهري للموظف"),
			fields: [
				{ fieldname: "employee", label: __("Employee / الموظف"), fieldtype: "Link", options: "Employee", reqd: 1 },
				{ fieldname: "from_date", label: __("From Date / من تاريخ"), fieldtype: "Date", reqd: 1 },
				{ fieldname: "to_date", label: __("To Date / إلى تاريخ"), fieldtype: "Date", reqd: 1 }
			],
			primary_action_label: __("Open Report / فتح التقرير"),
			primary_action: function(values) {
				values = values || d.get_values();
				if (!values || !values.employee || !values.from_date || !values.to_date) {
					if (frappe.msgprint) {
						frappe.msgprint(__("Please fill all required fields / يرجى تعبئة الحقول المطلوبة"));
					}
					return;
				}
				var url = "/app/query-report/Employee%20Monthly%20Attendance%20Summary?employee=" + encodeURIComponent(values.employee) + "&from_date=" + encodeURIComponent(values.from_date) + "&to_date=" + encodeURIComponent(values.to_date);
				window.open(url, "_blank");
				d.hide();
			}
		});
		if (frappe.datetime) {
			d.set_value("from_date", frappe.datetime.month_start());
			d.set_value("to_date", frappe.datetime.month_end());
		}
		d.show();
	} catch (e) {
		window.open("/app/query-report/Employee%20Monthly%20Attendance%20Summary", "_blank");
	}
}

function logoutUser() {
	if (!confirm(t("logout_confirm"))) return;
	try { localStorage.removeItem(SAUDI_PANEL_STORE_KEY); } catch(e) {}
	// /api/method/logout answers with a JSON body, so navigating to it leaves
	// the user reading a response instead of the login form. The session ends
	// over fetch and the browser is sent to /login afterwards; a failure goes
	// there too, because a half-finished logout must not strand anyone on a
	// response body. Without fetch, web_logout is a page rather than a body.
	var toLogin = function () { window.location.href = "/login"; };
	if (window.fetch) {
		window.fetch("/api/method/logout", { method: "POST" }).then(toLogin, toLogin);
	} else {
		window.location.href = "/api/method/web_logout";
	}
}

function showInlineAttendanceReport() {
	var card = document.getElementById("inline-attendance-report-card");
	if (card) card.style.display = "block";
	var fromEl = document.getElementById("inline-att-from");
	var toEl = document.getElementById("inline-att-to");
	if (fromEl && !fromEl.value) {
		var d = new Date();
		var first = new Date(d.getFullYear(), d.getMonth(), 1);
		var last = new Date(d.getFullYear(), d.getMonth()+1, 0);
		fromEl.value = first.toISOString().slice(0,10);
		toEl.value = last.toISOString().slice(0,10);
	}
	var empSel = document.getElementById("inline-att-employee");
	if (empSel && empSel.options.length === 0) {
		frappe.call({
			method: "frappe.client.get_list",
			args: { doctype: "Employee", fields: ["name", "employee_name"], filters: {"status": "Active"}, limit_page_length: 1000, order_by: "employee_name asc" },
			callback: function(r) {
				var rows = r.message || [];
				rows.forEach(function(e) {
					var opt = document.createElement("option");
					opt.value = e.name;
					opt.textContent = e.employee_name ? (e.employee_name + " - " + e.name) : e.name;
					empSel.appendChild(opt);
				});
			}
		});
	}
	try { document.getElementById("panel-report").scrollIntoView({behavior:"smooth", block:"start"}); } catch(e){}
}

function hideInlineAttendanceReport() {
	var card = document.getElementById("inline-attendance-report-card");
	if (card) card.style.display = "none";
}

function runInlineAttendanceReport() {
	var emp = document.getElementById("inline-att-employee").value;
	var fromDate = document.getElementById("inline-att-from").value;
	var toDate = document.getElementById("inline-att-to").value;
	var tbody = document.getElementById("inline-att-rows");
	var sumDiv = document.getElementById("inline-att-summary");
	var note = document.getElementById("inline-att-note");
	if (!emp) { showToast(t("select_employee") || "Select Employee", "error"); return; }
	if (!fromDate || !toDate) { showToast("Select dates", "error"); return; }
	tbody.innerHTML = '<tr><td colspan="14">...</td></tr>';
	if (sumDiv) sumDiv.innerHTML = '';
	if (note) { note.hidden = true; note.textContent = ''; }
	frappe.call({
		method: "frappe.desk.query_report.run",
		args: { report_name: "Employee Monthly Attendance Summary", filters: {employee: emp, from_date: fromDate, to_date: toDate} },
		callback: function(r) {
			var res = r.message || {};
			var result = res.result || [];
			var summary = res.report_summary || [];
			if (sumDiv) {
				sumDiv.innerHTML = '';
				summary.forEach(function(s) {
					var div = document.createElement("div");
					div.className = "saudi-stat";
					div.innerHTML = '<div class="saudi-stat__label">' + (s.label || '') + '</div><div class="saudi-stat__value">' + (s.value !== undefined && s.value !== null ? s.value : '-') + '</div>';
					sumDiv.appendChild(div);
				});
			}
			tbody.innerHTML = '';
			if (!result.length) {
				if (note) { note.hidden = false; note.textContent = t("no_data") || "No data"; }
				return;
			}
			result.forEach(function(row) {
				var tr = document.createElement("tr");
				tr.innerHTML = '<td>' + (row.attendance_date||'') + '</td><td>' + (row.day||'') + '</td><td>' + (row.status||'') + '</td><td>' + (row.day_type||'') + '</td><td>' + (row.shift_type||'') + '</td><td>' + (row.attendance_location||'') + '</td><td>' + (row.in_time||'') + '</td><td>' + (row.out_time||'') + '</td><td>' + (row.worked_hours||0) + '</td><td>' + (row.late_minutes||0) + '</td><td>' + (row.early_exit_minutes||0) + '</td><td>' + (row.overtime_hours||0) + '</td><td>' + (row.leave_type||'') + '</td><td>' + (row.remarks||'') + '</td>';
				tbody.appendChild(tr);
			});
		}
	});
}

function exportInlineAttendanceReportPdf() {
	var emp = document.getElementById("inline-att-employee").value;
	var fromDate = document.getElementById("inline-att-from").value;
	var toDate = document.getElementById("inline-att-to").value;
	if (!emp || !fromDate || !toDate) {
		showToast(t("select_employee") || "Select Employee", "error");
		return;
	}
	var url = "/api/method/frappe.desk.query_report.export_query?";
	url += "report_name=" + encodeURIComponent("Employee Monthly Attendance Summary");
	url += "&file_format_type=PDF";
	url += "&filters=" + encodeURIComponent(JSON.stringify({employee: emp, from_date: fromDate, to_date: toDate}));
	url += "&visible_idx=" + encodeURIComponent("[]");
	window.open(url, "_blank");
}


function openMissingCheckoutViolationsModal() {
	if (typeof frappe === "undefined" || !frappe.ui || typeof frappe.ui.Dialog !== "function") {
		alert("فقط في بيئة Frappe");
		return;
	}
	var d = new frappe.ui.Dialog({
		title: __("Missing Check-Out Violations / تنبيهات عدم تسجيل الخروج"),
		size: "large",
		fields: [
			{ fieldname: "from_date", label: __("From Date / من تاريخ"), fieldtype: "Date", default: frappe.datetime.get_today() },
			{ fieldname: "to_date", label: __("To Date / إلى تاريخ"), fieldtype: "Date", default: frappe.datetime.get_today() },
			{ fieldname: "company", label: __("Company / الشركة"), fieldtype: "Link", options: "Company" },
			{ fieldname: "department", label: __("Department / القسم"), fieldtype: "Link", options: "Department" },
			{ fieldname: "results", label: "", fieldtype: "HTML" }
		],
		primary_action_label: __("Search / بحث"),
		primary_action: function(values) {
			loadMissingCheckoutViolations(d, values);
		}
	});
	d.show();
	d.fields_dict.results.$wrapper.html('<div class="text-muted">Use Search to load violations</div>');
}

function loadMissingCheckoutViolations(d, values) {
	values = values || d.get_values();
	var wrapper = d.fields_dict.results.$wrapper;
	wrapper.html('<div>Loading...</div>');
	frappe.call({
		method: "saudi_hr.saudi_hr.admin_api.get_missing_checkout_violations",
		args: values,
		callback: function(r) {
			var rows = r.message || [];
			if (!rows.length) {
				wrapper.html('<div class="text-muted">No missing check-out found</div>');
				return;
			}
			var html = '<table class="table table-bordered"><thead><tr><th>Employee</th><th>Date</th><th>In Time</th><th>Shift</th><th>Dept</th><th>Action</th></tr></thead><tbody>';
			rows.forEach(function(row, idx) {
				html += '<tr><td>' + (row.employee_name || row.employee) + ' (' + row.employee + ')</td><td>' + (row.attendance_date || '') + '</td><td>' + (row.in_time || '') + '</td><td>' + (row.shift_type || '') + '</td><td>' + (row.department || '') + '</td><td><button class="btn btn-xs btn-primary" data-idx="' + idx + '">رفع إجراء تأديبي</button></td></tr>';
			});
			html += '</tbody></table>';
			wrapper.html(html);
			wrapper.find("button").on("click", function() {
				var i = $(this).data("idx");
				var rec = rows[i];
				openDisciplinaryFromMissingCheckout(rec);
			});
		}
	});
}

function openDisciplinaryFromMissingCheckout(rec) {
	var url = "/app/disciplinary-procedure/new";
	var qs = [];
	qs.push("employee=" + encodeURIComponent(rec.employee));
	qs.push("incident_date=" + encodeURIComponent(rec.attendance_date));
	qs.push("violation_type=" + encodeURIComponent("Unauthorised Absence / غياب بدون إذن"));
	qs.push("reported_by=" + encodeURIComponent(frappe.session.user));
	var desc = "عدم تسجيل الخروج (Forgot to check-out) / Missing check-out punch on " + (rec.attendance_date || "") + ". First IN: " + (rec.in_time || "") + (rec.shift_type ? ". Shift: " + rec.shift_type : "") + ".";
	qs.push("incident_description=" + encodeURIComponent(desc));
	window.open(url + "?" + qs.join("&"), "_blank");
}

/* ─── Company policies ──────────────────────────── */
var POLICY_ACK_PHRASE = "أقر بالاطلاع والفهم";
var companyPolicies = [];

function escPolicy(v) {
	return String(v == null ? "" : v).replace(/[&<>"']/g, function(c) {
		return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c];
	});
}

// "Other / أخرى" → the half matching the current language
function policyLabel(v) {
	if (!v) return "";
	var parts = String(v).split(" / ");
	if (parts.length < 2) return v;
	return CURRENT_LANG === "ar" ? parts[parts.length - 1] : parts[0];
}

function policyFileIcon(type) {
	if (type === "pdf") return {label: "PDF", cls: "pdf"};
	if (type === "doc" || type === "docx") return {label: "DOC", cls: "doc"};
	if (type === "xls" || type === "xlsx" || type === "csv") return {label: "XLS", cls: "xls"};
	if (["png", "jpg", "jpeg", "webp"].indexOf(type) !== -1) return {label: "IMG", cls: "img"};
	return {label: "📄", cls: "other"};
}

SAUDI_PANEL_LOADERS["policies"] = function() {
	var list = document.getElementById("policies-list");
	if (!list) return;
	var search = document.getElementById("policies-search");
	if (search) search.value = "";
	document.getElementById("policies-stats").innerHTML = "";
	list.innerHTML = [1, 2].map(function() {
		return '<div class="saudi-policy saudi-policy--skeleton"><div class="saudi-policy__file"></div>' +
			'<div class="saudi-policy__main"><div class="saudi-skel saudi-skel--title"></div><div class="saudi-skel"></div><div class="saudi-skel saudi-skel--short"></div></div></div>';
	}).join("");
	frappe.call({
		method: "saudi_hr.saudi_hr.enterprise_operations.get_company_policies",
		callback: function(r) {
			companyPolicies = r.message || [];
			renderPolicyStats();
			renderCompanyPolicies(companyPolicies);
		},
		error: function() {
			list.innerHTML = '<div class="saudi-empty"><span class="saudi-empty__icon">⚠️</span><p>' + t("policies_load_error") + '</p>' +
				'<button type="button" class="saudi-policy__btn saudi-policy__btn--ghost" onclick="SAUDI_PANEL_LOADERS.policies()">' + t("policies_retry") + '</button></div>';
		}
	});
};

function renderPolicyStats() {
	var box = document.getElementById("policies-stats");
	if (!companyPolicies.length) { box.innerHTML = ""; return; }
	var pending = companyPolicies.filter(function(p) { return p.needs_acknowledgement; }).length;
	var done = companyPolicies.filter(function(p) { return p.acknowledged; }).length;
	box.innerHTML =
		'<div class="saudi-policies__stat"><b>' + companyPolicies.length + '</b><span>' + t("policies_total") + '</span></div>' +
		'<div class="saudi-policies__stat saudi-policies__stat--warn"><b>' + pending + '</b><span>' + t("policies_pending") + '</span></div>' +
		'<div class="saudi-policies__stat saudi-policies__stat--ok"><b>' + done + '</b><span>' + t("policies_done") + '</span></div>';
}

function renderCompanyPolicies(policies, isSearch) {
	var list = document.getElementById("policies-list");
	if (!policies.length) {
		list.innerHTML = '<div class="saudi-empty"><span class="saudi-empty__icon">' + (isSearch ? "🔍" : "📭") + '</span><p>' +
			t(isSearch ? "policies_no_match" : "no_policies") + '</p></div>';
		return;
	}
	// policies awaiting acknowledgement first
	var sorted = policies.slice().sort(function(a, b) { return (b.needs_acknowledgement ? 1 : 0) - (a.needs_acknowledgement ? 1 : 0); });
	list.innerHTML = sorted.map(policyCardHtml).join("");
}

function policyCardHtml(p) {
	var idx = companyPolicies.indexOf(p);
	var icon = policyFileIcon(p.file_type);
	var ack = p.acknowledgement || {};
	var status = "";
	if (p.acknowledged) {
		status = '<span class="saudi-chip saudi-chip--approved">✓ ' + t("policy_acknowledged") + (ack.acknowledged_on ? ' · ' + escPolicy(String(ack.acknowledged_on).slice(0, 10)) : '') + '</span>';
	} else if (p.needs_acknowledgement) {
		status = '<span class="saudi-chip saudi-chip--pending">⏳ ' + t("policy_ack_pending") + (ack.due_date ? ' · ' + t("policy_ack_due") + ' ' + escPolicy(ack.due_date) : '') + '</span>';
	}
	var meta = [];
	if (p.policy_category) meta.push('<span class="saudi-chip saudi-chip--muted">' + escPolicy(policyLabel(p.policy_category)) + '</span>');
	if (p.policy_version) meta.push('<span class="saudi-policy__meta-item">' + t("policy_version") + ' ' + escPolicy(p.policy_version) + '</span>');
	if (p.effective_date) meta.push('<span class="saudi-policy__meta-item">' + t("policy_effective") + ' ' + escPolicy(p.effective_date) + '</span>');
	var summary = p.summary_text || "";
	var summaryHtml = "";
	if (summary) {
		summaryHtml = '<p class="saudi-policy__summary" id="policy-summary-' + idx + '">' + escPolicy(summary) + '</p>';
		if (summary.length > 110) summaryHtml += '<button type="button" class="saudi-policy__more" onclick="togglePolicySummary(' + idx + ', this)">' + t("policy_more") + '</button>';
	}
	var actions = p.attachment_url
		? '<button type="button" class="saudi-policy__btn" onclick="openCompanyPolicy(' + idx + ')">' + t("policy_open") + '</button>'
		: '<span class="saudi-policy__nofile">' + t("policy_no_file") + '</span>';
	if (p.needs_acknowledgement) {
		actions += '<button type="button" class="saudi-policy__btn saudi-policy__btn--ghost" onclick="togglePolicyAck(' + idx + ')">' + t("policy_ack_btn") + '</button>';
	}
	return '<article class="saudi-policy' + (p.needs_acknowledgement ? ' saudi-policy--pending' : '') + '">' +
		'<div class="saudi-policy__file saudi-policy__file--' + icon.cls + '">' + icon.label + '</div>' +
		'<div class="saudi-policy__main">' +
			'<h3 class="saudi-policy__title">' + escPolicy(p.policy_title || p.name) + '</h3>' +
			(status ? '<div class="saudi-policy__status">' + status + '</div>' : '') +
			'<div class="saudi-policy__meta">' + meta.join("") + '</div>' +
			summaryHtml +
			'<div class="saudi-policy__actions">' + actions + '</div>' +
			(p.needs_acknowledgement ?
				'<div class="saudi-policy__ack" id="policy-ack-' + idx + '" hidden>' +
					'<div class="saudi-policy__ack-hint">' + t("policy_ack_hint") + '</div>' +
					'<div class="saudi-policy__ack-phrase">' + POLICY_ACK_PHRASE + '</div>' +
					'<input type="text" class="saudi-policy__ack-input" id="policy-ack-input-' + idx + '" dir="rtl" autocomplete="off" placeholder="' + POLICY_ACK_PHRASE + '">' +
					'<div class="saudi-policy__actions">' +
						'<button type="button" class="saudi-policy__btn" id="policy-ack-submit-' + idx + '" onclick="submitPolicyAck(' + idx + ')">' + t("policy_ack_confirm") + '</button>' +
						'<button type="button" class="saudi-policy__btn saudi-policy__btn--ghost" onclick="togglePolicyAck(' + idx + ')">' + t("policy_ack_cancel") + '</button>' +
					'</div>' +
				'</div>' : '') +
		'</div>' +
	'</article>';
}

function filterCompanyPolicies(q) {
	q = (q || "").trim().toLowerCase();
	if (!q) { renderCompanyPolicies(companyPolicies); return; }
	renderCompanyPolicies(companyPolicies.filter(function(p) {
		return [p.policy_title, p.policy_category, p.summary_text].join(" ").toLowerCase().indexOf(q) !== -1;
	}), true);
}

function togglePolicySummary(idx, btn) {
	var el = document.getElementById("policy-summary-" + idx);
	var open = el.classList.toggle("saudi-policy__summary--open");
	btn.textContent = t(open ? "policy_less" : "policy_more");
}

function togglePolicyAck(idx) {
	var box = document.getElementById("policy-ack-" + idx);
	box.hidden = !box.hidden;
	if (!box.hidden) document.getElementById("policy-ack-input-" + idx).focus();
}

function submitPolicyAck(idx) {
	var p = companyPolicies[idx];
	var input = document.getElementById("policy-ack-input-" + idx);
	var btn = document.getElementById("policy-ack-submit-" + idx);
	if (input.value.trim() !== POLICY_ACK_PHRASE) {
		input.classList.add("saudi-policy__ack-input--error");
		showToast(t("policy_ack_hint") + ": " + POLICY_ACK_PHRASE, "error");
		return;
	}
	btn.disabled = true;
	frappe.call({
		method: "saudi_hr.saudi_hr.enterprise_operations.acknowledge_company_policy",
		args: {policy: p.name, consent_text: input.value.trim()},
		callback: function(r) {
			showToast(t("policy_ack_success"), "success");
			SAUDI_PANEL_LOADERS.policies();
		},
		error: function(err) {
			btn.disabled = false;
			showToast(serverErrorMessage(err, t("policies_load_error")), "error");
		}
	});
}

function openCompanyPolicy(idx) {
	var p = companyPolicies[idx];
	if (p && p.attachment_url) {
		window.open(p.attachment_url, "_blank");
	} else {
		showToast(t("policy_no_file"), "error");
	}
}


SAUDI_PANEL_LOADERS["payslips"] = function() {
	var list = document.getElementById("payslips-list");
	if (!list) return;
	list.innerHTML = [1, 2].map(function() {
		return '<div class="saudi-policy saudi-policy--skeleton"><div class="saudi-policy__main"><div class="saudi-skel saudi-skel--title"></div><div class="saudi-skel saudi-skel--short"></div></div></div>';
	}).join("");
	frappe.call({
		method: "saudi_hr.saudi_hr.enterprise_operations.get_my_payslips",
		callback: function(r) {
			var slips = r.message || [];
			list.innerHTML = slips.length
				? slips.map(payslipHtml).join("")
				: '<div class="saudi-empty"><span class="saudi-empty__icon">📭</span><p>' + t("payslips_empty") + '</p></div>';
		},
		error: function() {
			list.innerHTML = '<div class="saudi-empty"><span class="saudi-empty__icon">⚠️</span><p>' + t("payslips_load_error") + '</p>' +
				'<button type="button" class="saudi-policy__btn saudi-policy__btn--ghost" onclick="SAUDI_PANEL_LOADERS.payslips()">' + t("policies_retry") + '</button></div>';
		}
	});
};

function payslipMoney(value) {
	return Number(value || 0).toLocaleString("en-US", {minimumFractionDigits: 2, maximumFractionDigits: 2});
}

// payroll months are stored as "October / أكتوبر"
function payslipMonth(month) {
	var parts = String(month || "").split(" / ");
	return (CURRENT_LANG === "en" ? parts[0] : parts[1]) || parts[0];
}

function payslipLines(items) {
	return items.map(function(item) {
		return '<div class="saudi-payslip__line"><span>' + t("payslip_" + item.key) + '</span><b>' + payslipMoney(item.amount) + '</b></div>';
	}).join("");
}

function payslipHtml(slip, index) {
	var currency = t("payslips_currency");
	var facts = [];
	if (slip.period_from && slip.period_to) facts.push(t("payslips_period") + ': <bdi>' + escPolicy(slip.period_from) + '</bdi> – <bdi>' + escPolicy(slip.period_to) + '</bdi>');
	if (slip.working_days) facts.push(t("payslips_working_days") + ': ' + slip.working_days);
	if (slip.absence_days) facts.push(t("payslips_absence_days") + ': ' + slip.absence_days);
	return '<details class="saudi-payslip"' + (index === 0 ? ' open' : '') + '>' +
		'<summary class="saudi-payslip__summary">' +
			'<span class="saudi-payslip__month">' + escPolicy(payslipMonth(slip.month)) + ' ' + escPolicy(slip.year) + '</span>' +
			'<span class="saudi-payslip__net"><small>' + t("payslips_net") + '</small><b>' + payslipMoney(slip.net_salary) + ' ' + currency + '</b></span>' +
		'</summary>' +
		'<div class="saudi-payslip__body">' +
			(facts.length ? '<div class="saudi-payslip__facts">' + facts.join(' · ') + '</div>' : '') +
			'<div class="saudi-payslip__heading">' + t("payslips_earnings") + '</div>' + payslipLines(slip.earnings) +
			'<div class="saudi-payslip__line saudi-payslip__line--total"><span>' + t("payslips_total_earnings") + '</span><b>' + payslipMoney(slip.total_earnings) + '</b></div>' +
			(slip.deductions.length
				? '<div class="saudi-payslip__heading">' + t("payslips_deductions") + '</div>' + payslipLines(slip.deductions) +
					'<div class="saudi-payslip__line saudi-payslip__line--total saudi-payslip__line--minus"><span>' + t("payslips_total_deductions") + '</span><b>' + payslipMoney(slip.total_deductions) + '</b></div>'
				: '') +
			'<div class="saudi-payslip__line saudi-payslip__line--net"><span>' + t("payslips_net") + '</span><b>' + payslipMoney(slip.net_salary) + ' ' + currency + '</b></div>' +
		'</div></details>';
}

SAUDI_PANEL_LOADERS["disciplinary"] = function() {
	var list = document.getElementById("disciplinaryList");
	if (!list) return;
	list.innerHTML = '<div class="saudi-list__item"><div class="saudi-list__body"><div class="saudi-list__title">' + (t("loading") || "Loading...") + '</div></div></div>';
	frappe.call({
		method: "saudi_hr.saudi_hr.api.get_my_disciplinary_procedures",
		args: { limit: 30 },
		callback: function(r) {
			var data = (r.message && r.message.data) || [];
			if (!data.length) {
				list.innerHTML = '<div class="saudi-list__item"><div class="saudi-list__body"><div class="saudi-list__title">' + (t("no_requests") || "No items") + '</div></div></div>';
				return;
			}
			var html = "";
			data.forEach(function(d) {
				var status = d.status || "";
				var ack = d.acknowledged_by_employee ? "✓" : "✗";
				html += '<div class="saudi-list__item" style="flex-direction:column;align-items:flex-start;gap:6px;">' +
					'<div style="display:flex;justify-content:space-between;width:100%;"><div class="saudi-list__title">' + (d.name || "") + ' - ' + (d.violation_type || "") + '</div><span>' + status + '</span></div>' +
					'<div class="saudi-list__meta">' + t("disc_date") + ': ' + (d.incident_date || "") + ' | ' + t("disc_ack") + ': ' + ack + '</div>';
				if (!d.acknowledged_by_employee) {
					html += '<div style="display:flex;gap:8px;width:100%;"><input id="ack-phrase-' + d.name + '" placeholder="' + POLICY_ACK_PHRASE + '" style="flex:1;padding:8px;border:1px solid #e5e7eb;border-radius:8px;"><button class="saudi-btn saudi-btn--primary" style="padding:6px 10px;" onclick="ackDisciplinary(\'' + d.name + '\')">' + t("disc_ack_btn") + '</button></div>' +
						'<textarea id="obj-' + d.name + '" placeholder="' + t("disc_objection_ph") + '" style="width:100%;padding:8px;border:1px solid #e5e7eb;border-radius:8px;"></textarea><button class="saudi-btn" style="padding:6px 10px;" onclick="objDisciplinary(\'' + d.name + '\')">' + t("disc_submit_objection") + '</button>';
				}
				if (d.employee_objection) {
					html += '<div class="saudi-list__meta">' + t("disc_objection") + ': ' + d.employee_objection + '</div>';
				}
				html += '</div>';
			});
			list.innerHTML = html;
		}
	});
};

window.ackDisciplinary = function(name) {
	var inp = document.getElementById("ack-phrase-" + name);
	var consent = inp ? inp.value : "";
	frappe.call({
		method: "saudi_hr.saudi_hr.api.acknowledge_disciplinary_procedure",
		args: { disciplinary_name: name, consent: consent },
		callback: function() { showToast(t("disc_ack_done"), "success"); if (typeof navigate === "function") navigate("disciplinary"); }
	});
};

window.objDisciplinary = function(name) {
	var ta = document.getElementById("obj-" + name);
	var objection = ta ? ta.value : "";
	frappe.call({
		method: "saudi_hr.saudi_hr.api.object_to_disciplinary_procedure",
		args: { disciplinary_name: name, objection: objection },
		callback: function() { showToast(t("disc_objection_done"), "success"); if (typeof navigate === "function") navigate("disciplinary"); }
	});
};


