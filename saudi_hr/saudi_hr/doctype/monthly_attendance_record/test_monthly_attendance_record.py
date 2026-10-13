import frappe
from frappe.tests.utils import FrappeTestCase

from saudi_hr.saudi_hr.doctype.monthly_attendance_record.monthly_attendance_record import (
	get_monthly_days,
)
from saudi_hr.saudi_hr.test_support import make_qa_employee


class TestMonthlyAttendanceRecord(FrappeTestCase):
	"""Auto-Fill has to describe the attendance that exists, not a calendar.

	The days are chosen inside a past month (June 2026) so a working day with no
	record can only be an absence, and a future month to prove the generated
	rows never claim Present for a day that has not happened.
	"""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.company = frappe.get_all("Company", pluck="name", limit_page_length=1)[0]
		self.employee = make_qa_employee(self.company, "monthly-attendance")
		frappe.db.set_value("Employee", self.employee, "date_of_joining", "2020-01-01")
		# a deterministic weekend fallback unless a test assigns its own list
		frappe.db.set_value("Company", self.company, "default_holiday_list", None)
		frappe.db.set_value("Employee", self.employee, "holiday_list", None)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		super().tearDown()

	def _rows(self, month="June / يونيو", year=2026, employee=None):
		rows = get_monthly_days(month, year, self.employee if employee is None else employee)
		return {row["attendance_date"]: row for row in rows}

	def _make_attendance(
		self,
		day,
		status="Present / حاضر",
		in_time="08:15:00",
		out_time="16:30:00",
		hours=8.25,
		late_minutes=0,
	):
		doc = {
			"doctype": "Saudi Daily Attendance",
			"employee": self.employee,
			"attendance_date": day,
			"status": status,
			"in_time": f"{day} {in_time}",
			"out_time": f"{day} {out_time}",
			"working_hours": hours,
		}
		if late_minutes:
			doc.update({"late_entry": 1, "late_minutes": late_minutes})
		return frappe.get_doc(doc).insert(ignore_permissions=True).name

	def _make_checkin(self, day, at="09:15:00", log_type="IN"):
		return (
			frappe.get_doc(
				{
					"doctype": "Saudi Employee Checkin",
					"employee": self.employee,
					"log_type": log_type,
					"time": f"{day} {at}",
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _holiday_list(self, rows):
		"""A 2026 Holiday List with the given (date, description, weekly_off)."""
		doc = frappe.get_doc(
			{
				"doctype": "Holiday List",
				"holiday_list_name": f"QA Monthly Holidays {frappe.generate_hash(length=8)}",
				"from_date": "2026-01-01",
				"to_date": "2026-12-31",
				"holidays": [
					{"holiday_date": day, "description": desc, "weekly_off": off}
					for day, desc, off in rows
				],
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("Employee", self.employee, "holiday_list", doc.name)
		return doc.name

	def _approved_leave(self, start, end):
		doc = frappe.get_doc(
			{
				"doctype": "Saudi Annual Leave",
				"employee": self.employee,
				"company": self.company,
				"leave_start_date": start,
				"leave_end_date": end,
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("Saudi Annual Leave", doc.name, "workflow_state", "Approved")
		return doc.name

	def test_a_present_record_reads_as_present_with_its_times(self):
		self._make_attendance("2026-06-01")

		row = self._rows()["2026-06-01"]

		self.assertEqual(row["status"], "Present / حاضر")
		self.assertEqual(row["day_type"], "Working Day / يوم عمل")
		self.assertEqual(row["time_in"], "08:15")
		self.assertEqual(row["time_out"], "16:30")
		self.assertEqual(row["hours_worked"], 8.25)
		self.assertEqual(row["overtime_hours"], 0.25)

	def test_a_present_record_moved_after_the_shift_reads_as_late(self):
		self._make_attendance("2026-06-02", late_minutes=15)

		row = self._rows()["2026-06-02"]

		self.assertEqual(row["status"], "Late / متأخر")
		self.assertEqual(row["late_minutes"], 15)

	def test_a_past_working_day_with_no_record_reads_as_absent(self):
		row = self._rows()["2026-06-04"]  # a Thursday, nothing on record

		self.assertEqual(row["status"], "Absent / غائب")
		self.assertEqual(row["day_type"], "Working Day / يوم عمل")

	def test_an_approved_leave_day_reads_as_leave(self):
		self._approved_leave("2026-06-02", "2026-06-02")

		row = self._rows()["2026-06-02"]

		self.assertEqual(row["status"], "Leave / إجازة")
		self.assertEqual(row["day_type"], "Annual Leave / إجازة سنوية")

	def test_a_named_holiday_reads_as_a_public_holiday(self):
		self._holiday_list([("2026-06-03", "Founding Day / يوم التأسيس", 0)])

		row = self._rows()["2026-06-03"]

		self.assertEqual(row["status"], "Holiday / عطلة")
		self.assertEqual(row["day_type"], "Public Holiday / عطلة رسمية")

	def test_the_weekend_reads_as_a_holiday(self):
		rows = self._rows()

		self.assertEqual(rows["2026-06-05"]["status"], "Holiday / عطلة")
		self.assertEqual(rows["2026-06-05"]["day_type"], "Friday / الجمعة")
		self.assertEqual(rows["2026-06-06"]["day_type"], "Saturday / السبت")

	def test_a_day_with_only_punches_reads_as_present(self):
		self._make_checkin("2026-06-09", at="09:15:00", log_type="IN")

		row = self._rows()["2026-06-09"]

		self.assertEqual(row["status"], "Present / حاضر")
		self.assertEqual(row["time_in"], "09:15")

	def test_a_future_day_is_not_marked_present_or_absent(self):
		rows = {
			row["attendance_date"]: row
			for row in get_monthly_days("December / ديسمبر", 2026, self.employee)
		}

		future = rows["2026-12-01"]  # a Tuesday still ahead
		self.assertIsNone(future["status"])
		self.assertEqual(future["day_type"], "Working Day / يوم عمل")

	def test_generating_without_an_employee_never_claims_present(self):
		rows = get_monthly_days("June / يونيو", 2026)

		working = [row for row in rows if row["day_type"] == "Working Day / يوم عمل"]
		self.assertTrue(working)
		self.assertTrue(all(row["status"] is None for row in working))
		self.assertTrue([row for row in rows if row["day_type"] == "Friday / الجمعة"])

	def test_the_summary_totals_follow_the_real_rows(self):
		self._make_attendance("2026-06-01")  # present; every other working day is absent

		rows = get_monthly_days("June / يونيو", 2026, self.employee)
		record = frappe.get_doc(
			{
				"doctype": "Monthly Attendance Record",
				"employee": self.employee,
				"company": self.company,
				"month": "June / يونيو",
				"year": 2026,
				"attendance_details": [
					{
						"attendance_date": row["attendance_date"],
						"day_type": row["day_type"],
						"status": row["status"],
					}
					for row in rows
				],
			}
		).insert(ignore_permissions=True)

		self.assertEqual(record.actual_present_days, 1)
		self.assertGreaterEqual(record.absent_days, 1)
