import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, get_datetime, nowdate

from saudi_hr.saudi_hr.attendance_policy import (
	calculate_attendance_variance,
	resolve_mobile_attendance_policy,
)
from saudi_hr.saudi_hr.doctype.saudi_punch_correction.saudi_punch_correction import (
	get_punch_correction_context,
)
from saudi_hr.saudi_hr.test_support import make_qa_employee


def _hhmm(value):
	"""Clock values come back from the database as strings, times, or timedeltas."""
	if isinstance(value, str):
		return value[:8]
	if hasattr(value, "hour"):
		return value.strftime("%H:%M:%S")
	return f"{int(value.total_seconds() // 3600):02}:{int(value.total_seconds() % 3600 // 60):02}:00"


class TestSaudiPunchCorrection(FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.company = frappe.get_all("Company", pluck="name", limit_page_length=1)[0]
		self.employee = make_qa_employee(self.company, f"punch-{frappe.generate_hash(length=6)}")
		frappe.db.set_value("Employee", self.employee, "date_of_joining", "2020-01-01")
		self.employee_email = frappe.db.get_value("Employee", self.employee, "user_id")
		self.day = add_days(nowdate(), -1)
		self._assign_nine_o_morning_shift()
		self.punch = self._punch("IN", f"{self.day} 09:40:00")
		self._punch("OUT", f"{self.day} 17:30:00")

	def _assign_nine_o_morning_shift(self):
		"""A submitted shift so 09:40 is genuinely late and 08:05 is not."""
		shift = frappe.get_doc(
			{
				"doctype": "Saudi Shift Type",
				"shift_name": f"Punch QA {frappe.generate_hash(length=6)}",
				"start_time": "09:00:00",
				"end_time": "17:00:00",
				"enable_late_entry_marking": 1,
			}
		).insert(ignore_permissions=True)
		assignment = frappe.get_doc(
			{
				"doctype": "Saudi Shift Assignment",
				"employee": self.employee,
				"shift_type": shift.name,
				"status": "Active",
				"start_date": "2020-01-01",
			}
		)
		assignment.insert(ignore_permissions=True)
		assignment.submit()

	def _punch(self, log_type, time):
		"""Record a punch the way the punch API does, penalty included."""
		variance = calculate_attendance_variance(
			log_type, get_datetime(time), resolve_mobile_attendance_policy(self.employee, self.day)
		)
		doc = frappe.get_doc(
			{
				"doctype": "Saudi Employee Checkin",
				"employee": self.employee,
				"log_type": log_type,
				"time": time,
				"verification_mode": "gps",
				"late_minutes": variance["late_minutes"],
				"early_exit_minutes": variance["early_exit_minutes"],
			}
		).insert(ignore_permissions=True)
		return doc.name

	def _request(self, **kwargs):
		payload = {
			"doctype": "Saudi Punch Correction",
			"employee": self.employee,
			"attendance_date": self.day,
			"corrected_in_time": "08:05:00",
			"correction_reason": "I forgot to punch in at the main gate",
		}
		payload.update(kwargs)
		return frappe.get_doc(payload)

	def _insert(self, **kwargs):
		return self._request(**kwargs).insert(ignore_permissions=True)

	def _approve(self, doc):
		"""Approve through the workflow, the way an approver would.

		Submitting is enough here: the workflow moves the request to Approved
		because this user may perform every transition. A plain save that set
		``workflow_state`` directly is refused by design.
		"""
		return frappe.get_doc(doc.doctype, doc.name).submit()

	def _punch_time(self, punch=None):
		return _hhmm(frappe.db.get_value("Saudi Employee Checkin", punch or self.punch, "time"))

	def test_the_request_records_the_original_check_in(self):
		doc = self._insert()

		self.assertEqual(doc.punch, self.punch)
		self.assertEqual(_hhmm(doc.original_in_time), "09:40:00")
		self.assertEqual(_hhmm(doc.corrected_in_time), "08:05:00")
		self.assertEqual(doc.applied, 0)

	def test_a_draft_request_changes_nothing(self):
		self._insert()

		self.assertEqual(self._punch_time(), "09:40:00")

	def test_approval_moves_the_punch_to_the_corrected_time(self):
		"""What the employee asked for: after approval the check-in is the new time."""
		doc = self._insert()
		approved = self._approve(doc)

		self.assertEqual(approved.workflow_state, "Approved")
		self.assertEqual(approved.applied, 1)
		self.assertTrue(approved.applied_on)
		self.assertEqual(self._punch_time(), "08:05:00")
		# the original is still on the request, so the change is auditable
		self.assertEqual(
			_hhmm(frappe.db.get_value("Saudi Punch Correction", doc.name, "original_in_time")), "09:40:00"
		)

	def test_approval_updates_the_daily_attendance_record(self):
		attendance = frappe.get_doc(
			{
				"doctype": "Saudi Daily Attendance",
				"employee": self.employee,
				"attendance_date": self.day,
				"in_time": f"{self.day} 09:40:00",
				"out_time": f"{self.day} 17:30:00",
			}
		).insert(ignore_permissions=True)
		self.assertEqual(attendance.working_hours, 7.83)

		self._approve(self._insert())

		daily = frappe.get_doc("Saudi Daily Attendance", attendance.name)
		self.assertEqual(_hhmm(daily.in_time), "08:05:00")
		# working hours are derived on save, so they follow the corrected check-in
		self.assertEqual(daily.working_hours, 9.42)

	def test_a_correction_is_applied_only_once(self):
		self._approve(self._insert())

		# running the apply path again on the same request must do nothing
		name = frappe.get_all("Saudi Punch Correction", filters={"employee": self.employee}, pluck="name")[0]
		frappe.get_doc("Saudi Punch Correction", name)._apply_correction_if_approved()

		self.assertEqual(self._punch_time(), "08:05:00")

	def test_a_day_with_no_check_in_punch_cannot_be_corrected(self):
		"""Correcting a punch that does not exist would fabricate attendance."""
		with self.assertRaises(frappe.exceptions.ValidationError) as error:
			self._insert(attendance_date=add_days(self.day, -3))

		self.assertIn("No check-in punch was found", str(error.exception))

	def test_the_first_check_in_of_the_day_is_the_one_corrected(self):
		second_in = self._punch("IN", f"{self.day} 10:15:00")

		doc = self._insert()
		self.assertEqual(doc.punch, self.punch)

		self._approve(doc)

		self.assertEqual(self._punch_time(), "08:05:00")
		self.assertEqual(self._punch_time(second_in), "10:15:00")

	def test_the_original_late_minutes_are_recalculated(self):
		"""A correction that changes punctuality has to change the penalty too."""
		self.assertEqual(
			frappe.db.get_value("Saudi Employee Checkin", self.punch, "late_minutes"),
			40,
			"09:40 against a 09:00 shift start is 40 minutes late",
		)

		self._approve(self._insert())

		self.assertEqual(
			frappe.db.get_value("Saudi Employee Checkin", self.punch, "late_minutes"),
			0,
			"08:05 against a 09:00 shift start is not late",
		)

	def test_cancelling_puts_the_penalty_back_as_well_as_the_time(self):
		"""Reverting has to be a true revert, not a time change with a stale penalty."""
		self._approve(self._insert())

		name = frappe.get_all("Saudi Punch Correction", filters={"employee": self.employee}, pluck="name")[0]
		frappe.get_doc("Saudi Punch Correction", name).cancel()

		self.assertEqual(self._punch_time(), "09:40:00")
		self.assertEqual(
			frappe.db.get_value("Saudi Employee Checkin", self.punch, "late_minutes"),
			40,
			"the original 40 minutes of lateness are back",
		)

	def test_a_day_can_only_be_corrected_once(self):
		self._approve(self._insert())

		with self.assertRaises(frappe.exceptions.ValidationError) as error:
			self._insert(corrected_in_time="07:30:00")

		self.assertIn("already corrected", str(error.exception))
		self.assertEqual(self._punch_time(), "08:05:00")

	def test_a_future_day_cannot_be_corrected(self):
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._insert(attendance_date=add_days(nowdate(), 2))

	def test_cancelling_the_request_puts_the_punch_back(self):
		doc = self._approve(self._insert())
		self.assertEqual(self._punch_time(), "08:05:00")

		frappe.get_doc(doc.doctype, doc.name).cancel()

		self.assertEqual(self._punch_time(), "09:40:00")

	def test_the_form_context_shows_the_current_check_in(self):
		"""The form shows the punch it would correct rather than asking for trust."""
		frappe.set_user(self.employee_email)
		try:
			context = get_punch_correction_context(attendance_date=self.day)
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(context["correctable"], 1)
		self.assertEqual(context["punch"], self.punch)
		self.assertEqual(_hhmm(context["current_in_time"]), "09:40:00")
		self.assertEqual(context["future_date"], 0)

	def test_the_form_context_reports_a_day_with_no_punch(self):
		frappe.set_user(self.employee_email)
		try:
			context = get_punch_correction_context(attendance_date=add_days(self.day, -5))
			future = get_punch_correction_context(attendance_date=add_days(nowdate(), 3))
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(context["correctable"], 0)
		self.assertIsNone(context["current_in_time"])
		self.assertEqual(future["future_date"], 1)

	def test_the_form_context_is_scoped_to_the_employee(self):
		other = make_qa_employee(self.company, f"punch-other-{frappe.generate_hash(length=6)}")
		frappe.db.set_value("Employee", other, "date_of_joining", "2020-01-01")

		frappe.set_user(self.employee_email)
		try:
			with self.assertRaises(frappe.exceptions.PermissionError):
				get_punch_correction_context(employee=other, attendance_date=self.day)
		finally:
			frappe.set_user("Administrator")