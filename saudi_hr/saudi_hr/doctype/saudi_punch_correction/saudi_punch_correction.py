import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cstr, get_datetime, getdate, get_time, now_datetime, nowdate

from saudi_hr.saudi_hr.attendance_policy import (
	calculate_attendance_variance,
	resolve_mobile_attendance_policy,
)
from saudi_hr.saudi_hr.utils import assert_employee_record_access

APPROVED_STATE = "Completed"


class SaudiPunchCorrection(Document):
	"""A request to fix or register a check-in/check-out punch, applied only once approved.

	A punch that already exists is moved to the corrected time with its original
	captured on the request first, so the request is the audit trail of what the
	punches used to say. When the employee has no punch on the date (they forgot
	to check in, or the punch never reached the device), the request registers
	one at the corrected time instead of refusing: an approved request is our
	documented, auditable equivalent of a punch.

	The original times are never lost. They are captured on the request before the
	punches move, so the approved request is the audit trail of what the punches
	used to say, and cancelling the request puts them back. A punch that the
	request created is deleted again on cancel, and a day's attendance that the
	request created is removed with it.

	The workflow state is applied last. Frappe runs workflow transitions inside
	``on_update``, which is *after* ``validate``, so a correction is applied from
	``on_submit`` rather than from validation.
	"""

	def validate(self):
		self._sync_employee_context()
		self._validate_attendance_date()
		self._resolve_punches()
		self._resolve_daily_attendance()
		self._validate_not_already_corrected()
		self._require_a_corrected_time()
		# an edit after approval should not leave a stale punch behind
		self._apply_correction_if_approved()

	def on_submit(self):
		self._apply_correction_if_approved()

	def on_cancel(self):
		"""Cancelling an approved correction undoes what it did: punches it moved
		go back to their originals, punches it created are deleted, and a day's
		attendance row it created is removed with them."""
		if not self.applied:
			return

		if self.punch and self.original_in_time:
			self._move_punch("IN", self.punch, get_datetime(f"{self.attendance_date} {self.original_in_time}"))
		elif self.punch:
			self._clear_daily_time("in_time")
			frappe.delete_doc(
				"Saudi Employee Checkin", self.punch, force=True, ignore_permissions=True
			)
		if self.punch_out and self.original_out_time:
			self._move_punch("OUT", self.punch_out, get_datetime(f"{self.attendance_date} {self.original_out_time}"))
		elif self.punch_out:
			self._clear_daily_time("out_time")
			frappe.delete_doc(
				"Saudi Employee Checkin", self.punch_out, force=True, ignore_permissions=True
			)
		if self.created_daily_attendance and self.daily_attendance:
			# the row was inserted and submitted on approval, so it has to be
			# cancelled before it can be deleted
			daily = frappe.get_doc("Saudi Daily Attendance", self.daily_attendance)
			daily.flags.ignore_permissions = True
			if daily.docstatus == 1:
				daily.cancel()
			frappe.delete_doc(
				"Saudi Daily Attendance", self.daily_attendance, force=True, ignore_permissions=True
			)
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

	def _resolve_punches(self):
		if not (self.employee and self.attendance_date):
			return

		self._resolve_punch_in()
		self._resolve_punch_out()

	def _resolve_punch_in(self):
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
			# No check-in punch on the date is not a refusal: the employee may
			# have forgotten to check in, and the approved request then serves
			# as an auditable registration of the missing punch.
			self.punch = None
			self.original_in_time = None
			return

		punch = punches[0]
		# Capture the original before it is overwritten, so the request itself
		# remains the record of what the punch used to say. Frappe pre-fills every
		# Time field of a new document with the current time, so "is it already
		# set?" is never a usable test: capture it on the first save, then keep it.
		if self.is_new() or not self.get("original_in_time"):
			self.original_in_time = get_time(punch.time)
		self.punch = punch.name

	def _resolve_punch_out(self):
		punches = frappe.get_all(
			"Saudi Employee Checkin",
			filters={
				"employee": self.employee,
				"log_type": "OUT",
				"time": ["between", [f"{self.attendance_date} 00:00:00", f"{self.attendance_date} 23:59:59"]],
			},
			fields=["name", "time", "early_exit_minutes"],
			order_by="time desc",
			limit_page_length=1,
		)
		if not punches:
			# Like the check-in, a missing check-out is registered rather than
			# refused once the request is approved.
			self.punch_out = None
			self.original_out_time = None
			return

		punch = punches[0]
		if self.is_new() or not self.get("original_out_time"):
			self.original_out_time = get_time(punch.time)
		self.punch_out = punch.name

	def _require_a_corrected_time(self):
		"""A request must move something: check-in, check-out, or both."""
		if self._real_corrected_time("corrected_in_time") or self._real_corrected_time("corrected_out_time"):
			return

		frappe.throw(
			_("Please choose the corrected check-in or check-out time.<br>"
			  "الرجاء تحديد وقت الحضور أو الخروج الصحيح."),
			title=_("Corrected Time Required / الوقت الصحيح مطلوب"),
		)

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
				_("The attendance on {0} was already corrected by {1}. A day can only be corrected once.<br>"
				  "تم تصحيح سجل الحضور في {0} مسبقاً عبر {1}. لا يمكن تصحيح اليوم نفسه أكثر من مرة.").format(
					frappe.bold(self.attendance_date), frappe.bold(existing)
				),
				title=_("Already Corrected / تم التصحيح مسبقاً"),
			)

	def _apply_correction_if_approved(self):
		"""Idempotent: the ``applied`` flag means this runs exactly once."""
		if self.applied or self.workflow_state != APPROVED_STATE or self.docstatus != 1:
			return

		in_time = self._corrected_datetime("corrected_in_time")
		out_time = self._corrected_datetime("corrected_out_time")
		if not (in_time or out_time):
			return

		if in_time:
			if self.punch:
				self._move_punch("IN", self.punch, in_time)
			else:
				punch = self._create_punch("IN", in_time)
				self._move_punch("IN", punch, in_time)
				self.punch = punch
				frappe.db.set_value("Saudi Punch Correction", self.name, "punch", punch)
		if out_time:
			if self.punch_out:
				self._move_punch("OUT", self.punch_out, out_time)
			else:
				punch = self._create_punch("OUT", out_time)
				self._move_punch("OUT", punch, out_time)
				self.punch_out = punch
				frappe.db.set_value("Saudi Punch Correction", self.name, "punch_out", punch)

		self._ensure_daily_attendance(in_time, out_time)
		self.db_set({"applied": 1, "applied_on": now_datetime()})

	def _corrected_datetime(self, field):
		"""A corrected Time field as a datetime on the request's date, or None."""
		value = self._real_corrected_time(field)
		return get_datetime(f"{self.attendance_date} {value}") if value else None

	def _real_corrected_time(self, field):
		"""The time the employee typed, or None when the field only holds the
		now-the-pre-fill.

		Frappe proposes the current time in every empty Time field of a new
		document, so an empty corrected field is not readable as "empty" from the
		value alone: it holds now, with fractional seconds. A time the employee
		typed (the form sends hour and minute) never carries microseconds, so the
		fractional part is exactly the mark of a time nobody chose.
		"""
		value = cstr(self.get(field) or "").strip()
		if not value:
			return None
		try:
			time_obj = get_time(value)
		except ValueError:
			return None
		if getattr(time_obj, "microsecond", 0):
			return None
		return time_obj

	def _create_punch(self, log_type, punch_time):
		"""Register a punch the date did not have, tagged with this request so the
		audit trail says it was created rather than read from a device."""
		checkin = frappe.get_doc(
			{
				"doctype": "Saudi Employee Checkin",
				"employee": self.employee,
				"log_type": log_type,
				"time": punch_time,
				"verification_note": _("Registered by Punch Correction {0} / مسجلة عبر طلب تصحيح البصمة {0}").format(
					self.name
				),
			}
		)
		checkin.flags.ignore_permissions = True
		checkin.insert()
		return checkin.name

	def _ensure_daily_attendance(self, in_time=None, out_time=None):
		"""A registered punch must surface as a day in the reports: create the
		day's attendance row when the correction is the first thing that did."""
		if self.daily_attendance or not (in_time or out_time):
			return

		# a correction to only one side still gets a complete day: the other
		# side falls back to the real punch on the date
		if not in_time and self.punch:
			in_time = frappe.db.get_value("Saudi Employee Checkin", self.punch, "time")
		if not out_time and self.punch_out:
			out_time = frappe.db.get_value("Saudi Employee Checkin", self.punch_out, "time")
		if not (in_time or out_time):
			return

		policy = resolve_mobile_attendance_policy(self.employee, self.attendance_date)
		in_variance = calculate_attendance_variance("IN", in_time, policy) if in_time else {}
		out_variance = calculate_attendance_variance("OUT", out_time, policy) if out_time else {}
		attendance = frappe.get_doc(
			{
				"doctype": "Saudi Daily Attendance",
				"employee": self.employee,
				"attendance_date": self.attendance_date,
				"status": "Present / حاضر",
				"in_time": in_time,
				"out_time": out_time,
				"shift_type": policy.get("shift_type"),
				"expected_start_time": policy.get("expected_start"),
				"expected_end_time": policy.get("expected_end"),
				"late_entry": in_variance.get("late_entry", 0),
				"late_minutes": in_variance.get("late_minutes", 0),
				"early_exit": out_variance.get("early_exit", 0),
				"early_exit_minutes": out_variance.get("early_exit_minutes", 0),
			}
		)
		attendance.flags.ignore_permissions = True
		attendance.insert()
		attendance.flags.ignore_permissions = True
		attendance.submit()

		self.daily_attendance = attendance.name
		frappe.db.set_value(
			"Saudi Punch Correction",
			self.name,
			{"daily_attendance": attendance.name, "created_daily_attendance": 1},
		)
		for punch in (self.punch, self.punch_out):
			if punch:
				frappe.db.set_value("Saudi Employee Checkin", punch, "attendance", attendance.name)

	def _clear_daily_time(self, field):
		"""Revert a loaded day's time that only existed because this request wrote a
		missing punch onto it, without touching a row the request itself created."""
		if not (self.daily_attendance and not self.created_daily_attendance):
			return
		updates = {field: None}
		if field == "in_time":
			updates.update({"late_entry": 0, "late_minutes": None})
		else:
			updates.update({"early_exit": 0, "early_exit_minutes": None})
		frappe.db.set_value("Saudi Daily Attendance", self.daily_attendance, updates)
		self._resync_daily_attendance()

	def _move_punch(self, log_type, punch_name, punch_time):
		"""Point a punch, its penalty, and the day at this time.

		Both moving forward and reverting go through here, so the penalties that are
		written on approval are exactly the penalties that come back on cancel.
		"""
		variance = calculate_attendance_variance(
			log_type, punch_time, resolve_mobile_attendance_policy(self.employee, self.attendance_date)
		)

		punch_updates = {"time": punch_time}
		if log_type == "IN":
			punch_updates["late_minutes"] = variance["late_minutes"]
		else:
			punch_updates["early_exit_minutes"] = variance["early_exit_minutes"]
		frappe.db.set_value("Saudi Employee Checkin", punch_name, punch_updates)

		if not self.daily_attendance:
			return

		attendance_updates = {}
		if log_type == "IN":
			attendance_updates = {
				"in_time": punch_time,
				"late_entry": variance["late_entry"],
				"late_minutes": variance["late_minutes"],
			}
		else:
			attendance_updates = {
				"out_time": punch_time,
				"early_exit": variance["early_exit"],
				"early_exit_minutes": variance["early_exit_minutes"],
			}
		frappe.db.set_value("Saudi Daily Attendance", self.daily_attendance, attendance_updates)
		# working hours and the remaining flags are derived on save
		self._resync_daily_attendance()

	def _resync_daily_attendance(self):
		"""Re-derive the day so working hours follow the corrected punch."""
		if not self.daily_attendance:
			return

		attendance = frappe.get_doc("Saudi Daily Attendance", self.daily_attendance)
		attendance.flags.ignore_permissions = True
		attendance.flags.ignore_validate_update_after_submit = True
		attendance.save()


@frappe.whitelist()
def get_punch_correction_context(employee=None, attendance_date=None):
	"""What the mobile form needs to show before the employee submits.

	Returns the punches it would correct, so the form can display the current
	check-in and check-out next to the corrected ones instead of asking the
	employee to trust it.
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
		"has_in_punch": 0,
		"punch_out": None,
		"current_out_time": None,
		"has_out_punch": 0,
	}
	if not (employee and attendance_date):
		return context

	in_punches = frappe.get_all(
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
	if in_punches:
		context["punch"] = in_punches[0].name
		context["current_in_time"] = get_time(in_punches[0].time)
		context["has_in_punch"] = 1
		# the date has happened, so the form may correct it or register the
		# missing punch even when none was recorded
		context["correctable"] = 1

	out_punches = frappe.get_all(
		"Saudi Employee Checkin",
		filters={
			"employee": employee,
			"log_type": "OUT",
			"time": ["between", [f"{attendance_date} 00:00:00", f"{attendance_date} 23:59:59"]],
		},
		fields=["name", "time"],
		order_by="time desc",
		limit_page_length=1,
	)
	if out_punches:
		context["punch_out"] = out_punches[0].name
		context["current_out_time"] = get_time(out_punches[0].time)
		context["has_out_punch"] = 1

	if attendance_date:
		context["future_date"] = int(getdate(attendance_date) > getdate(nowdate()))
		if not context["has_in_punch"] and not context["future_date"]:
			# no punch to display, but the day has happened, so the request may
			# register the forgotten punch
			context["correctable"] = 1
	return context