no_cache = 1
login_required = True


def get_context(context):
	import frappe
	from saudi_hr.saudi_hr.enterprise_operations import get_self_service_portal

	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=/mobile-attendance"
		raise frappe.Redirect

	user_lang = frappe.db.get_value("User", frappe.session.user, "language")
	lang_code = (user_lang or frappe.local.lang or "ar").lower()
	is_english = lang_code.startswith("en")
	context.title = "Mobile Self Service | Saudi HR" if is_english else "بوابة الموظف الذاتية | Saudi HR"
	context.full_name = frappe.db.get_value("User", frappe.session.user, "full_name") or frappe.session.user
	context.no_breadcrumbs = True
	context.show_sidebar = False
	context.lang_code = lang_code
	context.text_direction = "ltr" if is_english else "rtl"

	try:
		context.portal_data = get_self_service_portal()
	except Exception:
		context.portal_data = {}
