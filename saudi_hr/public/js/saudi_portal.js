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
		reason_label: "مبرر الطلب",
		annual_balance: "رصيد الإجازة السنوية",
		emergency_balance: "رصيد الإجازة الطارئة",
		emergency_remaining: "المتاح من الإجازة الطارئة",
		emergency_gate_warning: "لا يمكنك طلب إجازة طارئة لوجود رصيد في الإجازة السنوية، استخدم رصيدك السنوي أولاً.",
		emergency_quota_warning: "استنفدت رصيد الإجازة الطارئة لهذا العام.",
		emergency_days_short: "عدد الأيام المطلوبة يتجاوز الرصيد المتاح من الإجازة الطارئة.",
		current_checkin: "وقت الحضور المسجل",
		no_checkin_found: "لا توجد بصمة حضور في هذا التاريخ، لا يمكن التصحيح.",
		corrected_time_label: "وقت الحضور الصحيح",
		corrected_time_required: "الرجاء تحديد وقت الحضور الصحيح",
		future_date_not_allowed: "لا يمكن التصحيح لتاريخ لم يحدث بعد",
		half_day: "نصف يوم",
		attachments_label: "مرفقات الطلب",
		choose_subtype: "اختر النوع...",
		subtype_required: "الرجاء اختيار نوع الإجازة",
		start_date_required: "الرجاء تحديد تاريخ بداية الإجازة",
		day_unit: "يوم",
		loading: "جاري التحميل...",
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
		admin_employee_saved: "تم حفظ بيانات الموظف بنجاح",
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
		admin_action_done: "تم تنفيذ الإجراء بنجاح",
		admin_action_failed: "تعذر تنفيذ الإجراء",
		admin_restricted_row: "لا تملك صلاحية فتح هذا الطلب",
		admin_submitting: "جارٍ التنفيذ...",
		admin_employee_details: "بيانات الموظف",
		admin_employee_requests: "طلبات الموظف",
		admin_employee_requests_truncated: "يعرض أحدث الطلبات فقط",
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

		admin_state_draft: "مسودة",
		admin_state_pending: "بانتظار الموافقة",
		admin_state_approved: "معتمدة",
		admin_state_rejected: "مرفوضة",
		admin_state_cancelled: "ملغاة",
		admin_state_unknown: "غير محدد",
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
		admin_employees_restricted: "لا تملك صلاحية عرض قائمة الموظفين",
		admin_confirm_action: "هل تريد تنفيذ \"{action}\" على الطلب {name}؟",
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
		reason_label: "Reason",
		annual_balance: "Annual Leave Balance",
		emergency_balance: "Emergency Leave Balance",
		emergency_remaining: "Emergency leave remaining",
		emergency_gate_warning: "You cannot take emergency leave while annual leave remains. Please use your annual leave first.",
		emergency_quota_warning: "You have used all of this year's emergency leave.",
		emergency_days_short: "The days requested are more than the emergency leave you have left.",
		current_checkin: "Recorded check-in",
		no_checkin_found: "There is no check-in punch on that date, so it cannot be corrected.",
		corrected_time_label: "Correct check-in time",
		corrected_time_required: "Please choose the corrected check-in time",
		future_date_not_allowed: "You cannot correct a day that has not happened yet",
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
		admin_employee_saved: "Employee saved successfully",
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
		admin_action_done: "Action completed",
		admin_action_failed: "The action could not be completed",
		admin_restricted_row: "You cannot open this request",
		admin_submitting: "Working...",
		admin_employee_details: "Employee Details",
		admin_employee_requests: "Employee Requests",
		admin_employee_requests_truncated: "Showing the most recent requests only",
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

		admin_state_draft: "Draft",
		admin_state_pending: "Pending Approval",
		admin_state_approved: "Approved",
		admin_state_rejected: "Rejected",
		admin_state_cancelled: "Cancelled",
		admin_state_unknown: "Unknown",
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
		admin_employees_restricted: "You do not have permission to view the employee list",
		admin_confirm_action: "Apply \"{action}\" to request {name}?",
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
		} else {
			el.textContent = v;
		}
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
function logoutUser() {
	if (!confirm(t("logout_confirm"))) return;
	try { localStorage.removeItem(SAUDI_PANEL_STORE_KEY); } catch(e) {}
	window.location.href = "/api/method/logout";
}
