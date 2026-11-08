import frappe
from frappe.model.document import Document
from frappe.utils import today

from saudi_hr.saudi_hr.hr_documents import is_document_ready


class HRServiceRequest(Document):
	def validate(self):
		if self.from_date and self.to_date and self.to_date < self.from_date:
			frappe.throw("End date cannot be before start date")
		if self.request_type == "advance_salary" and (not self.amount or self.amount <= 0):
			frappe.throw("Amount is required for salary advance requests")
		if self.request_type == "employee_loan" and (not self.amount or self.amount <= 0):
			frappe.throw("Amount is required for employee loan requests")
		if not self.issued_on and is_document_ready(self.request_type, self.workflow_state):
			self.issued_on = today()
