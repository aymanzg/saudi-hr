import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class LeaveBalanceAdjustment(Document):
	def validate(self):
		if not self.employee:
			frappe.throw(_("Employee is required / يلزم تحديد الموظف"))
		if self.adjustment_days is None or flt(self.adjustment_days) == 0:
			frappe.throw(_("Adjustment days cannot be zero / لا يمكن أن تكون أيام التعديل صفرًا"))
		status = frappe.db.get_value("Employee", self.employee, "status")
		if status != "Active":
			frappe.throw(_("Employee {0} is not active / الموظف غير نشط").format(self.employee))