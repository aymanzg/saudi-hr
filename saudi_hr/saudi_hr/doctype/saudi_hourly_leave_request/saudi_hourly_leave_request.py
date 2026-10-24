import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, get_datetime, get_last_day, getdate, now_datetime, nowdate, time_diff_in_hours

from saudi_hr.saudi_hr.utils import assert_employee_record_access, get_hourly_leave_balance
from saudi_hr.saudi_hr.workflow_catalogue import state_bucket


class SaudiHourlyLeaveRequest(Document):
	def validate(self):
		self._sync_employee_context()
		self._validate_leave_date()
		self._validate_times()
		self._check_overlap()
		self._apply_balance_snapshot()
		if cint(self.applied):
			self._ensure_approval_snapshot()

	def on_submit(self):
		self._apply_balance_snapshot(check_approved=True)
		self.db_set(
			{
				"applied": 1,
				"approved_by": frappe.session.user,
				"approved_on": now_datetime(),
			}
		)

	def on_cancel(self):
		self.db_set(
			{
				"applied": 0,
				"approved_by": None,
				"approved_on": None,
			}
		)

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
			frappe.throw(_("Employee {0} was not found.").format(frappe.bold(self.employee)))
		self.employee_name = employee.employee_name
		self.company = employee.company
		self.department = employee.department

	def _validate_leave_date(self):
		if not self.leave_date:
			return
		leave_date = getdate(self.leave_date)
		today = getdate(nowdate())
		if leave_date < today:
			frappe.throw(_("Hourly leave cannot be for a past date."))
		first = today.replace(day=1)
		last = get_last_day(today)
		if leave_date < first or leave_date > last:
			frappe.throw(_("Hourly leave must be within the current calendar month."))

	def _validate_times(self):
		if not (self.from_time and self.to_time):
			return
		start = get_datetime(f"{self.leave_date} {self.from_time}")
		end = get_datetime(f"{self.leave_date} {self.to_time}")
		if end <= start:
			frappe.throw(_("To Time must be after From Time."))
		diff_hours = time_diff_in_hours(end, start)
		minutes = round(diff_hours * 60)
		if minutes % 60 != 0:
			frappe.throw(_("Hourly leave is in whole hours only."))
		hours = minutes / 60.0
		if hours < 1:
			frappe.throw(_("Minimum hourly leave is 1 hour."))
		if hours != int(hours):
			frappe.throw(_("Hourly leave is in whole hours only."))
		self.total_hours = flt(hours)

	def _check_overlap(self):
		if not (self.employee and self.leave_date and self.from_time and self.to_time):
			return
		filters = {
			"employee": self.employee,
			"leave_date": self.leave_date,
			"name": ["!=", self.name or ""],
			"docstatus": ["!=", 2],
		}
		for row in frappe.get_all(
			"Saudi Hourly Leave Request",
			filters=filters,
			fields=["name", "from_time", "to_time", "workflow_state"],
		):
			bucket = state_bucket(row.get("workflow_state"))
			if bucket == "rejected" or bucket == "cancelled":
				continue
			if row.from_time < self.to_time and row.to_time > self.from_time:
				frappe.throw(_("You already have an overlapping hourly leave request for this time."))

	def _apply_balance_snapshot(self, check_approved=False):
		if not self.employee or not self.leave_date:
			return
		balance = get_hourly_leave_balance(self.employee, self.leave_date, exclude_name=self.name)
		self.monthly_allowance_hours = flt(balance.get("allowance"))
		self.used_hours_before = flt(balance.get("approved") + balance.get("pending"))
		requested = flt(self.total_hours or 0)
		available = flt(balance.get("available"))
		if check_approved:
			available = flt(balance.get("allowance")) - flt(balance.get("approved"))
		if requested <= 0:
			return
		if available < requested:
			frappe.throw(
				_("Insufficient hourly leave balance for this month. Available: {0} hours.").format(
					round(available, 2)
				)
			)
		self.remaining_hours_after = round(available - requested, 2)

	def _ensure_approval_snapshot(self):
		self._apply_balance_snapshot(check_approved=True)


@frappe.whitelist()
def get_hourly_leave_context(employee=None, leave_date=None):
	employee = employee or frappe.db.get_value("Employee", {"user_id": frappe.session.user}, "name")
	if not employee:
		return {}
	assert_employee_record_access(employee, "Saudi Hourly Leave Request")
	balance = get_hourly_leave_balance(employee, leave_date)
	return {
		"employee": employee,
		"leave_date": leave_date,
		"allowance": balance.get("allowance"),
		"approved": balance.get("approved"),
		"pending": balance.get("pending"),
		"balance": balance.get("balance"),
		"available": balance.get("available"),
		"month": balance.get("month"),
		"year": balance.get("year"),
		"policy_name": balance.get("policy_name"),
	}
