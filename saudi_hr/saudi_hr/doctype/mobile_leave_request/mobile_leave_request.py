import frappe
from frappe.model.document import Document
from frappe.utils import date_diff


class MobileLeaveRequest(Document):

	def validate(self):
		self._calculate_total_days()

	def _calculate_total_days(self):
		if self.from_date and self.to_date:
			self.total_days = max(date_diff(self.to_date, self.from_date) + 1, 1)
			if self.total_days <= 0:
				frappe.throw(
					_("To Date must be after From Date / يجب أن يكون تاريخ الانتهاء بعد تاريخ البدء")
				)
