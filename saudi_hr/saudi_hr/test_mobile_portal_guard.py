import frappe
from frappe.tests.utils import FrappeTestCase

from saudi_hr.saudi_hr import mobile_portal_guard


class TestMobilePortalGuard(FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")

	def _make_user(self, roles):
		suffix = frappe.generate_hash(length=8).lower()
		email = f"saudi.mobile.{suffix}@example.com"
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": "mobileguard",
				"new_password": "N7!xP4@qR9#vT2$k",
				"send_welcome_email": 0,
				"roles": [{"doctype": "Has Role", "role": role} for role in roles],
			}
		).insert(ignore_permissions=True)
		return email

	def _make_forced_user(self):
		from saudi_hr.install import ensure_mobile_portal_role

		ensure_mobile_portal_role()
		return self._make_user([mobile_portal_guard.FORCED_ROLE])

	def test_desk_path_detection(self):
		self.assertTrue(mobile_portal_guard._is_desk_path("app"))
		self.assertTrue(mobile_portal_guard._is_desk_path("/app/employee/EMP-1"))
		self.assertTrue(mobile_portal_guard._is_desk_path("apps"))
		self.assertTrue(mobile_portal_guard._is_desk_path("desk/foo"))
		self.assertFalse(mobile_portal_guard._is_desk_path("application"))
		self.assertFalse(mobile_portal_guard._is_desk_path("mobile-attendance"))
		self.assertFalse(mobile_portal_guard._is_desk_path(""))

	def test_forced_user_is_redirected_off_the_desk(self):
		frappe.set_user(self._make_forced_user())

		with self.assertRaises(frappe.Redirect):
			mobile_portal_guard.resolve("app")

		self.assertEqual(frappe.flags.redirect_location, mobile_portal_guard.MOBILE_PORTAL_ROUTE)

	def test_forced_user_is_redirected_from_desk_subpaths(self):
		frappe.set_user(self._make_forced_user())

		with self.assertRaises(frappe.Redirect):
			mobile_portal_guard.resolve("app/employee/EMP-1")

		self.assertEqual(frappe.flags.redirect_location, mobile_portal_guard.MOBILE_PORTAL_ROUTE)

	def test_forced_user_can_still_open_the_portal(self):
		frappe.set_user(self._make_forced_user())

		self.assertEqual(mobile_portal_guard.resolve("mobile-attendance"), "mobile-attendance")

	def test_users_without_the_role_reach_the_desk(self):
		frappe.set_user(self._make_user(["Employee"]))

		self.assertEqual(mobile_portal_guard.resolve("app"), "app")

	def test_guest_is_never_forced(self):
		frappe.set_user("Guest")

		self.assertFalse(mobile_portal_guard.is_forced_user())

	def test_role_only_matches_the_dedicated_role(self):
		frappe.set_user(self._make_user(["Employee"]))

		self.assertFalse(mobile_portal_guard.is_forced_user())


class TestMobilePortalRole(FrappeTestCase):
	def test_ensure_mobile_portal_role_creates_desk_less_role(self):
		from saudi_hr.install import ensure_mobile_portal_role

		ensure_mobile_portal_role()

		self.assertTrue(frappe.db.exists("Role", mobile_portal_guard.FORCED_ROLE))
		self.assertEqual(frappe.db.get_value("Role", mobile_portal_guard.FORCED_ROLE, "desk_access"), 0)
