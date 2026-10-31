import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, date_diff, add_days


class SaudiFinalSettlement(Document):
	def validate(self):
		self._calculate_totals()
		self._build_html()

	def _calculate_totals(self):
		total_earn = 0.0
		total_ded = 0.0
		for row in self.get("earnings") or []:
			total_earn += flt(row.amount)
		for row in self.get("deductions") or []:
			total_ded += flt(row.amount)
		self.total_earnings = total_earn
		self.total_deductions = total_ded
		self.net_payable = flt(total_earn) - flt(total_ded)

	def _build_html(self):
		html = "<h4>مخالصة مالية شاملة / Comprehensive Final Settlement</h4>"
		html += "<p><b>Employee:</b> %s | <b>Period:</b> %s to %s</p>" % (
			self.employee_name or self.employee,
			self.calculated_from or self.last_payroll_period_from or "",
			self.calculated_to or self.last_payroll_period_to or "",
		)
		html += "<h5>مستحقات / Earnings</h5><table border='1' cellpadding='4' cellspacing='0'><tr><th>Item</th><th>Amount</th></tr>"
		for row in self.get("earnings") or []:
			html += "<tr><td>%s</td><td>%s</td></tr>" % (row.item or row.description or "", row.amount)
		html += "<tr><td><b>Total</b></td><td><b>%s</b></td></tr></table>"
		html += "<h5>استقطاعات / Deductions</h5><table border='1' cellpadding='4' cellspacing='0'><tr><th>Item</th><th>Amount</th></tr>"
		for row in self.get("deductions") or []:
			html += "<tr><td>%s</td><td>%s</td></tr>" % (row.item or row.description or "", row.amount)
		html += "<tr><td><b>Total</b></td><td><b>%s</b></td></tr></table>"
		html += "<p><b>Net Payable / صافي المستحق:</b> %s</p>" % self.net_payable
		self.details_html = html
