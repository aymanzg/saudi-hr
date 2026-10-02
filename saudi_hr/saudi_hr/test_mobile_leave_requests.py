"""The mobile leave form builds documents through one API path.

These tests drive the same entry point the phone uses, so a request the form
offers is proven to survive the trip to the database, and to be refused for the
same reason the server would refuse it.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, nowdate

from saudi_hr.saudi_hr import api as api_module
from saudi_hr.saudi_hr.test_support import make_qa_employee
from saudi_hr.saudi_hr.utils import get_annual_leave_balance


class TestMobileLeaveRequests(FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.company = frappe.get_all("Company", pluck="name", limit_page_length=1)[0]
		self.employee = make_qa_employee(self.company, f"leave-{frappe.generate_hash(length=6)}")
		frappe.db.set_value("Employee", self.employee, "date_of_joining", "2020-01-01")
		# tomorrow: emergency leave may be known about in advance, and a punch
		# correction never is
		self.day = add_days(nowdate(), 1)
		self.punched_day = add_days(nowdate(), -1)
		self.employee_email = frappe.db.get_value("Employee", self.employee, "user_id")

	def _exhaust_annual_leave(self):
		frappe.get_doc(
			{
				"doctype": "Leave Balance Adjustment",
				"employee": self.employee,
				"leave_year": frappe.utils.getdate(nowdate()).year,
				"adjustment_days": -100,
				"reason": "QA: annual leave already used",
			}
		).insert(ignore_permissions=True).submit()

	def _punch_in(self, day, time="09:40"):
		frappe.get_doc(
			{
				"doctype": "Saudi Employee Checkin",
				"employee": self.employee,
				"log_type": "IN",
				"time": f"{day} {time}",
				"verification_mode": "gps",
			}
		).insert(ignore_permissions=True)

	def _submit(self, request_type, **kwargs):
		"""The whitelisted entry point, called as the employee who owns the phone.

		The endpoint commits, which would leave this test's fixtures behind on
		the site and leak into suites that pick up whatever employee exists
		first, so the commit is stubbed out here.
		"""
		payload = {"start_date": self.day, "end_date": self.day, "reason": "emergency"}
		payload.update(kwargs)
		frappe.set_user(self.employee_email)
		try:
			with patch.object(api_module.frappe.db, "commit"):
				return api_module.submit_mobile_leave_request(request_type, **payload)
		finally:
			frappe.set_user("Administrator")

	def _punch_correction(self, **payload):
		doc = api_module._build_mobile_leave_doc(
			self.employee,
			api_module._get_employee_profile(self.employee),
			"punch_correction",
			[],
			payload,
		)
		return doc

	def test_the_form_offers_emergency_leave_and_correction(self):
		options = api_module._get_leave_options(self.employee)

		self.assertEqual(options["emergency_leave"]["doctype"], "Saudi Emergency Leave")
		self.assertEqual(options["punch_correction"]["doctype"], "Saudi Punch Correction")
		# what the form shows before it will let anything be submitted
		for key in ("entitled", "taken", "available", "annual_leave_balance", "blocked_by_annual_leave"):
			self.assertIn(key, options["emergency_leave"]["emergency"])

	def test_an_emergency_request_is_refused_while_annual_leave_remains(self):
		"""The rule the employee is told about, enforced where it cannot be skipped."""
		self.assertGreater(get_annual_leave_balance(self.employee)["balance"], 0)

		with self.assertRaises(frappe.ValidationError) as error:
			self._submit("emergency_leave")

		self.assertIn("annual", str(error.exception).lower())
		self.assertFalse(
			frappe.db.exists("Saudi Emergency Leave", {"employee": self.employee}),
			"a refused request must not be left behind",
		)

	def test_an_emergency_request_saves_once_annual_leave_is_gone(self):
		self._exhaust_annual_leave()

		result = self._submit("emergency_leave")

		self.assertEqual(result["doctype"], "Saudi Emergency Leave")
		stored = frappe.db.get_value(
			"Saudi Emergency Leave",
			result["name"],
			["workflow_state", "total_days"],
			as_dict=True,
		)
		self.assertEqual(stored.workflow_state, "Draft")
		self.assertEqual(stored.total_days, 1)

	def test_a_punch_correction_needs_the_corrected_time(self):
		"""Without a time there is nothing to correct to.

		A Time field arrives pre-filled with the current clock on a new
		document, so this has to be refused at the API or the request would
		silently ask to be checked in at right now.
		"""
		self._punch_in(self.punched_day)

		with self.assertRaises(frappe.ValidationError) as error:
			self._submit(
				"punch_correction",
				start_date=self.punched_day,
				reason="the gate was slow",
			)

		self.assertIn("time", str(error.exception).lower())

	def test_a_punch_correction_carries_the_corrected_time(self):
		doc = self._punch_correction(
			start_date=self.punched_day,
			corrected_time="08:05",
			reason="the gate was slow",
		)

		self.assertEqual(doc.doctype, "Saudi Punch Correction")
		self.assertEqual(doc.get("corrected_in_time"), "08:05")
		self.assertEqual(doc.correction_reason, "the gate was slow")

	def test_a_punch_correction_reaches_the_employee_queue(self):
		"""A submitted correction has to show up where the employee looks for it."""
		self._punch_in(self.punched_day)
		self._submit(
			"punch_correction",
			start_date=self.punched_day,
			corrected_time="08:05",
			reason="the gate was slow",
		)
		frappe.set_user(self.employee_email)
		try:
			requests = api_module.get_my_requests()
		finally:
			frappe.set_user("Administrator")

		corrections = [r for r in requests if r["request_type"] == "punch_correction"]
		self.assertEqual(len(corrections), 1, requests)
		self.assertEqual(corrections[0]["from_date"], self.punched_day)
		self.assertEqual(corrections[0]["status_code"], "pending")