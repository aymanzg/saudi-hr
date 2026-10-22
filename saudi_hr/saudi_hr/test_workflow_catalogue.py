"""Unit tests for the workflow catalogue, the single source of truth.

These run against the pure builder/validator functions so they need neither a
live site nor the reconciled Workflow documents in the database.
"""
from frappe.tests.utils import FrappeTestCase

from saudi_hr.saudi_hr import workflow_catalogue as wf

ALL_DOCTYPES = wf.WORKFLOW_DOCUMENT_TYPES
ROLES = set(wf.SUBMIT_ROLES) | set(wf.EXECUTOR_ROLES) | set(wf.CHAIN_ROLES)


def submittable_map(submittable) -> dict:
	return {doctype: submittable for doctype in ALL_DOCTYPES}


def built_all(submittable=True) -> dict:
	"""Build the whole catalog without touching live Doctype meta."""
	return {dt: wf.build_workflow(dt, is_submittable=submittable) for dt in ALL_DOCTYPES}


class TestWorkflowCatalogue(FrappeTestCase):
	def test_one_workflow_per_doctype_with_canonical_shapes(self):
		workflows = built_all()
		self.assertEqual(set(workflows), set(ALL_DOCTYPES))
		for doctype, workflow in workflows.items():
			self.assertEqual(workflow["document_type"], doctype)
			self.assertEqual(workflow["is_active"], 1)
			states = {row["state"] for row in workflow["states"]}
			if doctype == "Termination Notice":
				# HR-driven: no employee submitter, no supervisor leg.
				self.assertEqual(
					states,
					set(wf.ALL_STATES) - {"Pending Supervisor Review", "Rejected by Supervisor"},
				)
				self.assertEqual(len(workflow["states"]), 10)
				self.assertEqual(len(workflow["transitions"]), 16)
				continue
			if doctype in wf.AUTO_COMPLETE_ON_GM_APPROVAL:
				# GM approval is terminal: no "GM Approved" holding state and no
				# "Mark Completed" follow-up transition.
				self.assertEqual(states, set(wf.ALL_STATES) - {"GM Approved"})
				self.assertEqual(len(workflow["states"]), 11)
				self.assertEqual(len(workflow["transitions"]), 18)
				continue
			self.assertEqual(states, set(wf.ALL_STATES))
			self.assertEqual(len(workflow["states"]), 12)
			self.assertEqual(len(workflow["transitions"]), 20)

	def test_gm_approval_completes_the_punch_correction(self):
		workflow = wf.build_workflow("Saudi Punch Correction", is_submittable=True)
		states = [row["state"] for row in workflow["states"]]
		actions = [t["action"] for t in workflow["transitions"]]

		self.assertNotIn("GM Approved", states)
		self.assertNotIn("Mark Completed", actions)

		gm_approvals = [t for t in workflow["transitions"] if t["action"] == "GM Approve"]
		self.assertTrue(gm_approvals)
		for transition in gm_approvals:
			self.assertEqual(transition["state"], "Pending GM Review")
			self.assertEqual(transition["next_state"], wf.TERMINAL_STATE)
			self.assertEqual(transition["allowed"], wf.GM_ROLE)

		terminal = next(row for row in workflow["states"] if row["state"] == wf.TERMINAL_STATE)
		self.assertEqual(terminal["doc_status"], "1")

	def test_other_doctypes_keep_the_gm_approved_handoff(self):
		workflow = wf.build_workflow("Saudi Annual Leave", is_submittable=True)
		states = [row["state"] for row in workflow["states"]]
		actions = [t["action"] for t in workflow["transitions"]]

		self.assertIn("GM Approved", states)
		self.assertIn("Mark Completed", actions)
		gm_approve = next(t for t in workflow["transitions"] if t["action"] == "GM Approve")
		self.assertEqual(gm_approve["next_state"], "GM Approved")
		mark_completed = next(t for t in workflow["transitions"] if t["action"] == "Mark Completed")
		self.assertEqual(mark_completed["state"], "GM Approved")
		self.assertEqual(mark_completed["next_state"], wf.TERMINAL_STATE)


	def test_terminal_doc_status_tracks_submittability(self):
		for doctype in ALL_DOCTYPES:
			submittable = wf.build_workflow(doctype, is_submittable=True)
			terminal = {r["state"]: r["doc_status"] for r in submittable["states"]}
			self.assertEqual(terminal[wf.TERMINAL_STATE], "1")
			self.assertEqual(terminal[wf.CANCELLED_STATE], "2")

			not_submittable = wf.build_workflow(doctype, is_submittable=False)
			terminal = {r["state"]: r["doc_status"] for r in not_submittable["states"]}
			self.assertEqual(terminal[wf.TERMINAL_STATE], "0")
			self.assertEqual(terminal[wf.CANCELLED_STATE], "0")

	def test_submission_allows_self_approval_but_no_approval_step_does(self):
		workflow = wf.build_workflow("Saudi Annual Leave", is_submittable=True)
		by_action = {}
		for transition in workflow["transitions"]:
			by_action.setdefault(transition["action"], []).append(transition)
		for action in ("Submit Request", "Resubmit Request"):
			self.assertTrue(all(t["allow_self_approval"] for t in by_action[action]), action)
		for action in (
			"Supervisor Approve",
			"Supervisor Reject",
			"HR Approve",
			"HR Reject",
			"HR Manager Approve",
			"HR Manager Reject",
			"GM Approve",
			"GM Reject",
			"Mark Completed",
		):
			self.assertTrue(all(not t["allow_self_approval"] for t in by_action[action]), action)

	def test_termination_notice_submission_is_hr_only(self):
		workflow = wf.build_workflow("Termination Notice", is_submittable=True)
		submit_allowed = {
			t["allowed"]
			for t in workflow["transitions"]
			if t["action"] in wf.SUBMIT_ACTIONS
		}
		self.assertEqual(submit_allowed, {"HR User", "HR Manager"})

		for doctype in ALL_DOCTYPES:
			if doctype == "Termination Notice":
				continue
			other = wf.build_workflow(doctype, is_submittable=True)
			allowed = {
				t["allowed"] for t in other["transitions"] if t["action"] in wf.SUBMIT_ACTIONS
			}
			self.assertEqual(allowed, set(wf.SUBMIT_ROLES), doctype)

	def test_resubmit_returns_to_the_same_level_that_rejected(self):
		workflow = wf.build_workflow("Saudi Annual Leave", is_submittable=True)
		transitions = workflow["transitions"]
		for rejected, review in (
			("Rejected by Supervisor", "Pending Supervisor Review"),
			("Rejected by HR", "Pending HR Review"),
			("Rejected by HR Manager", "Pending HR Manager Review"),
			("Rejected by GM", "Pending GM Review"),
		):
			next_states = {
				t["next_state"]
				for t in transitions
				if t["action"] == "Resubmit Request" and t["state"] == rejected
			}
			self.assertEqual(next_states, {review})

	def test_validate_passes_and_rejects_missing_roles(self):
		wf.validate_workflow_catalogue(is_submittable=submittable_map(True), expected_roles=ROLES)
		with self.assertRaises(AssertionError):
			wf.validate_workflow_catalogue(
				is_submittable=submittable_map(True),
				expected_roles=ROLES - {"Supervisor"},
			)

	def test_workflow_vocabulary_is_english_only(self):
		for workflow in built_all().values():
			wf._assert_no_bilingual(workflow)

	def test_state_bucket_covers_every_known_state(self):
		for state in wf.ALL_STATES:
			self.assertIsNotNone(wf.state_bucket(state), state)
		self.assertEqual(wf.state_bucket("Draft"), "draft")
		self.assertEqual(wf.state_bucket("Pending HR Review"), "pending")
		self.assertEqual(wf.state_bucket("GM Approved"), "approved")
		self.assertEqual(wf.state_bucket("Completed"), "approved")
		self.assertEqual(wf.state_bucket("Rejected by HR Manager"), "rejected")
		self.assertEqual(wf.state_bucket("Cancelled"), "cancelled")
		self.assertEqual(wf.state_bucket("مرفوض من المدير"), "rejected")
		self.assertIsNone(wf.state_bucket(""))
		self.assertIsNone(wf.state_bucket(None))

	def test_role_labels_are_arabic_for_the_chain_roles(self):
		self.assertEqual(wf.role_label("Supervisor"), "المشرف")
		self.assertTrue("المدير العام" in wf.role_label("General Manager"))
		self.assertTrue("مدير الموارد البشرية" in wf.role_label("HR Manager"))
		self.assertEqual(wf.role_label("HR User"), "اخصائي العمليات")
		self.assertEqual(wf.role_label("Executive DIRECTOR"), "Executive DIRECTOR")


class TestBackfillTargets(FrappeTestCase):
	def test_legacy_states_map_onto_the_new_chain(self):
		for legacy, expected in (
			("Draft", "Draft"),
			("ملغى / Cancelled", "Cancelled"),
			("Pending Manager Approval", "Pending Supervisor Review"),
			("Pending HR Approval", "Pending HR Review"),
			("Pending Finance Approval", "Pending HR Review"),
			("Approved", "Completed"),
			("Closed", "Completed"),
			("Decided", "Completed"),
			("Resolved", "Completed"),
			("مرفوض / Rejected", "Rejected by Supervisor"),
			("Cancelled", "Cancelled"),
		):
			self.assertEqual(wf._backfill_target(legacy), expected, legacy)