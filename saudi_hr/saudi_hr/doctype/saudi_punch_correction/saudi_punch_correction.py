import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime, getdate, get_time, now_datetime, nowdate

from saudi_hr.saudi_hr.attendance_policy import (
	calculate_attendance_variance,
	resolve_mobile_attendance_policy,
)
from saudi_hr.saudi_hr.utils import assert_employee_record_access

APPROVED_STATE = "Approved"


class SaudiPunchCorrection(Document):
	"""A request to fix a wrong check-in punch, applied only once it is approved.

	The correction is refused unless the employee actually has an IN punch on that
	date: without one there is nothing to correct, and inventing a punch would
	fabricate attendance.

	The original time is never lost. It is captured on the request before the
	punch moves, so the approved request is the audit trail of what the punch
	used to say, and cancelling the request puts the punch back.

	The workflow state is applied last. Frappe runs workflow transitions inside
``on_update``, which is *after* ``validate``, so a correction is applied from
``on_submit`` rather than from validation.
	"""

	def validate(self):
		self._sync_employee_context()
		self._validate_attendance_date()
		self._resolve_punch()
		self._resolve_daily_attendance()
		self._validate_not_already_corrected()
		# an edit after approval should not leave a stale punch behind
		self._apply_correction_if_approved()

	def on_submit(self):
		self._apply_correction_if_approved()

	def on_cancel(self):
		"""Cancelling an approved correction puts the punch back the way it was."""
		if not self.applied or not self.punch or not self.original_in_time:
			return

		self._move_punch(get_datetime(f"{self.attendance_date} {self.original_in_time}"))
		self.db_set({"applied": 0, "applied_on": None})

	def _sync_employee_context(self):
		if not self.employee:
			return

		employee = frappe.db.get_value(
			"Employee",
			self.employee,
			["employee_name", "company", "department"],
			as_dict=True,
		)
		if not employee:
			frappe.throw(
				_("Employee {0} was not found.<br>لم يتم العثور على الموظف {0}.").format(
					frappe.bold(self.employee)
				)
			)
		self.employee_name = employee.employee_name
		self.company = employee.company
		self.department = employee.department

	def _validate_attendance_date(self):
		if not self.attendance_date:
			return

		if getdate(self.attendance_date) > getdate(nowdate()):
			frappe.throw(
				_("You cannot correct a day that has not happened yet.<br>لا يمكن تصحيح يوم لم يحدث بعد.")
			)

	def _resolve_punch(self):
		if not (self.employee and self.attendance_date):
			return

		punches = frappe.get_all(
			"Saudi Employee Checkin",
			filters={
				"employee": self.employee,
				"log_type": "IN",
				"time": ["between", [f"{self.attendance_date} 00:00:00", f"{self.attendance_date} 23:59:59"]],
			},
			fields=["name", "time", "late_minutes"],
			order_by="time asc",
			limit_page_length=1,
		)
		if not punches:
			frappe.throw(
				_("No check-in punch was found for {0} on {1}. There is nothing to correct on that date.<br>"
				  "لم يتم العثور على بصمة حضور للموظف في {1}. لا يوجد ما يمكن تصحيحه في هذا التاريخ.").format(
					frappe.bold(self.employee), frappe.bold(self.attendance_date)
				),
				title=_("No Punch To Correct / لا توجد بصمة لتصحيحها"),
			)

		punch = punches[0]
		# Capture the original before it is overwritten, so the request itself
		# remains the record of what the punch used to say. Frappe pre-fills every
		# Time field of a new document with the current time, so "is it already
		# set?" is never a usable test: capture it on the first save, then keep it.
		if self.is_new() or not self.get("original_in_time"):
			self.original_in_time = get_time(punch.time)
		self.punch = punch.name

	def _resolve_daily_attendance(self):
		if not (self.employee and self.attendance_date):
			return

		self.daily_attendance = frappe.db.get_value(
			"Saudi Daily Attendance",
			{"employee": self.employee, "attendance_date": self.attendance_date},
			"name",
		)

	def _validate_not_already_corrected(self):
		if not (self.employee and self.attendance_date and self.name):
			return

		existing = frappe.db.exists(
			"Saudi Punch Correction",
			{
				"employee": self.employee,
				"attendance_date": self.attendance_date,
				"applied": 1,
				"docstatus": 1,
				"name": ["!=", self.name],
			},
		)
		if existing:
			frappe.throw(
				_("The check-in on {0} was already corrected by {1}. A day can only be corrected once.<br>"
				  "تم تصحيح بصمة الحضور في {0} مسبقاً عبر {1}. لا يمكن تصحيح اليوم نفسه أكثر من مرة.").format(
					frappe.bold(self.attendance_date), frappe.bold(existing)
				),
				title=_("Already Corrected / تم التصحيح مسبقاً"),
			)

	def _apply_correction_if_approved(self):
		"""Idempotent: the ``applied`` flag means this runs exactly once."""
		if self.applied or self.workflow_state != APPROVED_STATE or self.docstatus != 1:
			return
		if not (self.punch and self.corrected_in_time):
			return

		self._move_punch(get_datetime(f"{self.attendance_date} {self.corrected_in_time}"))
		self.db_set({"applied": 1, "applied_on": now_datetime()})

	def _move_punch(self, punch_time):
		"""Point the punch, its penalty, and the day at this time.

		Both moving forward and reverting go through here, so the lateness that is
		written on approval is exactly the lateness that comes back on cancel.
		"""
		variance = calculate_attendance_variance(
			"IN", punch_time, resolve_mobile_attendance_policy(self.employee, self.attendance_date)
		)

		frappe.db.set_value(
			"Saudi Employee Checkin",
			self.punch,
			{"time": punch_time, "late_minutes": variance["late_minutes"]},
		)

		if not self.daily_attendance:
			return

		frappe.db.set_value(
			"Saudi Daily Attendance",
			self.daily_attendance,
			{
				"in_time": punch_time,
				"late_entry": variance["late_entry"],
				"late_minutes": variance["late_minutes"],
			},
		)
		# working hours and the remaining flags are derived on save
		self._resync_daily_attendance()

	def _resync_daily_attendance(self):
		"""Re-derive the day so working hours follow the corrected check-in."""
		if not self.daily_attendance:
			return

		attendance = frappe.get_doc("Saudi Daily Attendance", self.daily_attendance)
		attendance.flags.ignore_permissions = True
		attendance.flags.ignore_validate_update_after_submit = True
		attendance.save()


@frappe.whitelist()
def get_punch_correction_context(employee=None, attendance_date=None):
	"""What the mobile form needs to show before the employee submits.

	Returns the punch it would correct, so the form can display the current
	check-in next to the corrected one instead of asking the employee to trust it.
	"""
	employee = employee or frappe.db.get_value(
		"Employee", {"user_id": frappe.session.user}, "name"
	)
	assert_employee_record_access(employee, "Saudi Punch Correction")

	context = {
		"employee": employee,
		"attendance_date": attendance_date,
		"punch": None,
		"current_in_time": None,
		"correctable": 0,
		"future_date": 0,
	}
	if not (employee and attendance_date):
		return context

	punches = frappe.get_all(
		"Saudi Employee Checkin",
		filters={
			"employee": employee,
			"log_type": "IN",
			"time": ["between", [f"{attendance_date} 00:00:00", f"{attendance_date} 23:59:59"]],
		},
		fields=["name", "time"],
		order_by="time asc",
		limit_page_length=1,
	)
	if punches:
		context["punch"] = punches[0].name
		context["current_in_time"] = get_time(punches[0].time)
		context["correctable"] = 1

	if attendance_date:
		context["future_date"] = int(getdate(attendance_date) > getdate(nowdate()))
	return context