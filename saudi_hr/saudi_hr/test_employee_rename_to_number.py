from unittest.mock import patch

import frappe
from erpnext.setup.doctype.employee.test_employee import make_employee
from frappe.tests.utils import FrappeTestCase

from saudi_hr.patches import rename_employees_to_employee_number as patch_module
from saudi_hr.scripts import rename_employees_to_employee_number as script


class TestEmployeeRenameToEmployeeNumber(FrappeTestCase):
	"""Covers the plan, the rename itself, and the patch that runs it on migrate.

	Every rename is scoped to the fixture employee and runs without committing,
	so the test rolls back with the fixture and never touches site data.
	"""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.company = frappe.get_all("Company", pluck="name", limit_page_length=1)[0]
		suffix = frappe.generate_hash(length=8).lower()
		self.email = f"saudi.rename.{suffix}@example.com"
		frappe.get_doc(
			{
				"doctype": "User",
				"email": self.email,
				"first_name": f"rename{suffix}",
				"new_password": "N7!xP4@qR9#vT2$k",
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)

	def _new_employee_for(self, email, number=None):
		"""ERPNext's helper reuses the employee of a known user, so each
		employee in a test needs its own user."""
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": email,
					"first_name": email.split("@", 1)[0],
					"new_password": "N7!xP4@qR9#vT2$k",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)
		employee = make_employee(email, company=self.company, employee_number=number)
		self.assertRegex(employee, r"^[A-Za-z].*-[0-9]+$")
		if number:
			self.assertNotEqual(employee, number)
		return employee

	def _new_employee(self, number=None):
		return self._new_employee_for(self.email, number)

	def _free_number(self):
		used = {row for row in frappe.get_all("Employee", pluck="employee_number") if row}
		candidate = 900000
		while str(candidate) in used:
			candidate += 1
		return str(candidate)

	def _rename_only(self, employee):
		return script.apply_renames(commit_each=False, only=[employee])

	def test_plan_renames_only_when_name_differs_from_number(self):
		number = self._free_number()
		employee = self._new_employee(number)

		plan, _total = script.build_plan()
		planned = {row.name: new for row, new in plan["rename"]}
		self.assertEqual(planned.get(employee), number)

	def test_plan_skips_employee_without_a_number(self):
		employee = self._new_employee(None)
		plan, _total = script.build_plan()
		self.assertIn(employee, [row.name for row in plan["skip_no_number"]])
		self.assertNotIn(employee, [row.name for row, _ in plan["rename"]])

	def test_plan_skips_duplicate_numbers(self):
		number = self._free_number()
		first = self._new_employee(number)
		second = self._new_employee_for(self.email.replace("@", ".dup@example.com"), number)

		plan, _total = script.build_plan()
		duplicates = {row.name for row, _number, _all in plan["skip_duplicate"]}
		self.assertIn(first, duplicates)
		self.assertIn(second, duplicates)

	def _user_permission(self, employee):
		"""ERPNext's make_employee can add one itself, so reuse whatever exists."""
		filters = {"user": self.email, "allow": "Employee", "for_value": employee}
		if not frappe.db.exists("User Permission", filters):
			frappe.get_doc(
				{
					"doctype": "User Permission",
					"user": self.email,
					"allow": "Employee",
					"for_value": employee,
					"apply_to_all_doctypes": 1,
				}
			).insert(ignore_permissions=True)
		return filters

	def test_apply_renames_employee_and_carries_linked_records(self):
		number = self._free_number()
		employee = self._new_employee(number)
		# named after the employee, so it exercises the "follow the rename" path too
		profile = frappe.get_doc({"doctype": "Saudi Employee Voice Profile", "employee": employee}).insert(
			ignore_permissions=True
		)
		self._user_permission(employee)

		result = self._rename_only(employee)

		self.assertEqual(result["renamed"], [(employee, number)])
		self.assertFalse(result["failed"], result["failed"])
		self.assertFalse(frappe.db.exists("Employee", employee))
		self.assertTrue(frappe.db.exists("Employee", number))
		# the business field follows the document id
		self.assertEqual(frappe.db.get_value("Employee", number, "employee"), number)
		# a doc named after the employee is renamed with it
		self.assertFalse(frappe.db.exists("Saudi Employee Voice Profile", profile.name))
		self.assertTrue(frappe.db.exists("Saudi Employee Voice Profile", number))
		self.assertEqual(frappe.db.get_value("Saudi Employee Voice Profile", number, "employee"), number)
		# including the reference rename_doc does not handle
		self.assertEqual(frappe.db.count("User Permission", {"for_value": employee}), 0)
		self.assertEqual(frappe.db.count("User Permission", {"user": self.email, "for_value": number}), 1)

	def test_only_leaves_other_employees_untouched(self):
		"""The `only` guard exists so a scoped run cannot sweep in site data."""
		employee = self._new_employee(self._free_number())
		other = self._new_employee_for(self.email.replace("@", ".other@example.com"), "900777")

		result = self._rename_only(employee)

		self.assertEqual(len(result["renamed"]), 1)
		self.assertTrue(frappe.db.exists("Employee", other))
		self.assertNotEqual(frappe.db.get_value("Employee", other, "name"), "900777")

	def test_renaming_the_same_employee_twice_is_a_no_op(self):
		number = self._free_number()
		employee = self._new_employee(number)

		first = self._rename_only(employee)
		second = self._rename_only(employee)

		self.assertEqual(len(first["renamed"]), 1)
		self.assertEqual(second["renamed"], [])
		self.assertTrue(frappe.db.exists("Employee", number))

	def test_patch_skips_work_when_nothing_is_pending(self):
		"""The patch must not call the renamer on an already-correct site."""
		plan = {"rename": [], **{key: [] for key in script.SKIP_BUCKETS}}
		with patch.object(patch_module, "mode", return_value="run"), patch.object(
			patch_module, "build_plan", return_value=(plan, 1)
		), patch.object(patch_module, "apply_renames") as apply_mock:
			patch_module.execute()
		apply_mock.assert_not_called()

	def test_patch_honours_skip_mode(self):
		with patch.object(patch_module, "mode", return_value="skip"), patch.object(
			patch_module, "build_plan"
		) as plan_mock:
			patch_module.execute()
		plan_mock.assert_not_called()

	def test_patch_dry_run_writes_nothing(self):
		number = self._free_number()
		employee = self._new_employee(number)

		with patch.object(patch_module, "mode", return_value="dry-run"):
			patch_module.execute()

		self.assertTrue(frappe.db.exists("Employee", employee))
		self.assertFalse(frappe.db.exists("Employee", number))

	def test_patch_runs_renames_for_real_employees(self):
		number = self._free_number()
		employee = self._new_employee(number)

		with patch.object(patch_module, "mode", return_value="run"), patch.object(
			patch_module, "apply_renames", side_effect=lambda **kw: self._rename_only(employee)
		):
			patch_module.execute()

		self.assertTrue(frappe.db.exists("Employee", number))
		self.assertFalse(frappe.db.exists("Employee", employee))

	def test_patch_logs_error_instead_of_failing_the_deploy(self):
		number = self._free_number()
		employee = self._new_employee(number)

		with patch.object(patch_module, "mode", return_value="run"), patch.object(
			patch_module,
			"apply_renames",
			return_value={
				"renamed": [],
				"failed": [(employee, number, "simulated failure")],
				"followed": [],
				"skipped": {key: [] for key in script.SKIP_BUCKETS},
			},
		), patch.object(patch_module.frappe, "log_error") as log_error:
			patch_module.execute()  # must not raise

		log_error.assert_called_once()
		self.assertIn(number, log_error.call_args.kwargs["message"])

	def test_stale_pattern_covers_every_series_in_use(self):
		pattern = script.stale_pattern()
		self.assertRegex("HR-EMP-00042", pattern)
		self.assertNotRegex("HR-EMP-", pattern)  # the bare series, not an id
		self.assertNotRegex("SAU-CHK-2026-0001", pattern)  # an unrelated series
		self.assertNotRegex("101", pattern)  # an employee number, not an old id

	def test_discovered_prefix_uses_the_whole_series(self):
		# regression: "HR-EMP-00042" must yield the prefix "HR-EMP-", not "HR-"
		self.assertIn("HR-EMP-", script.employee_series_prefixes())
