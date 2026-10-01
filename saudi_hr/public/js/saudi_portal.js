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
		reason_label: "مبرر الطلب",
		annual_balance: "رصيد الإجازة السنوية",
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
	},
	en: {
		hero_greeting: "Hello, ",
		hero_subtitle: "Wishing you a productive and successful day",
		leave_balance: "Leave Balance",
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
		reason_label: "Reason",
		annual_balance: "Annual Leave Balance",
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
	if (err && err._server_messages && err._server_messages.length) {
		var raw = (err._server_messages[0] + "").replace(/\\?"/g, "").replace(/<[^>]+>/g, "").trim();
		if (raw) return raw;
	}
	return fallback;
}

function showSessionBanner() {
	var el = document.getElementById("session-banner");
	if (el) el.style.display = "flex";
}

function logoutUser() {
	if (!confirm(t("logout_confirm"))) return;
	try { localStorage.removeItem(SAUDI_PANEL_STORE_KEY); } catch(e) {}
	window.location.href = "/api/method/logout";
}
