"""The dashboard clock.

It used to be the wall clock, shown to everyone, because it read the HRMS
``Employee Checkin`` doctype this site does not have. It is now the employee's
own check-in time, shown only while they are checked in.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from saudi_hr.saudi_hr.enterprise_operations import _attendance_status_for

from frappe.utils import add_days, now_datetime


def _expected(value):
	"""The format the dashboard promises: 08:05 ص / 04:05 م.

	Written out rather than imported, so a change to the helper cannot quietly
	change the contract with it.
	"""
	formatted = value.strftime("%I:%M %p")
	return formatted.replace("AM", "ص").replace("PM", "م")


class TestAttendanceClock(FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.employee = frappe.get_all(
			"Employee", filters={"status": "Active"}, pluck="name", limit_page_length=1
		)[0]
		self.today = frappe.utils.nowdate()
		self._clear_punches()

	def tearDown(self):
		self._clear_punches()
		super().tearDown()

	def _clear_punches(self):
		frappe.db.delete("Saudi Employee Checkin", {"employee": self.employee})

	def _punch(self, log_type, time):
		frappe.get_doc(
			{
				"doctype": "Saudi Employee Checkin",
				"employee": self.employee,
				"log_type": log_type,
				"time": time,
				"verification_mode": "gps",
			}
		).insert(ignore_permissions=True)

	def test_nobody_punched_yet_means_no_clock(self):
		status = _attendance_status_for(self.employee)
		self.assertEqual(status["status_code"], "not_checked_in")
		self.assertIsNone(status["checkin_time"])
		self.assertFalse(status["is_present"])
		self.assertFalse(status["live_clock"])

	def test_the_clock_is_never_a_ticking_wall_clock(self):
		"""The old payload told the page to run its own tick."""
		self._punch("IN", now_datetime())
		self.assertFalse(_attendance_status_for(self.employee)["live_clock"])

	def test_checked_in_shows_the_check_in_time(self):
		punched_at = now_datetime()
		self._punch("IN", punched_at)
		status = _attendance_status_for(self.employee)
		self.assertEqual(status["status_code"], "checked_in")
		self.assertTrue(status["is_present"])
		self.assertEqual(status["checkin_time"], _expected(punched_at))
		self.assertEqual(
			status["time"], _expected(punched_at), "the Desk page still reads .time"
		)

	def test_checked_out_keeps_the_check_in_time_and_drops_the_clock(self):
		"""A finished day has no live clock, but its check-in time is real."""
		start = frappe.utils.get_datetime(f"{self.today} 08:05:00")
		self._punch("IN", start)
		self._punch("OUT", frappe.utils.get_datetime(f"{self.today} 17:00:00"))
		status = _attendance_status_for(self.employee)
		self.assertEqual(status["status_code"], "checked_out")
		self.assertFalse(status["is_present"])
		self.assertEqual(status["checkin_time"], _expected(start))
		self.assertEqual(status["checkin_time"], "08:05 ص")
		self.assertEqual(status["punch_count"], 2)

	def test_only_todays_punches_count(self):
		"""Yesterday's punch must not make today look checked in."""
		yesterday = add_days(self.today, -1)
		self._punch("IN", frappe.utils.get_datetime(f"{yesterday} 08:00:00"))
		status = _attendance_status_for(self.employee)
		self.assertEqual(status["status_code"], "not_checked_in")
		self.assertIsNone(status["checkin_time"])

	def test_the_label_is_bilingual_for_console_consumers(self):
		"""status_code is what the page localises; the label is the fallback."""
		self.assertIn(" / ", _attendance_status_for(self.employee)["status_label"])

	def test_the_hijri_date_still_rides_along(self):
		status = _attendance_status_for(self.employee)
		self.assertTrue(status["date_hijri"])
		self.assertEqual(status["date_gregorian"], self.today)