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
		self.punch_out = self._punch("OUT", f"{self.day} 17:30:00")

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

		Submitting is enough here: the workflow moves the request to Completed
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

	def test_the_request_records_the_original_check_out(self):
		doc = self._insert(corrected_out_time="17:45:00")

		self.assertEqual(doc.punch_out, self.punch_out)
		self.assertEqual(_hhmm(doc.original_out_time), "17:30:00")
		self.assertEqual(_hhmm(doc.corrected_out_time), "17:45:00")

	def test_a_draft_request_changes_nothing(self):
		self._insert()

		self.assertEqual(self._punch_time(), "09:40:00")

	def test_approval_moves_the_punch_to_the_corrected_time(self):
		"""What the employee asked for: after approval the check-in is the new time."""
		doc = self._insert()
		approved = self._approve(doc)

		self.assertEqual(approved.workflow_state, "Completed")
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

	def test_approval_moves_the_out_punch_to_the_corrected_time(self):
		doc = self._insert(corrected_out_time="17:45:00")
		approved = self._approve(doc)

		self.assertEqual(approved.applied, 1)
		self.assertEqual(self._punch_time(self.punch_out), "17:45:00")
		# the original is still on the request, so the change is auditable
		self.assertEqual(
			_hhmm(frappe.db.get_value("Saudi Punch Correction", doc.name, "original_out_time")), "17:30:00"
		)

	def test_approval_updates_the_daily_attendance_out_time(self):
		attendance = frappe.get_doc(
			{
				"doctype": "Saudi Daily Attendance",
				"employee": self.employee,
				"attendance_date": self.day,
				"in_time": f"{self.day} 08:05:00",
				"out_time": f"{self.day} 17:30:00",
			}
		).insert(ignore_permissions=True)
		self.assertEqual(attendance.working_hours, 9.42)

		self._approve(self._insert(corrected_out_time="18:15:00"))

		daily = frappe.get_doc("Saudi Daily Attendance", attendance.name)
		self.assertEqual(_hhmm(daily.out_time), "18:15:00")
		# out moved without touching the already-corrected check-in
		self.assertEqual(_hhmm(daily.in_time), "08:05:00")
		self.assertEqual(daily.working_hours, 10.17)

	def test_the_early_exit_minutes_are_recalculated_for_the_out_punch(self):
		"""An out correction that changes punctuality has to change the penalty too."""
		self.assertEqual(
			frappe.db.get_value("Saudi Employee Checkin", self.punch_out, "early_exit_minutes"),
			0,
			"17:30 against a 17:00 shift end is not an early exit",
		)

		self._approve(self._insert(corrected_out_time="16:30:00"))

		self.assertEqual(
			frappe.db.get_value("Saudi Employee Checkin", self.punch_out, "early_exit_minutes"),
			30,
			"16:30 against a 17:00 shift end is 30 minutes early",
		)

	def test_an_out_correction_without_an_out_punch_registers_it(self):
		"""A date with no check-out punch is corrected by registering one: the
		approved request is the documented, auditable equivalent of a punch."""
		frappe.db.delete("Saudi Employee Checkin", self.punch_out)
		doc = self._approve(self._insert(corrected_in_time="", corrected_out_time="17:45:00"))

		created = frappe.db.get_value(
			"Saudi Employee Checkin",
			{"employee": self.employee, "log_type": "OUT"},
			"name",
		)
		self.assertTrue(created)
		self.assertEqual(_hhmm(frappe.db.get_value("Saudi Employee Checkin", created, "time")), "17:45:00")
		self.assertIn(
			doc.name,
			frappe.db.get_value("Saudi Employee Checkin", created, "verification_note"),
			"the audit trail says this punch was registered from the request",
		)
		# the registered check-out surfaces as a complete day
		daily_name = frappe.db.get_value(
			"Saudi Daily Attendance", {"employee": self.employee, "attendance_date": self.day}, "name"
		)
		self.assertTrue(daily_name)
		self.assertEqual(
			_hhmm(frappe.db.get_value("Saudi Daily Attendance", daily_name, "out_time")), "17:45:00"
		)

	def test_a_request_must_move_a_punch(self):
		with self.assertRaises(frappe.exceptions.ValidationError) as error:
			self._insert(corrected_in_time="", corrected_out_time="")

		self.assertIn("corrected", str(error.exception).lower())

	def test_a_correction_is_applied_only_once(self):
		self._approve(self._insert())

		# running the apply path again on the same request must do nothing
		name = frappe.get_all("Saudi Punch Correction", filters={"employee": self.employee}, pluck="name")[0]
		frappe.get_doc("Saudi Punch Correction", name)._apply_correction_if_approved()

		self.assertEqual(self._punch_time(), "08:05:00")

	def test_a_day_with_no_check_in_punch_is_registered(self):
		"""No punch that day is not a refusal: approving the request registers the
		forgotten check-in, tagged with the request for the audit trail."""
		day = add_days(self.day, -3)
		doc = self._insert(attendance_date=day)
		self.assertIsNone(doc.punch)
		self.assertIsNone(doc.original_in_time)

		approved = self._approve(doc)

		created = frappe.db.get_value(
			"Saudi Employee Checkin",
			{
				"employee": self.employee,
				"log_type": "IN",
				"time": ["between", [f"{day} 00:00:00", f"{day} 23:59:59"]],
			},
			"name",
		)
		self.assertTrue(created)
		self.assertEqual(_hhmm(frappe.db.get_value("Saudi Employee Checkin", created, "time")), "08:05:00")
		self.assertIn(
			approved.name,
			frappe.db.get_value("Saudi Employee Checkin", created, "verification_note"),
			"the audit trail says this punch was registered from the request",
		)
		# the registered check-in surfaces as a day in the reports
		daily_name = frappe.db.get_value(
			"Saudi Daily Attendance", {"employee": self.employee, "attendance_date": day}, "name"
		)
		self.assertTrue(daily_name)
		self.assertEqual(
			_hhmm(frappe.db.get_value("Saudi Daily Attendance", daily_name, "in_time")), "08:05:00"
		)
		self.assertTrue(frappe.db.get_value("Saudi Punch Correction", doc.name, "created_daily_attendance"))
		self.assertEqual(frappe.db.get_value("Saudi Punch Correction", doc.name, "daily_attendance"), daily_name)

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

	def test_a_later_approval_supersedes_an_applied_correction(self):
		"""A request filed before an older one took effect must still be
		approvable: approving it cancels the older correction and takes over, so
		the day ends with exactly one correction in force."""
		first = self._insert(corrected_in_time="08:05:00")
		second = self._insert(corrected_in_time="08:30:00")
		self.assertEqual(first.applied, 0)
		self.assertEqual(second.applied, 0)

		self._approve(first)
		self.assertEqual(self._punch_time(), "08:05:00")

		# approving the second is no longer refused, and it wins
		self._approve(second)
		self.assertEqual(self._punch_time(), "08:30:00")
		self.assertEqual(
			frappe.db.get_value("Saudi Punch Correction", first.name, "docstatus"),
			2,
			"the superseded correction is cancelled",
		)
		in_force = frappe.get_all(
			"Saudi Punch Correction",
			filters={
				"employee": self.employee,
				"attendance_date": self.day,
				"applied": 1,
				"docstatus": 1,
			},
			pluck="name",
		)
		self.assertEqual(in_force, [second.name], "only one correction is in force")
		# the original on the winning request is the true one, read after the
		# superseded correction put its punch back
		self.assertEqual(
			_hhmm(frappe.db.get_value("Saudi Punch Correction", second.name, "original_in_time")),
			"09:40:00",
		)

	def test_a_future_day_cannot_be_corrected(self):
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._insert(attendance_date=add_days(nowdate(), 2))

	def test_cancelling_the_request_puts_the_punch_back(self):
		doc = self._approve(self._insert())
		self.assertEqual(self._punch_time(), "08:05:00")

		frappe.get_doc(doc.doctype, doc.name).cancel()

		self.assertEqual(self._punch_time(), "09:40:00")

	def test_cancelling_a_registration_removes_the_created_punch_and_day(self):
		"""Reverting a registration is a true revert: the created check-in and the
		day's attendance row it surfaced go back to not existing."""
		day = add_days(self.day, -3)
		doc = self._approve(self._insert(attendance_date=day))
		created_in = frappe.db.get_value(
			"Saudi Employee Checkin",
			{
				"employee": self.employee,
				"log_type": "IN",
				"time": ["between", [f"{day} 00:00:00", f"{day} 23:59:59"]],
			},
			"name",
		)
		daily_name = frappe.db.get_value(
			"Saudi Daily Attendance", {"employee": self.employee, "attendance_date": day}, "name"
		)
		self.assertTrue(created_in)
		self.assertTrue(daily_name)

		frappe.get_doc(doc.doctype, doc.name).cancel()

		self.assertFalse(
			frappe.db.exists("Saudi Employee Checkin", created_in),
			"the registered check-in is deleted on cancel",
		)
		self.assertFalse(
			frappe.db.exists("Saudi Daily Attendance", daily_name),
			"the day's attendance row created by the request is deleted on cancel",
		)

	def test_the_form_context_shows_the_current_check_in_and_check_out(self):
		"""The form shows both punches it would correct rather than asking for trust."""
		frappe.set_user(self.employee_email)
		try:
			context = get_punch_correction_context(attendance_date=self.day)
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(context["correctable"], 1)
		self.assertEqual(context["punch"], self.punch)
		self.assertEqual(_hhmm(context["current_in_time"]), "09:40:00")
		self.assertEqual(context["has_out_punch"], 1)
		self.assertEqual(context["punch_out"], self.punch_out)
		self.assertEqual(_hhmm(context["current_out_time"]), "17:30:00")
		self.assertEqual(context["future_date"], 0)

	def test_the_form_context_reports_a_day_with_no_punch(self):
		frappe.set_user(self.employee_email)
		try:
			context = get_punch_correction_context(attendance_date=add_days(self.day, -5))
			future = get_punch_correction_context(attendance_date=add_days(nowdate(), 3))
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(context["correctable"], 1)
		self.assertEqual(context["has_in_punch"], 0)
		self.assertIsNone(context["current_in_time"])
		self.assertEqual(future["future_date"], 1)
		self.assertEqual(future["correctable"], 0)

	def test_the_form_context_is_scoped_to_the_employee(self):
		other = make_qa_employee(self.company, f"punch-other-{frappe.generate_hash(length=6)}")
		frappe.db.set_value("Employee", other, "date_of_joining", "2020-01-01")

		frappe.set_user(self.employee_email)
		try:
			with self.assertRaises(frappe.exceptions.PermissionError):
				get_punch_correction_context(employee=other, attendance_date=self.day)
		finally:
			frappe.set_user("Administrator")