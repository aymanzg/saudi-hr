import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, nowdate

from saudi_hr.saudi_hr.doctype.saudi_emergency_leave.saudi_emergency_leave import (
	get_emergency_leave_availability,
)
from saudi_hr.saudi_hr.test_support import make_qa_employee
from saudi_hr.saudi_hr.utils import (
	get_annual_leave_balance,
	get_emergency_leave_balance,
	get_emergency_leave_days_taken,
)


class TestSaudiEmergencyLeave(FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.company = frappe.get_all("Company", pluck="name", limit_page_length=1)[0]
		self.employee = make_qa_employee(self.company, f"emergency-{frappe.generate_hash(length=6)}")
		frappe.db.set_value("Employee", self.employee, "date_of_joining", "2020-01-01")
		self.employee_email = frappe.db.get_value("Employee", self.employee, "user_id")

	def _exhaust_annual_leave(self, leave_year=None):
		"""Bring the annual balance to zero the way HR would, so the gate opens."""
		frappe.get_doc(
			{
				"doctype": "Leave Balance Adjustment",
				"employee": self.employee,
				"leave_year": leave_year or frappe.utils.getdate(nowdate()).year,
				"adjustment_days": -100,
				"reason": "QA: annual leave already used",
			}
		).insert(ignore_permissions=True).submit()

	def _insert(self, **kwargs):
		payload = {
			"doctype": "Saudi Emergency Leave",
			"employee": self.employee,
			"from_date": nowdate(),
			"to_date": nowdate(),
			"reason": "Family emergency",
		}
		payload.update(kwargs)
		return frappe.get_doc(payload).insert(ignore_permissions=True)

	def _submit(self, doc):
		"""Submit through a freshly read document.

		The workflow sends an action email, which renders the document through
		printview and leaves ``flags.in_print`` set on that object. Every later
		``save()`` on it is then a silent no-op, so each step re-reads the doc.
		"""
		return frappe.get_doc(doc.doctype, doc.name).submit()

	def test_emergency_leave_is_refused_while_annual_leave_remains(self):
		"""The whole point of the feature: annual leave comes first."""
		self.assertGreater(get_annual_leave_balance(self.employee)["balance"], 0)

		with self.assertRaises(frappe.exceptions.ValidationError) as error:
			self._insert()

		self.assertIn("annual leave available", str(error.exception))

	def test_emergency_leave_is_allowed_once_annual_leave_is_gone(self):
		self._exhaust_annual_leave()

		doc = self._insert(to_date=add_days(nowdate(), 1))

		self.assertEqual(doc.total_days, 2)
		self.assertEqual(doc.entitlement_days, 3)
		self.assertEqual(doc.used_days_before, 0)
		self.assertEqual(doc.available_days, 3)
		self.assertEqual(doc.annual_leave_available, 0)
		self.assertLessEqual(doc.annual_leave_balance_snapshot, 0)

	def test_the_entitlement_is_three_days_per_calendar_year(self):
		balance = get_emergency_leave_balance(self.employee)

		self.assertEqual(balance["entitled"], 3)
		self.assertEqual(balance["available"], 3)
		self.assertEqual(balance["year"], frappe.utils.getdate(nowdate()).year)

	def test_a_request_cannot_exceed_the_three_day_allowance(self):
		self._exhaust_annual_leave()

		with self.assertRaises(frappe.exceptions.ValidationError) as error:
			self._insert(to_date=add_days(nowdate(), 3))

		self.assertIn("per calendar year", str(error.exception))

	def test_three_days_is_the_whole_year(self):
		self._exhaust_annual_leave()
		self._submit(self._insert(to_date=add_days(nowdate(), 2)))

		year = frappe.utils.getdate(nowdate()).year
		self.assertEqual(get_emergency_leave_days_taken(self.employee, year), 3)
		self.assertEqual(get_emergency_leave_balance(self.employee)["available"], 0)

		with self.assertRaises(frappe.exceptions.ValidationError) as error:
			self._insert()
		self.assertIn("per calendar year", str(error.exception))

	def test_only_approved_emergency_leave_consumes_the_quota(self):
		self._exhaust_annual_leave()
		doc = self._insert()

		# a draft request is still a request; it must not burn the allowance
		self.assertEqual(get_emergency_leave_balance(self.employee)["taken"], 0)
		self.assertEqual(get_emergency_leave_balance(self.employee)["available"], 3)

		submitted = self._submit(doc)

		self.assertEqual(submitted.docstatus, 1)
		self.assertEqual(get_emergency_leave_balance(self.employee)["taken"], 1)
		self.assertEqual(get_emergency_leave_balance(self.employee)["available"], 2)

	def test_a_future_request_spends_the_quota_of_the_year_it_falls_in(self):
		"""An emergency absence can be known about in advance; the three days are
		counted against the calendar year the day itself falls in."""
		next_year = str(frappe.utils.getdate(nowdate()).year + 1)
		next_year_start = f"{next_year}-01-01"
		# annual leave is granted again next year, so the gate is opened there too
		self._exhaust_annual_leave(leave_year=int(next_year))

		self._submit(self._insert(from_date=next_year_start, to_date=add_days(next_year_start, 2)))

		with self.assertRaises(frappe.exceptions.ValidationError):
			self._insert(from_date=next_year_start, to_date=next_year_start)

	def test_the_workflow_state_is_the_only_status(self):
		"""One source of truth, so the list view and the workflow cannot disagree."""
		self._exhaust_annual_leave()
		doc = self._insert()

		self.assertEqual(doc.workflow_state, "Draft")
		self.assertNotIn("status", doc.as_dict())

	def test_the_mobile_warning_explains_the_gate(self):
		"""What the form shows before the employee submits anything."""
		frappe.set_user(self.employee_email)
		try:
			blocked = get_emergency_leave_availability()
			self.assertEqual(blocked["blocked_by_annual_leave"], 1)
			self.assertEqual(blocked["annual_leave_available"], 1)
			self.assertEqual(blocked["emergency_available"], 3)
			self.assertGreater(blocked["annual_leave_balance"], 0)
		finally:
			frappe.set_user("Administrator")

		self._exhaust_annual_leave()

		frappe.set_user(self.employee_email)
		try:
			open_gate = get_emergency_leave_availability()
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(open_gate["blocked_by_annual_leave"], 0)
		self.assertEqual(open_gate["annual_leave_available"], 0)

	def test_the_warning_is_scoped_to_the_requesting_employee(self):
		"""The availability helper must not leak another employee's balance."""
		other = make_qa_employee(self.company, f"emergency-other-{frappe.generate_hash(length=6)}")
		frappe.db.set_value("Employee", other, "date_of_joining", "2020-01-01")
		self._exhaust_annual_leave()

		frappe.set_user(self.employee_email)
		try:
			with self.assertRaises(frappe.exceptions.PermissionError):
				get_emergency_leave_availability(employee=other)
		finally:
			frappe.set_user("Administrator")

	def test_the_doctype_enforces_its_own_quota(self):
		"""The controller is the gate, not the caller."""
		self._exhaust_annual_leave()
		self._submit(self._insert())

		# a fourth day for the same employee cannot sneak past validation
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._insert(to_date=add_days(nowdate(), 3))