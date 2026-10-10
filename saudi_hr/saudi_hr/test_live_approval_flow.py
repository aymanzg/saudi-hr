from unittest.mock import patch

import frappe
from erpnext.setup.doctype.employee.test_employee import make_employee
from frappe.model.workflow import apply_workflow
from frappe.tests.utils import FrappeTestCase


class TestLiveApprovalFlow(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.submitter_email = "saudi.leave.submitter@example.com"
		self.manager_email = "saudi.leave.manager@example.com"
		self.hr_user_email = "saudi.leave.hr.user@example.com"
		self.hr_manager_email = "saudi.leave.hr.manager@example.com"
		self.gm_email = "saudi.leave.gm@example.com"
		self.attach_print_patcher = patch("frappe.attach_print", return_value={})
		self.sendmail_patcher = patch("frappe.sendmail")
		self.attach_print_patcher.start()
		self.sendmail_patcher.start()
		frappe.set_user("Administrator")

		self._ensure_user(self.manager_email, "Supervisor", "Department Approver")
		self._ensure_user(self.submitter_email, "Employee Self Service")
		self._ensure_user(self.hr_user_email, "HR User")
		self._ensure_user(self.hr_manager_email, "HR Manager")
		self._ensure_user(self.gm_email, "General Manager")
		self.company = frappe.get_all("Company", pluck="name", limit_page_length=1)[0]

		self.manager_employee = make_employee(self.manager_email, company=self.company)
		self.employee = make_employee(self.submitter_email, company=self.company)

		# Role assignments must come after the employee records exist: ERPNext's
		# User validate hook strips Employee / Employee Self Service from any
		# user without a mapped Employee.
		frappe.get_doc("User", self.submitter_email).add_roles("Employee Self Service")
		frappe.get_doc("User", self.manager_email).add_roles("Supervisor", "Department Approver")
		frappe.get_doc("User", self.hr_user_email).add_roles("HR User")
		frappe.get_doc("User", self.hr_manager_email).add_roles("HR Manager")
		frappe.get_doc("User", self.gm_email).add_roles("General Manager")

		employee_doc = frappe.get_doc("Employee", self.employee)
		employee_doc.reports_to = self.manager_employee
		employee_doc.leave_approver = self.manager_email
		employee_doc.expense_approver = self.manager_email
		employee_doc.save()

	def tearDown(self):
		frappe.set_user("Administrator")
		self.attach_print_patcher.stop()
		self.sendmail_patcher.stop()
		frappe.db.rollback()
		super().tearDown()

	def test_annual_leave_workflow_runs_full_approval_chain(self):
		with patch(
			"saudi_hr.saudi_hr.doctype.saudi_annual_leave.saudi_annual_leave.get_annual_leave_balance",
			return_value={"balance": 21},
		):
			frappe.set_user(self.submitter_email)
			leave = frappe.get_doc(
				{
					"doctype": "Saudi Annual Leave",
					"employee": self.employee,
					"company": frappe.db.get_value("Employee", self.employee, "company"),
					"department": frappe.db.get_value("Employee", self.employee, "department"),
					"leave_start_date": "2026-05-10",
					"leave_end_date": "2026-05-12",
					"description": "Workflow path verification",
				}
			).insert()

			self.assertEqual(leave.workflow_state, "Draft")
			apply_workflow(leave, "Submit Request")
			leave.reload()
			self.assertEqual(leave.workflow_state, "Pending Supervisor Review")

			frappe.set_user(self.manager_email)
			self.assertTrue(frappe.has_permission("Saudi Annual Leave", "read", doc=leave))
			apply_workflow(leave, "Supervisor Approve")
			leave.reload()
			self.assertEqual(leave.workflow_state, "Pending HR Review")

			frappe.set_user(self.hr_user_email)
			self.assertTrue(frappe.has_permission("Saudi Annual Leave", "read", doc=leave))
			apply_workflow(leave, "HR Approve")
			leave.reload()
			self.assertEqual(leave.workflow_state, "Pending HR Manager Review")

			frappe.set_user(self.hr_manager_email)
			self.assertTrue(frappe.has_permission("Saudi Annual Leave", "read", doc=leave))
			apply_workflow(leave, "HR Manager Approve")
			leave.reload()
			self.assertEqual(leave.workflow_state, "Pending GM Review")

			frappe.set_user(self.gm_email)
			self.assertTrue(frappe.has_permission("Saudi Annual Leave", "read", doc=leave))
			apply_workflow(leave, "GM Approve")
			leave.reload()
			self.assertEqual(leave.workflow_state, "GM Approved")

			frappe.set_user(self.hr_user_email)
			apply_workflow(leave, "Mark Completed")
			leave.reload()

		self.assertEqual(leave.workflow_state, "Completed")
		self.assertEqual(leave.docstatus, 1)
		self.assertEqual(leave.status, "Approved / موافق عليها")
		self.assertEqual(leave.approved_by, self.hr_user_email)

	def test_leave_rejected_by_gm_resubmits_into_pending_gm_review(self):
		with patch(
			"saudi_hr.saudi_hr.doctype.saudi_annual_leave.saudi_annual_leave.get_annual_leave_balance",
			return_value={"balance": 21},
		):
			frappe.set_user(self.submitter_email)
			leave = frappe.get_doc(
				{
					"doctype": "Saudi Annual Leave",
					"employee": self.employee,
					"company": frappe.db.get_value("Employee", self.employee, "company"),
					"department": frappe.db.get_value("Employee", self.employee, "department"),
					"leave_start_date": "2026-05-20",
					"leave_end_date": "2026-05-21",
					"description": "Rejection path verification",
				}
			).insert()

			for action, actor in (
				("Submit Request", self.submitter_email),
				("Supervisor Approve", self.manager_email),
				("HR Approve", self.hr_user_email),
				("HR Manager Approve", self.hr_manager_email),
			):
				frappe.set_user(actor)
				apply_workflow(leave, action)
				leave.reload()

			frappe.set_user(self.gm_email)
			apply_workflow(leave, "GM Reject")
			leave.reload()
			self.assertEqual(leave.workflow_state, "Rejected by GM")
			self.assertEqual(leave.docstatus, 0)

			frappe.set_user(self.submitter_email)
			apply_workflow(leave, "Resubmit Request")
			leave.reload()
			self.assertEqual(leave.workflow_state, "Pending GM Review")
			self.assertEqual(leave.docstatus, 0)

	def _ensure_user(self, email, *roles):
		if frappe.db.exists("User", email):
			user = frappe.get_doc("User", email)
		else:
			user = frappe.get_doc(
				{
					"doctype": "User",
					"email": email,
					"first_name": email.split("@", 1)[0],
					"new_password": "N7!xP4@qR9#vT2$k",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)

		if roles:
			user.add_roles(*roles)

		return user