"""Keep selected users on the mobile HTML portal.

Users holding the ``Mobile Portal Only`` role should never see the Frappe Desk.
``website_path_resolver`` runs while a website page is resolved; raising
``frappe.Redirect`` there is handled by ``frappe.website.serve.get_response`` and
becomes a redirect response. API and static asset requests do not go through the
path resolver, so they are unaffected.
"""

import frappe
import werkzeug.routing.exceptions

FORCED_ROLE = "Mobile Portal Only"
DESK_PATH_ROOTS = {"app", "apps", "desk"}
MOBILE_PORTAL_ROUTE = "/mobile-attendance"


def is_forced_user(user=None):
	"""True when the user must stay on the mobile HTML portal."""
	try:
		user = user or frappe.session.user
	except Exception:
		return False

	if not user or user in ("Guest", "Administrator"):
		return False

	return FORCED_ROLE in frappe.get_roles(user)


def _is_desk_path(path):
	root = (path or "").strip("/ ").split("/", 1)[0].lower()
	return root in DESK_PATH_ROOTS


def resolve(path):
	"""``website_path_resolver`` entry: bounce forced users off the Desk."""
	if is_forced_user() and _is_desk_path(path):
		frappe.flags.redirect_location = MOBILE_PORTAL_ROUTE
		raise frappe.Redirect

	# Not a forced desk request: hand back to Frappe's standard resolution.
	from frappe.website.path_resolver import resolve_path

	try:
		return resolve_path(path)
	except werkzeug.routing.exceptions.RequestRedirect as exc:
		frappe.flags.redirect_location = exc.new_url
		raise frappe.Redirect(exc.code) from exc
