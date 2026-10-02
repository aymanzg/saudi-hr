import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import date_diff, flt, getdate, nowdate

from saudi_hr.saudi_hr.utils import (
	assert_employee_record_access,
	get_annual_leave_balance,
	get_emergency_leave_balance,
	get_overlap_days,
)


class SaudiEmergencyLeave(Document):
	"""Emergency leave, for the case that cannot wait for an annual-leave request.

	The rule this enforces is deliberate: emergency leave is a fallback, not a
	premium. If the employee still has annual leave in the book, the annual leave
	is the right instrument, so the request is refused until it is used up.

	``workflow_state`` is the single source of truth for where this request sits;
	there is no second status field that could drift away from it.
	"""

	def validate(self):
		self._sync_employee_context()
		self._calculate_total_days()
		self._validate_dates()
		self._snapshot_entitlement()
		self._block_when_annual_leave_remains()
		self._validate_emergency_quota()

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

	def _calculate_total_days(self):
		if self.from_date and self.to_date:
			self.total_days = max(0, date_diff(getdate(self.to_date), getdate(self.from_date)) + 1)

	def _validate_dates(self):
		if not (self.from_date and self.to_date):
			return

		if getdate(self.to_date) < getdate(self.from_date):
			frappe.throw(_("To Date must be after From Date / يجب أن يكون تاريخ الانتهاء بعد تاريخ البدء"))

	def _snapshot_entitlement(self):
		reference = self.from_date or nowdate()
		emergency = get_emergency_leave_balance(self.employee, reference, exclude_name=self.name)
		self.entitlement_days = emergency["entitled"]
		self.used_days_before = emergency["taken"]
		self.available_days = emergency["available"]

		# only submitted annual leave counts: a draft request must not lock the
		# employee out of emergency leave
		annual = get_annual_leave_balance(self.employee, reference)
		self.annual_leave_balance_snapshot = flt(annual["balance"])
		self.annual_leave_available = int(flt(annual["balance"]) > 0)

	def _block_when_annual_leave_remains(self):
		if not self.employee:
			return
		if not self.annual_leave_available:
			return

		frappe.throw(
			_("This employee still has {0} day(s) of annual leave available, so emergency leave cannot be requested. Use the annual leave request instead, or ask HR to adjust the balance.<br>"
			  "لا يزال لدى الموظف {0} يوم من رصيد الإجازة السنوية، لذا لا يمكن طلب إجازة طارئة. استخدم طلب الإجازة السنوية بدلاً من ذلك، أو راجع الموارد البشرية لتعديل الرصيد.").format(
				flt(self.annual_leave_balance_snapshot, 2)
			),
			title=_("Annual Leave Still Available / ما زال رصيد الإجازة السنوية متاحاً"),
		)

	def _validate_emergency_quota(self):
		if not (self.employee and self.from_date and self.to_date):
			return

		# three days per calendar year, so a request that crosses New Year spends
		# the quota of each year it touches rather than one year's three days
		start, end = getdate(self.from_date), getdate(self.to_date)
		for year in range(start.year, end.year + 1):
			requested = get_overlap_days(self.from_date, self.to_date, f"{year}-01-01", f"{year}-12-31")
			if not requested:
				continue

			balance = get_emergency_leave_balance(self.employee, f"{year}-12-31", exclude_name=self.name)
			if requested > flt(balance["available"]):
				frappe.throw(
					_("Emergency leave covers {0} day(s) per calendar year; {1} remain in {2} and this request needs {3}.<br>"
					  "الإجازة الطارئة {0} يوم في السنة الميلادية، والمتاح {1} يوم في {2} وهذا الطلب يحتاج {3}.").format(
						int(balance["entitled"]), flt(balance["available"], 2), year, requested
					),
					title=_("Emergency Leave Limit Exceeded / تجاوز حد الإجازة الطارئة"),
				)


@frappe.whitelist()
def get_emergency_leave_availability(employee=None, from_date=None, exclude_doc=""):
	"""The warning the mobile form shows before it lets anyone submit.

	Returns both quotas plus the annual-leave gate, so the client never has to
	guess why an emergency request would be refused.
	"""
	employee = employee or _employee_for_session_user()
	assert_employee_record_access(employee, "Saudi Emergency Leave")

	reference = from_date or nowdate()
	emergency = get_emergency_leave_balance(employee, reference, exclude_name=exclude_doc)
	annual = get_annual_leave_balance(employee, reference)
	annual_balance = flt(annual["balance"])

	return {
		"emergency_entitled": emergency["entitled"],
		"emergency_taken": emergency["taken"],
		"emergency_available": emergency["available"],
		"annual_leave_balance": annual_balance,
		"annual_leave_available": int(annual_balance > 0),
		"blocked_by_annual_leave": int(annual_balance > 0),
		"year": emergency["year"],
	}


def _employee_for_session_user():
	employee = frappe.db.get_value("Employee", {"user_id": frappe.session.user}, "name")
	if not employee:
		frappe.throw(
			_("No employee record is linked to your user.<br>لا يوجد سجل موظف مرتبط بحسابك."),
			title=_("Employee Not Found / لم يتم العثور على الموظف"),
		)
	return employee