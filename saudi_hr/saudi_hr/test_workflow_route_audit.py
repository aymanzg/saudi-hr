from types import SimpleNamespace
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from saudi_hr.saudi_hr import api as api_module


class TestWorkflowRouteAudit(FrappeTestCase):
	_fake_meta = type("Meta", (), {"is_submittable": 1})

	def _route_audit(self, workflow_key):
		with patch.object(api_module.frappe, "session", SimpleNamespace(user="Administrator")), patch.object(
			api_module.frappe.db, "exists", return_value=False
		), patch.object(api_module.frappe, "get_meta", return_value=self._fake_meta):
			return api_module.get_workflow_route_audit(workflow_key=workflow_key)

	def test_get_workflow_route_audit_extracts_annual_leave_route(self):
		audit = self._route_audit("annual_leave")

		self.assertEqual(len(audit), 1)
		self.assertEqual(
			[step["allowed_role"] for step in audit[0]["approval_route"][:-1]],
			["Employee Self Service", "Supervisor", "HR User", "HR Manager", "General Manager", "HR User"],
		)
		self.assertEqual(audit[0]["approval_route"][-1]["state"], "Completed")

	def test_get_workflow_route_audit_extracts_salary_adjustment_route(self):
		audit = self._route_audit("salary_adjustment")

		self.assertEqual(
			[step["allowed_role"] for step in audit[0]["approval_route"][:-1]],
			["Employee Self Service", "Supervisor", "HR User", "HR Manager", "General Manager", "HR User"],
		)
		self.assertEqual(audit[0]["approval_route"][-1]["state"], "Completed")

	def test_get_workflow_route_audit_extracts_termination_route(self):
		audit = self._route_audit("termination")

		self.assertEqual(
			[step["allowed_role"] for step in audit[0]["approval_route"][:-1]],
			["Employee Self Service", "Supervisor", "HR User", "HR Manager", "General Manager", "HR User"],
		)
		self.assertEqual(audit[0]["approval_route"][-1]["state"], "Completed")

	def test_rejections_are_alternate_transitions_not_part_of_the_route(self):
		with patch.object(api_module.frappe, "session", SimpleNamespace(user="Administrator")), patch.object(
			api_module.frappe.db, "exists", return_value=False
		), patch.object(api_module.frappe, "get_meta", return_value=self._fake_meta):
			audit = api_module.get_workflow_route_audit(workflow_key="annual_leave")

		route_states = [step["state"] for step in audit[0]["approval_route"]]
		self.assertNotIn("Rejected by Supervisor", route_states)
		alternate_actions = {step["action"] for step in audit[0]["alternate_transitions"]}
		self.assertTrue(
			{"Supervisor Reject", "HR Reject", "HR Manager Reject", "GM Reject"}.issubset(alternate_actions)
		)