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
		if self.is_opening_balance:
			if not self.balance_as_of_date:
				frappe.throw(
					_(
						"An opening balance requires the as-of date.<br>"
						"يتطلب الرصيد الافتتاحي تحديد تاريخ الرصيد."
					),
					title=_("Missing As Of Date / تاريخ الرصيد مفقود"),
				)
			if flt(self.adjustment_days) < 0:
				frappe.throw(
					_(
						"An opening balance cannot be negative.<br>"
						"لا يمكن أن يكون الرصيد الافتتاحي سالبًا."
					),
					title=_("Invalid Opening Balance / رصيد افتتاحي غير صالح"),
				)

	def on_submit(self):
		if not self.is_opening_balance:
			return
		duplicate = frappe.db.get_value(
			"Leave Balance Adjustment",
			{
				"employee": self.employee,
				"leave_year": self.leave_year,
				"is_opening_balance": 1,
				"docstatus": 1,
				"name": ["!=", self.name],
			},
			"name",
		)
		if duplicate:
			frappe.throw(
				_(
					"An opening balance already exists for {0} in {1}: {2}.<br>"
					"يوجد رصيد افتتاحي مسجّل مسبقًا للموظف {0} لسنة {1}: {2}."
				).format(frappe.bold(self.employee), self.leave_year, frappe.bold(duplicate)),
				title=_("Duplicate Opening Balance / رصيد افتتاحي مكرر"),
			)
