from unittest.mock import patch

import frappe
from erpnext.setup.doctype.employee.test_employee import make_employee
from frappe.tests.utils import FrappeTestCase

from saudi_hr.install import remove_mismatched_company_user_permissions
from saudi_hr.patches import remove_mismatched_company_user_permissions as patch_module


class TestInstallCompanyUserPermissions(FrappeTestCase):
	"""Covers removal of Company User Permissions that contradict the user's own
	Employee company, and the patch that runs it on migrate.

	Every record is created inside the test transaction, so the deletions roll
	back with the fixture and never touch site data.
	"""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		companies = frappe.get_all("Company", pluck="name", limit=2)
		self.company = companies[0]
		self.other_company = companies[1] if len(companies) > 1 else None
		suffix = frappe.generate_hash(length=8).lower()
		self.user = f"saudi.companyperm.{suffix}@example.com"

	def _make_user(self):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": self.user,
				"first_name": "companyperm",
				"new_password": "N7!xP4@qR9#vT2$k",
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)
		return self.user

	def _company_permission(self, user, company):
		# ERPNext's Employee insert already creates a matching Company permission,
		# so reuse it when present instead of tripping the duplicate check.
		existing = frappe.db.exists(
			"User Permission", {"user": user, "allow": "Company", "for_value": company}
		)
		if existing:
			return existing

		return frappe.get_doc(
			{
				"doctype": "User Permission",
				"user": user,
				"allow": "Company",
				"for_value": company,
				"apply_to_all_doctypes": 1,
			}
		).insert(ignore_permissions=True).name

	def _require_two_companies(self):
		if not self.other_company:
			self.skipTest("needs at least two companies to express a mismatch")

	def test_removes_mismatched_company_permission(self):
		self._require_two_companies()
		self._make_user()
		make_employee(self.user, company=self.company)
		permission = self._company_permission(self.user, self.other_company)

		remove_mismatched_company_user_permissions()

		self.assertFalse(frappe.db.exists("User Permission", permission))

	def test_keeps_matching_company_permission(self):
		self._make_user()
		make_employee(self.user, company=self.company)
		permission = self._company_permission(self.user, self.company)

		remove_mismatched_company_user_permissions()

		self.assertTrue(frappe.db.exists("User Permission", permission))

	def test_leaves_users_without_employee_untouched(self):
		self._require_two_companies()
		self._make_user()
		permission = self._company_permission(self.user, self.other_company)

		remove_mismatched_company_user_permissions()

		self.assertTrue(frappe.db.exists("User Permission", permission))

	def test_removal_is_idempotent(self):
		self._require_two_companies()
		self._make_user()
		make_employee(self.user, company=self.company)
		permission = self._company_permission(self.user, self.other_company)

		remove_mismatched_company_user_permissions()
		remove_mismatched_company_user_permissions()

		self.assertFalse(frappe.db.exists("User Permission", permission))

	def test_patch_invokes_the_sync(self):
		with patch.object(
			patch_module, "remove_mismatched_company_user_permissions", return_value=3
		) as sync_mock:
			patch_module.execute()

		sync_mock.assert_called_once()
