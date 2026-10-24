import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, getdate, nowdate

from saudi_hr.saudi_hr.test_support import make_qa_employee


class TestSaudiHourlyLeaveRequest(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		try:
			company = frappe.defaults.get_user_default("Company") or frappe.db.get_value("Company", {"is_group": 0}, "name") or frappe.db.get_value("Company", {}, "name")
		except Exception:
			company = frappe.db.get_value("Company", {"is_group": 0}, "name") or frappe.db.get_value("Company", {}, "name")
		self.employee = make_qa_employee(company, prefix="hourly")
		settings = frappe.get_single("Saudi HR Settings")
		settings.monthly_hour_leave_hours = 8
		settings.save(ignore_permissions=True)
		frappe.db.set_value("Employee", self.employee, "user_id", "hourly.test@example.com")
		frappe.db.set_value("Employee", self.employee, "date_of_joining", add_days(nowdate(), -400))

	def test_naming_series(self):
		doc = frappe.get_doc({
			"doctype": "Saudi Hourly Leave Request",
			"employee": self.employee,
			"leave_date": nowdate(),
			"from_time": "09:00:00",
			"to_time": "11:00:00",
			"reason": "test",
		})
		doc.insert(ignore_permissions=True)
		self.assertTrue(doc.name.startswith("HL"))

	def test_whole_hours_only(self):
		doc = frappe.get_doc({
			"doctype": "Saudi Hourly Leave Request",
			"employee": self.employee,
			"leave_date": nowdate(),
			"from_time": "09:00:00",
			"to_time": "10:30:00",
			"reason": "test",
		})
		self.assertRaises(frappe.ValidationError, doc.insert, ignore_permissions=True)
