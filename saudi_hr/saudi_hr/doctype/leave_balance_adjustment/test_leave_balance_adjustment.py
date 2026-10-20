import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import getdate

from saudi_hr.saudi_hr import utils
from saudi_hr.saudi_hr.test_support import make_qa_employee


class TestLeaveBalanceAccrual(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.company = frappe.get_all("Company", pluck="name", limit_page_length=1)[0]

	def _employee(self, joining):
		employee = make_qa_employee(self.company, "leave-accrual")
		frappe.db.set_value("Employee", employee, "date_of_joining", joining)
		return employee

	def _details(self, joining, entitled, threshold=5):
		return {
			"joining_date": getdate(joining),
			"entitled": entitled,
			"annual_leave_years_threshold": threshold,
		}

	def test_accrual_before_threshold_is_1_75_per_month(self):
		details = self._details("2024-01-01", 21)
		self.assertEqual(
			utils.get_accrued_annual_leave(details, "2026-01-01", "2026-06-01"),
			8.75,
		)
		self.assertEqual(
			utils.get_accrued_annual_leave(details, "2026-01-01", "2026-12-31"),
			21.0,
		)

	def test_accrual_after_threshold_is_2_5_per_month(self):
		details = self._details("2019-01-01", 30)
		self.assertEqual(
			utils.get_accrued_annual_leave(details, "2026-01-01", "2026-06-01"),
			12.5,
		)
		self.assertEqual(
			utils.get_accrued_annual_leave(details, "2026-01-01", "2026-12-31"),
			30.0,
		)

	def test_accrual_rate_switches_when_crossing_threshold_mid_year(self):
		details = self._details("2021-07-01", 30)
		self.assertEqual(utils.monthly_accrual_rate(details, "2026-01-31"), 1.75)
		self.assertEqual(utils.monthly_accrual_rate(details, "2026-07-31"), 2.5)
		self.assertEqual(
			utils.get_accrued_annual_leave(details, "2026-01-01", "2026-12-31"),
			25.5,
		)

	def test_opening_balance_anchors_the_total(self):
		employee = self._employee("2019-01-01")
		frappe.get_doc(
			{
				"doctype": "Leave Balance Adjustment",
				"employee": employee,
				"leave_year": 2026,
				"adjustment_days": 15,
				"is_opening_balance": 1,
				"balance_as_of_date": "2026-06-30",
				"reason": "Opening balance from legacy system",
			}
		).insert(ignore_permissions=True).submit()

		balance = utils.get_annual_leave_balance(employee, "2026-09-01")
		self.assertEqual(balance["opening_balance"], 15.0)
		self.assertEqual(balance["opening_as_of"], getdate("2026-06-30"))
		self.assertEqual(balance["accrued"], 5.0)
		self.assertEqual(balance["entitled"], 20.0)
		self.assertEqual(balance["balance"], 20.0)

	def test_opening_balance_excluded_from_plain_adjustment_sum(self):
		employee = self._employee("2019-01-01")
		frappe.get_doc(
			{
				"doctype": "Leave Balance Adjustment",
				"employee": employee,
				"leave_year": 2026,
				"adjustment_days": 10,
				"is_opening_balance": 1,
				"balance_as_of_date": "2026-06-30",
				"reason": "Opening balance",
			}
		).insert(ignore_permissions=True).submit()
		frappe.get_doc(
			{
				"doctype": "Leave Balance Adjustment",
				"employee": employee,
				"leave_year": 2026,
				"adjustment_days": 3,
				"reason": "Correction",
			}
		).insert(ignore_permissions=True).submit()

		self.assertEqual(utils.get_leave_balance_adjustment(employee, 2026), 3.0)

	def test_opening_balance_requires_as_of_date(self):
		employee = self._employee("2019-01-01")
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Leave Balance Adjustment",
					"employee": employee,
					"leave_year": 2026,
					"adjustment_days": 15,
					"is_opening_balance": 1,
					"reason": "Missing as-of date",
				}
			).insert(ignore_permissions=True)

	def test_duplicate_opening_balance_is_rejected(self):
		employee = self._employee("2019-01-01")
		payload = {
			"doctype": "Leave Balance Adjustment",
			"employee": employee,
			"leave_year": 2026,
			"adjustment_days": 15,
			"is_opening_balance": 1,
			"balance_as_of_date": "2026-06-30",
			"reason": "Opening balance",
		}
		frappe.get_doc(dict(payload)).insert(ignore_permissions=True).submit()
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(dict(payload)).insert(ignore_permissions=True).submit()
