no_cache = 1
login_required = True


def get_context(context):
	"""Bootstrap the admin portal.

	The page itself is thin: the shell and the first dashboard numbers are
	rendered here so the page paints with data rather than an empty frame, and
	everything after that comes from admin_api over frappe.call.

	Access is refused here as well as in the API.  The API gate is the real
	boundary, but a user with no admin role should not receive a page shell
	that will only fail its first request.
	"""
	import frappe

	from saudi_hr.saudi_hr.admin_api import (
		ADMIN_PORTAL_ROLES,
		assert_portal_access,
		get_admin_dashboard,
	)

	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=/saudi-admin"
		raise frappe.Redirect

	user_lang = frappe.db.get_value("User", frappe.session.user, "language")
	lang_code = (user_lang or frappe.local.lang or "ar").lower()
	is_english = lang_code.startswith("en")

	context.no_breadcrumbs = True
	context.show_sidebar = False
	context.lang_code = lang_code
	context.text_direction = "ltr" if is_english else "rtl"
	context.title = (
		"HR Administration | Saudi HR" if is_english else "إدارة الموارد البشرية | Saudi HR"
	)
	context.full_name = (
		frappe.db.get_value("User", frappe.session.user, "full_name") or frappe.session.user
	)

	try:
		assert_portal_access()
	except frappe.PermissionError:
		# not an admin: send them to the employee portal rather than a bare error
		frappe.local.flags.redirect_location = (
			"/login?redirect-to=/saudi-admin" if frappe.session.user == "Guest" else "/mobile-attendance"
		)
		raise frappe.Redirect

	context.can_manage_employees = bool(frappe.has_permission("Employee", "create", throw=False))
	context.admin_roles = sorted(ADMIN_PORTAL_ROLES.intersection(frappe.get_roles()))

	# First paint carries real numbers, so the dashboard is never a blank grid.
	# A failure here must not blank the page, since the JS retries on load.
	try:
		context.dashboard = get_admin_dashboard()
	except Exception:
		context.dashboard = {}
