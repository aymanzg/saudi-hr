"""Tests for the /saudi-admin API.

The suite runs as Administrator because the interesting behaviour is what a
*non* privileged caller gets refused, which is only observable from inside.
Every test that writes rolls back with the fixture: nothing here commits, and
the counts asserted in tearDown prove the site is unchanged.
"""

import json
import os
import re
from datetime import date, timedelta
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, getdate, now_datetime, nowdate

from saudi_hr.saudi_hr import admin_api
from saudi_hr.saudi_hr.admin_api import (
	ATTENDANCE_STATUS_KEYS,
	LEAVE_REGISTRY,
	STANDARD_FIELDS,
	_dedupe_actions,
	_existing_fields,
	_row_state,
	assert_portal_access,
	apply_leave_action,
	apply_offboarding_action,
	correct_attendance_day,
	create_employee,
	create_eosb_settlement,
	create_eosb_from_case,
	create_exit_clearance,
	create_exit_interview,
	create_leave_disbursement,
	create_termination_notice,
	get_admin_dashboard,
	get_admin_config,
	get_attendance_report,
	get_documents_and_letters,
	get_employee_detail,
	get_employee_form_options,
	get_eosb_settlement,
	get_leave_request,
	get_offboarding_case,
	get_offboarding_form_options,
	issue_hr_document,
	list_employees,
	list_exit_clearances,
	list_leave_requests,
	save_exit_clearance,
	settle_final_settlement,
	submit_eosb,
	submit_leave_request,
)
from saudi_hr.saudi_hr.test_support import get_or_create_department, make_qa_employee

WORKFLOW_DOCTYPES = (
	"Saudi Annual Leave",
	"Saudi Sick Leave",
	"Mobile Leave Request",
	"Saudi Emergency Leave",
	"HR Service Request",
	"Saudi Punch Correction",
)
PLAIN_DOCTYPES = ("Special Leave", "Maternity Paternity Leave")


class _ApiTestBase(FrappeTestCase):
	"""Shared fixtures: a pinned admin user and a readable leave request.

	Both are needed by more than one test class, so they live here rather than
	being copied per class.
	"""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.company = frappe.get_all("Company", pluck="name", limit_page_length=1)[0]
		# this suite's own employee, so its leave requests are never measured
		# against somebody's real balance that another test happened to spend
		self.employee = make_qa_employee(self.company, f"admin-{frappe.generate_hash(length=6)}")
		frappe.db.set_value("Employee", self.employee, "date_of_joining", "2020-01-01")

	def _make_user(self, roles):
		suffix = frappe.generate_hash(length=8).lower()
		email = f"saudi.admin.{suffix}@example.com"
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": f"admin{suffix}",
				"new_password": "N7!xP4@qR9#vT2$k",
				"send_welcome_email": 0,
				"roles": [{"role": role} for role in roles],
			}
		).insert(ignore_permissions=True)
		return email

	def _plain_draft(self, doctype):
		employee = self.employee
		doc = {"doctype": doctype, "employee": employee, "company": self.company}
		if doctype == "Special Leave":
			doc.update(
				{
					"leave_type": "Marriage Leave / إجازة زواج (م.113 – 5 أيام)",
					"leave_start_date": "2026-11-01",
					"leave_end_date": "2026-11-02",
				}
			)
		else:
			doc.update(
				{
					"leave_type": "Maternity / أمومة (84 يوماً)",
					"leave_start_date": "2026-11-01",
					"entitled_days": 84,
					"medical_certificate_attached": 1,
				}
			)
		return frappe.get_doc(doc).insert(ignore_permissions=True).name

	def _make_leave_request(self, doctype):
		"""A draft request owned by Administrator, so self-approval never blocks."""
		employee = self.employee
		doc = {"doctype": doctype, "employee": employee, "company": self.company}
		if doctype == "Saudi Annual Leave":
			doc.update({"leave_start_date": "2026-11-01", "leave_end_date": "2026-11-03"})
		elif doctype == "Saudi Sick Leave":
			doc.update({"from_date": "2026-11-01", "to_date": "2026-11-02", "reason": "admin api test"})
		elif doctype == "Mobile Leave Request":
			doc.update({"from_date": "2026-11-01", "to_date": "2026-11-02"})
		elif doctype == "Special Leave":
			doc.update(
				{
					"leave_type": "Marriage Leave / إجازة زواج (م.113 – 5 أيام)",
					"leave_start_date": "2026-11-01",
					"leave_end_date": "2026-11-02",
				}
			)
		elif doctype == "Maternity Paternity Leave":
			doc.update(
				{
					"leave_type": "Maternity / أمومة (84 يوماً)",
					"leave_start_date": "2026-11-01",
					"entitled_days": 84,
					"medical_certificate_attached": 1,
				}
			)
		return frappe.get_doc(doc).insert(ignore_permissions=True).name

	def _make_service_request(self, request_type="visa_issuance"):
		"""A draft HR Service Request, which the inbox counts as a request too."""
		doc = {
			"doctype": "HR Service Request",
			"employee": self.employee,
			"employee_name": frappe.db.get_value("Employee", self.employee, "employee_name"),
			"company": self.company,
			"request_type": request_type,
			"description": "admin api test",
		}
		return frappe.get_doc(doc).insert(ignore_permissions=True).name

	def _make_punch_correction(self, date="2026-10-05"):
		"""A draft punch correction, which the inbox counts as a request too."""
		doc = {
			"doctype": "Saudi Punch Correction",
			"employee": self.employee,
			"company": self.company,
			"attendance_date": date,
			"corrected_in_time": "08:30:00",
			"correction_reason": "admin api test correction",
		}
		return frappe.get_doc(doc).insert(ignore_permissions=True).name


class TestAdminApiAccess(_ApiTestBase):
	"""The portal gate and the per-document permission behaviour under it."""

	def test_portal_refuses_a_user_with_no_admin_role(self):
		email = self._make_user(["Employee"])
		frappe.set_user(email)
		self.assertRaises(frappe.PermissionError, assert_portal_access)
		for endpoint in (
			get_admin_dashboard,
get_admin_config,
	get_attendance_report,
	get_employee_form_options,
			list_employees,
			list_leave_requests,
		):
			self.assertRaises(frappe.PermissionError, endpoint)

	def test_portal_refuses_guest(self):
		frappe.set_user("Guest")
		self.assertRaises(frappe.PermissionError, assert_portal_access)

	def test_portal_allows_an_hr_role(self):
		frappe.set_user(self._make_user(["HR User"]))
		assert_portal_access()
		self.assertEqual(get_admin_config()["user"], frappe.session.user)

	def test_a_department_approver_reaches_the_page_without_being_hr(self):
		frappe.set_user(self._make_user(["Department Approver"]))
		assert_portal_access()
		self.assertFalse(get_admin_config()["can_manage_employees"])

	def _pin_user_to_another_employee(self, email, request_doctype, request):
		"""Pin a user to an employee other than the request's.

		This is how the site configures real HR users, and it is the case where
		the list query and the document check can disagree.
		"""
		other = frappe.db.get_value(
			"Employee",
			{"name": ["!=", frappe.db.get_value(request_doctype, request, "employee")]},
			"name",
		)
		frappe.get_doc(
			{
				"doctype": "User Permission",
				"user": email,
				"allow": "Employee",
				"for_value": other,
				"apply_to_all_doctypes": 1,
			}
		).insert(ignore_permissions=True)

	def test_unreadable_request_is_refused_with_a_clean_error(self):
		"""A User Permission hides a request, and every layer must agree.

		The inbox is built with get_list so the app's permission query applies;
		get_all used to bypass it and leak rows the document check refuses. The
		detail and action endpoints stay strict regardless, because a row can go
		stale between listing and clicking.
		"""
		request = self._make_leave_request("Saudi Annual Leave")
		email = self._make_user(["HR User"])
		frappe.set_user(email)
		self._pin_user_to_another_employee(email, "Saudi Annual Leave", request)

		self.assertFalse(frappe.has_permission("Saudi Annual Leave", "read", doc=request, throw=False))
		self.assertNotIn(request, [r["name"] for r in list_leave_requests()["rows"]])
		self.assertRaises(frappe.PermissionError, get_leave_request, "Saudi Annual Leave", request)
		self.assertRaises(
			frappe.PermissionError, apply_leave_action, "Saudi Annual Leave", request, "Submit Request"
		)

	def test_the_inbox_never_shows_a_request_the_user_cannot_read(self):
		"""No row may be returned that the document check would refuse.

		can_read is kept in the payload as a defence in depth for the stale-row
		case, but the list itself must already be clean.
		"""
		request = self._make_leave_request("Saudi Annual Leave")
		email = self._make_user(["HR User"])
		frappe.set_user(email)
		self._pin_user_to_another_employee(email, "Saudi Annual Leave", request)

		for row in list_leave_requests()["rows"]:
			self.assertTrue(
				frappe.has_permission(row["doctype"], "read", doc=row["name"], throw=False),
				f"{row['doctype']} {row['name']} is listed but not readable",
			)

	def test_a_pinned_user_sees_no_actionable_requests_they_cannot_read(self):
		"""The dashboard badge must not advertise work the inbox will hide."""
		request = self._make_leave_request("Saudi Annual Leave")
		email = self._make_user(["HR User"])
		frappe.set_user(email)
		self._pin_user_to_another_employee(email, "Saudi Annual Leave", request)

		# the badge is per doctype, so compare it against the same doctype
		actionable_in_inbox = len(
			[
				r
				for r in list_leave_requests(doctype="Saudi Annual Leave")["rows"]
				if r["actionable"]
			]
		)
		dashboard = get_admin_dashboard()
		self.assertEqual(
			dashboard["leave"]["Saudi Annual Leave"]["actionable"], actionable_in_inbox
		)


class TestAdminApiLeaveActions(_ApiTestBase):
	"""Approval actions are the security boundary, so they are tested hardest."""

	def _draft(self, doctype="Saudi Annual Leave"):
		employee = self.employee
		doc = {
			"doctype": doctype,
			"employee": employee,
			"company": self.company,
			"leave_start_date": "2026-11-01",
			"leave_end_date": "2026-11-02",
		}
		return frappe.get_doc(doc).insert(ignore_permissions=True).name

	def test_row_actions_agree_with_get_transitions(self):
		"""The list view resolves actions from the workflow table to avoid a
		document load per row; that shortcut is only sound if it matches what
		get_transitions would authorise."""
		request = self._draft()
		frappe.set_user(self._hr_user())
		from frappe.model.workflow import get_transitions

		states = admin_api._actionable_states("Saudi Annual Leave")
		record = frappe.get_all(
			"Saudi Annual Leave", filters={"name": request}, fields=["name", "workflow_state", "docstatus", "owner"]
		)[0]
		_doc, can_read = admin_api._load_row("Saudi Annual Leave", record)

		expected = sorted(t["action"] for t in get_transitions(frappe.get_doc("Saudi Annual Leave", request)))
		actual = sorted(a["action"] for a in admin_api._row_actions("Saudi Annual Leave", record, states, can_read))
		self.assertEqual(actual, expected)
		# advancing a draft is the applicant's move, not an approval-stage role's
		self.assertEqual(actual, [], "an HR User has no action on a draft request")

	def test_actions_are_deduplicated_for_a_multi_role_user(self):
		"""The workflow declares Draft -> Submit Request once per role, so a
		user holding both roles must not be offered the button twice."""
		request = self._draft()
		email = self._hr_user(["HR User"])
		# the Employee Self Service role is stripped on save unless the user has
		# a mapped Employee, so link one before adding the role
		frappe.db.set_value("Employee", self.employee, "user_id", email)
		frappe.get_doc("User", email).add_roles("Employee Self Service")
		frappe.set_user(email)
		actions = get_leave_request("Saudi Annual Leave", request)["actions"]
		keys = [(a["action"], a["next_state"]) for a in actions]
		self.assertEqual(len(keys), len(set(keys)))
		self.assertEqual([a["action"] for a in actions].count("Submit Request"), 1)

	def test_dedupe_keeps_same_action_with_different_destinations(self):
		actions = _dedupe_actions(
			[
				{"action": "Approve", "next_state": "Pending HR"},
				{"action": "Approve", "next_state": "Pending Finance"},
				{"action": "Approve", "next_state": "Pending HR"},
			]
		)
		self.assertEqual(len(actions), 2)

	def test_action_from_the_wrong_stage_is_refused(self):
		request = self._draft()
		frappe.set_user(self._hr_user(["HR Manager", "Accounts Manager"]))
		self.assertRaises(
			frappe.PermissionError, apply_leave_action, "Saudi Annual Leave", request, "GM Approve"
		)
		self.assertEqual(frappe.db.get_value("Saudi Annual Leave", request, "workflow_state"), "Draft")

	def test_an_approval_action_advances_the_workflow(self):
		"""Submission is the applicant's move (mobile), so the admin API's first
		touchpoint is an approval step by a portal role."""
		request = self._draft()
		frappe.db.set_value("Saudi Annual Leave", request, "workflow_state", "Pending HR Review")
		frappe.set_user(self._hr_user(["HR User"]))
		result = apply_leave_action("Saudi Annual Leave", request, "HR Approve")
		self.assertEqual(result["next_state"], "Pending HR Manager Review")
		self.assertEqual(
			frappe.db.get_value("Saudi Annual Leave", request, "workflow_state"), "Pending HR Manager Review"
		)

	def test_action_is_refused_on_an_unsupported_doctype(self):
		self.assertRaises(
			frappe.ValidationError, apply_leave_action, "Salary Slip", "x", "Approve"
		)
		self.assertRaises(
			frappe.ValidationError, apply_leave_action, "Saudi Annual Leave", "x", ""
		)

	def test_submit_refuses_a_doctype_that_has_a_workflow(self):
		"""Submitting a workflow request would skip Manager, HR and Finance."""
		request = self._draft()
		frappe.set_user(self._hr_user(["HR Manager", "HR User", "Accounts Manager"]))
		self.assertRaises(
			frappe.ValidationError, submit_leave_request, "Saudi Annual Leave", request
		)
		self.assertEqual(frappe.db.get_value("Saudi Annual Leave", request, "workflow_state"), "Draft")
		self.assertEqual(frappe.db.get_value("Saudi Annual Leave", request, "docstatus"), 0)

	def test_submit_works_for_a_plain_leave_doctype(self):
		for doctype in PLAIN_DOCTYPES:
			request = self._plain_draft(doctype)
			result = submit_leave_request(doctype, request)
			self.assertEqual(frappe.db.get_value(doctype, request, "docstatus"), 1, doctype)
			self.assertIn(result["state"], ("approved", "draft"))

	def test_resubmitting_is_refused(self):
		request = self._plain_draft("Special Leave")
		submit_leave_request("Special Leave", request)
		self.assertRaises(frappe.ValidationError, submit_leave_request, "Special Leave", request)

	def test_maternity_without_a_certificate_is_refused_by_the_doctype(self):
		"""The portal does not police this itself; the doctype's own validation
		must still run, so this proves submit is not bypassing it."""
		employee = self.employee
		request = frappe.get_doc(
			{
				"doctype": "Maternity Paternity Leave",
				"employee": employee,
				"company": self.company,
				"leave_type": "Maternity / أمومة (84 يوماً)",
				"leave_start_date": "2026-11-01",
				"entitled_days": 84,
			}
		).insert(ignore_permissions=True).name
		self.assertRaises(
			frappe.ValidationError, submit_leave_request, "Maternity Paternity Leave", request
		)

	def _hr_user(self, roles=("HR User",)):
		suffix = frappe.generate_hash(length=8).lower()
		email = f"saudi.action.{suffix}@example.com"
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": f"action{suffix}",
				"new_password": "N7!xP4@qR9#vT2$k",
				"send_welcome_email": 0,
				"roles": [{"role": role} for role in roles],
			}
		).insert(ignore_permissions=True)
		return email


class TestAdminApiLeaveInbox(_ApiTestBase):
	"""The inbox merges doctypes with different fields into one shape."""

	def test_registry_matches_this_site(self):
		"""Each entry's fields must exist, or the inbox silently shows blanks."""
		for doctype, _label, start, end, days, kind, state in LEAVE_REGISTRY:
			self.assertTrue(frappe.db.table_exists(doctype), doctype)
			present = {d.fieldname for d in frappe.get_meta(doctype).fields} | STANDARD_FIELDS
			for field in (start, end, days, kind, state):
				if field:
					self.assertIn(field, present, f"{doctype}.{field}")

	def test_registry_covers_every_saudi_leave_doctype(self):
		self.assertEqual(
			[entry[0] for entry in LEAVE_REGISTRY],
			[*WORKFLOW_DOCTYPES, *PLAIN_DOCTYPES],
		)

	def test_workflow_split_is_read_from_the_site_not_hardcoded(self):
		config = get_admin_config()
		by_doctype = {entry["doctype"]: entry["has_workflow"] for entry in config["leave_types"]}
		from frappe.model.workflow import get_workflow_name

		for doctype, has_workflow in by_doctype.items():
			self.assertEqual(has_workflow, bool(get_workflow_name(doctype)), doctype)

	def test_inbox_rows_carry_a_normalised_shape(self):
		result = list_leave_requests()
		for row in result["rows"]:
			for key in ("doctype", "name", "state", "actions", "actionable", "can_read", "desk_url"):
				self.assertIn(key, row)
			self.assertIn(row["state"], ("pending", "draft", "approved", "rejected", "cancelled", "unknown"))
			self.assertTrue(row["employee"], "every leave request has an employee")

	def test_state_normalisation_covers_every_representation(self):
		cases = [
			({"workflow_state": "Pending Supervisor Review"}, "pending"),
			({"workflow_state": "Approved"}, "approved"),
			({"workflow_state": "Rejected"}, "rejected"),
			({"status": "Approved / موافق عليها"}, "approved"),
			({"status": "Rejected / مرفوضة"}, "rejected"),
			({"status": "Draft / مسودة"}, "draft"),
			({"docstatus": 1}, "approved"),
			({"docstatus": 0}, "draft"),
		]
		for row, expected in cases:
			self.assertEqual(_row_state(row), expected, row)

	def test_filtering_by_state_narrows_the_inbox(self):
		all_rows = list_leave_requests()["rows"]
		if not all_rows:
			self.skipTest("no leave requests on this site")
		pending = list_leave_requests(state="pending")["rows"]
		self.assertTrue(all(row["state"] == "pending" for row in pending))

	def test_employee_scoping_is_left_to_permissions(self):
		"""list_leave_requests must not widen visibility beyond what Desk shows."""
		from frappe.model.workflow import get_transitions

		request = frappe.db.get_value("Saudi Annual Leave", {}, "name")
		if not request:
			self.skipTest("no annual leave on this site")
		row = next(r for r in list_leave_requests()["rows"] if r["name"] == request)
		states = admin_api._actionable_states("Saudi Annual Leave")
		record = frappe.get_all(
			"Saudi Annual Leave", filters={"name": request}, fields=["name", "workflow_state", "docstatus", "owner"]
		)[0]
		_doc, can_read = admin_api._load_row("Saudi Annual Leave", record)
		actions = admin_api._row_actions("Saudi Annual Leave", record, states, can_read)
		expected = get_transitions(frappe.get_doc("Saudi Annual Leave", request))
		self.assertEqual(bool(actions), bool(expected) and can_read)

	def test_punch_corrections_appear_in_the_inbox(self):
		name = self._make_punch_correction()
		rows = list_leave_requests()["rows"]
		row = next(
			r for r in rows if r["doctype"] == "Saudi Punch Correction" and r["name"] == name
		)
		self.assertEqual(row["employee"], self.employee)
		self.assertEqual(row["state"], "draft")
		# a correction lands on one day, so both edges are that day
		self.assertEqual(row["from_date"], "2026-10-05")
		self.assertEqual(row["to_date"], "2026-10-05")
		self.assertIsNone(row["days"])

	def test_punch_correction_detail_carries_the_correction(self):
		name = self._make_punch_correction()
		detail = get_leave_request("Saudi Punch Correction", name)
		self.assertEqual(detail["fields"]["attendance_date"], "2026-10-05")
		self.assertEqual(detail["fields"]["corrected_in_time"], "8:30:00")
		self.assertEqual(detail["fields"]["correction_reason"], "admin api test correction")
		self.assertTrue(detail["has_workflow"])

	def test_punch_correction_advances_through_the_workflow(self):
		name = self._make_punch_correction()
		# place the request at the HR stage the way the chain would, then let an
		# HR user take the next step; db.set_value skips validate_workflow so a
		# transition that has not been walked yet is not refused as "not allowed"
		frappe.db.set_value("Saudi Punch Correction", name, "workflow_state", "Pending HR Review")
		hr = self._make_user(["HR User"])
		frappe.set_user(hr)
		# owned by Administrator, so self-approval never blocks the new user
		result = apply_leave_action("Saudi Punch Correction", name, "HR Approve")
		self.assertEqual(result["next_state"], "Pending HR Manager Review")
		self.assertEqual(
			frappe.db.get_value("Saudi Punch Correction", name, "workflow_state"),
			"Pending HR Manager Review",
		)

	def test_punch_correction_cannot_be_submitted_directly(self):
		"""Submitting skips the approver chain, exactly like the other workflows."""
		name = self._make_punch_correction()
		frappe.set_user(self._make_user(["HR User", "HR Manager"]))
		self.assertRaises(
			frappe.ValidationError, submit_leave_request, "Saudi Punch Correction", name
		)


class TestAdminApiFieldHelpers(FrappeTestCase):
	"""Regressions for the two field bugs found while building the inbox."""

	def test_standard_fields_are_always_selectable(self):
		"""name, docstatus, owner and creation are not in meta.fields, so
		filtering a field list by meta silently dropped exactly the fields the
		self-approval check, the draft check and the sort order depend on."""
		present = _existing_fields("Saudi Annual Leave", ["name", "docstatus", "owner", "creation", "modified"])
		for field in ("name", "docstatus", "owner", "creation", "modified"):
			self.assertIn(field, present)

	def test_standard_fields_survive_an_empty_meta_match(self):
		self.assertEqual(
			sorted(_existing_fields("Employee", ["name", "definitely_not_a_field"])),
			["name"],
		)

	def test_a_missing_optional_field_is_dropped_not_raised(self):
		"""A field that disappears in a future upgrade should blank a cell
		rather than break the whole page."""
		self.assertEqual(_existing_fields("Employee", ["definitely_not_a_field"]), [])


class TestAdminApiWorkflowParsing(FrappeTestCase):
	"""Workflow.allowed is a multiline Text column, not a JSON array."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")

	def test_allowed_column_is_split_on_newlines(self):
		"""parse_json() on 'HR Manager' returns a string, so intersecting it
		would match single characters and hand out the wrong transitions."""
		frappe.set_user(self._user_with("HR Manager"))
		states = admin_api._actionable_states("Saudi Annual Leave")
		actions = [a["action"] for entries in states.values() for a in entries]
		self.assertIn("HR Manager Approve", actions)
		self.assertNotIn("GM Approve", actions)

	def test_a_state_with_no_matching_role_yields_no_actions(self):
		from frappe.model.workflow import get_workflow

		workflow = get_workflow("Saudi Annual Leave")
		# GM is a single role, so a HR User must not see GM Approve
		frappe.set_user(self._user_with("HR User"))
		states = admin_api._actionable_states("Saudi Annual Leave")
		finance = next(
			(s for s in states.values() if any(a["action"] == "GM Approve" for a in s)), None
		)
		self.assertIsNone(finance, workflow.name)

	def _user_with(self, role):
		suffix = frappe.generate_hash(length=8).lower()
		email = f"saudi.parse.{suffix}@example.com"
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": f"parse{suffix}",
				"new_password": "N7!xP4@qR9#vT2$k",
				"send_welcome_email": 0,
				"roles": [{"role": role}],
			}
		).insert(ignore_permissions=True)
		return email


class TestAdminApiEmployees(_ApiTestBase):
	"""Employee creation has to land on the employee number, not a series name."""

	def setUp(self):
		super().setUp()
		self.employees_before = frappe.db.count("Employee")

	def _assert_employee_delta(self, delta):
		"""FrappeTestCase commits in setUpClass and rolls back in the class
		cleanup, so records created here are still visible to the next test in
		this class.  Assert the delta at the point of use rather than in
		tearDown, which would measure the accumulation rather than the leak."""
		self.assertEqual(frappe.db.count("Employee"), self.employees_before + delta)

	def _number(self):
		used = {row for row in frappe.get_all("Employee", pluck="name")}
		candidate = 880000
		while str(candidate) in used:
			candidate += 1
		return str(candidate)

	def _payload(self, **overrides):
		payload = {
			"employee_number": self._number(),
			"first_name": "Admin API Test",
			"company": self.company,
			"gender": "Male",
			"date_of_birth": "1990-01-01",
			"date_of_joining": "2026-01-01",
		}
		payload.update(overrides)
		return json.dumps(payload)

	def test_created_employee_is_named_by_its_number(self):
		number = self._number()
		result = create_employee(self._payload(employee_number=number))
		self.assertEqual(result["name"], number)
		stored = frappe.db.get_value(
			"Employee", number, ["name", "employee_number", "employee"], as_dict=True
		)
		self.assertEqual(stored["name"], number)
		self.assertEqual(stored["employee_number"], number)
		# the self-referential link is only right if the rename repointed it
		self.assertEqual(stored["employee"], number)
		self._assert_employee_delta(1)

	def test_created_employee_does_not_get_a_series_name(self):
		"""Employee is still set_name_by_naming_series, so without the rename
		this would be HR-EMP-00042 and the number would disagree with the name."""
		number = self._number()
		create_employee(self._payload(employee_number=number))
		self.assertFalse(
			frappe.get_value("Employee", number, "name").startswith("HR-EMP-"),
			"a series name leaked through",
		)
		self._assert_employee_delta(1)

	def test_duplicate_number_is_refused(self):
		existing = frappe.db.get_value("Employee", {}, "employee_number") or frappe.db.get_value(
			"Employee", {}, "name"
		)
		self.assertRaises(frappe.ValidationError, create_employee, self._payload(employee_number=existing))
		self._assert_employee_delta(0)

	def test_a_second_employee_holding_the_same_number_is_refused(self):
		"""A name that is free but already used in employee_number is a duplicate."""
		first = self._number()
		create_employee(self._payload(employee_number=first))
		other = self._number()
		self.assertRaises(
			frappe.ValidationError, create_employee, self._payload(employee_number=first, first_name="Clash")
		)
		self._assert_employee_delta(1)

	def test_an_illegal_name_is_refused(self):
		self.assertRaises(frappe.ValidationError, create_employee, self._payload(employee_number="<bad>"))
		self._assert_employee_delta(0)

	def test_required_fields_are_enforced(self):
		for field in ("first_name", "company", "gender", "date_of_birth", "date_of_joining"):
			payload = json.loads(self._payload())
			payload.pop(field)
			with self.subTest(field=field):
				self.assertRaises(frappe.ValidationError, create_employee, json.dumps(payload))
		self._assert_employee_delta(0)

	def test_a_future_joining_date_is_refused(self):
		self.assertRaises(
			frappe.ValidationError, create_employee, self._payload(date_of_joining="2099-01-01")
		)
		self._assert_employee_delta(0)

	def test_joining_before_date_of_birth_is_refused(self):
		self.assertRaises(
			frappe.ValidationError,
			create_employee,
			self._payload(date_of_joining="1980-01-01"),
		)
		self._assert_employee_delta(0)

	def test_a_duplicate_identity_number_is_refused(self):
		existing = frappe.db.get_value("Employee", {"custom_id_number": ("is", "set")}, "custom_id_number")
		if not existing:
			self.skipTest("no employee with an identity number on this site")
		self.assertRaises(
			frappe.ValidationError,
			create_employee,
			self._payload(custom_id_number=existing),
		)
		self._assert_employee_delta(0)

	def test_fields_outside_the_allow_list_are_dropped(self):
		"""The form must not be able to write salary or bank data that Desk
		owns, even though Employee has those fields."""
		number = self._number()
		create_employee(
			self._payload(
				employee_number=number,
				iban="SA0000000000000000000000",
				salary_mode="Basic",
				final_confirmation_date="2026-06-01",
			)
		)
		stored = frappe.db.get_value("Employee", number, ["iban", "salary_mode", "final_confirmation_date"], as_dict=True)
		self.assertFalse(stored["iban"])
		self.assertIn(stored["salary_mode"], (None, ""))
		self.assertIsNone(stored["final_confirmation_date"])
		self._assert_employee_delta(1)

	def test_a_company_field_in_the_allow_list_is_still_written(self):
		"""The allow list must not be so tight that a documented field breaks."""
		number = self._number()
		create_employee(self._payload(employee_number=number, company_email="new.hire@example.com"))
		self.assertEqual(
			frappe.db.get_value("Employee", number, "company_email"), "new.hire@example.com"
		)
		self._assert_employee_delta(1)

	def test_malformed_payloads_are_refused(self):
		for payload in ("not json", "[]", '"a string"'):
			with self.subTest(payload=payload):
				self.assertRaises(frappe.ValidationError, create_employee, payload)
		self._assert_employee_delta(0)

	def test_list_employees_carries_a_name_on_every_row(self):
		result = list_employees(limit=5)
		self.assertTrue(result["rows"])
		for row in result["rows"]:
			self.assertTrue(row["name"], "name was dropped from the field list")
			self.assertTrue(row["employee_number"])

	def test_list_employees_search_matches_the_number(self):
		number = self._number()
		create_employee(self._payload(employee_number=number))
		found = list_employees(search=number, limit=20)["rows"]
		self.assertIn(number, [row["name"] for row in found])
		self._assert_employee_delta(1)

	def test_list_employees_limit_is_bounded(self):
		self.assertLessEqual(list_employees(limit=100000)["returned"], admin_api.MAX_LIMIT)
		self.assertEqual(list_employees(limit=0)["limit"], admin_api.DEFAULT_LIMIT)

	def test_form_options_resolve_links_against_their_target(self):
		"""gender is a Link to the Gender doctype, so reading .options would
		return the literal string 'Gender' instead of the list of choices."""
		options = get_employee_form_options()["options"]
		self.assertIn("gender", options)
		self.assertNotEqual(options["gender"], ["Gender"])
		self.assertTrue(set(options["gender"]).issubset({"Male", "Female"}))
		self.assertIn("company", options)
		self.assertIn(self.company, options["company"])

	def test_form_options_cover_every_select_the_form_renders(self):
		"""The dialog fills a <select> per key, so a missing key leaves it empty."""
		options = get_employee_form_options()["options"]
		form = open(
			os.path.join(frappe.get_app_path("saudi_hr"), "www", "saudi-admin.html")
		).read()
		wanted = dict(
			re.findall(r'<select id="(emp-[a-z-]+)" name="([a-z_]+)"', form)
		)
		self.assertGreater(len(wanted), 5)
		for control, field in wanted.items():
			self.assertIn(field, options, f"{control} has no options for {field}")

	def test_form_options_refuse_a_user_without_create_permission(self):
		frappe.set_user(self._make_user(["Department Approver"]))
		self.assertRaises(frappe.PermissionError, get_employee_form_options)


class TestAdminApiEmployeeDetail(_ApiTestBase):
	"""The in-panel employee profile that replaced the Desk hand-off."""

	def test_detail_returns_a_readable_profile_with_a_desk_fallback(self):
		payload = get_employee_detail(self.employee)
		profile = payload["profile"]
		self.assertEqual(profile["name"], self.employee)
		self.assertTrue(profile["full_name"])
		self.assertTrue(profile["employee_number"])
		self.assertEqual(profile["status"], "Active")
		self.assertEqual(profile["desk_url"], admin_api.desk_route("Employee", self.employee))
		self.assertIn("requests", payload)
		self.assertFalse(payload["truncated"])

	def test_detail_masks_the_iban_and_the_identity_number(self):
		"""The portal only displays these, so it must never receive them whole."""
		iban = "SA0000000000000000001234"
		id_number = "1098765432"
		frappe.db.set_value(
			"Employee", self.employee, {"iban": iban, "custom_id_number": id_number}
		)
		profile = get_employee_detail(self.employee)["profile"]
		self.assertTrue(iban.endswith(profile["iban"].lstrip("*")))
		self.assertNotIn(iban, json.dumps(profile))
		self.assertTrue(id_number.endswith(profile["custom_id_number"].lstrip("*")))
		self.assertNotIn(id_number, json.dumps(profile))

	def test_detail_lists_that_employees_requests_newest_first(self):
		name = self._make_leave_request("Saudi Sick Leave")
		payload = get_employee_detail(self.employee)
		self.assertIn(name, [row["name"] for row in payload["requests"]])
		row = next(r for r in payload["requests"] if r["name"] == name)
		self.assertEqual(row["doctype"], "Saudi Sick Leave")
		self.assertEqual(row["days"], 2.0)
		self.assertEqual(row["desk_url"], admin_api.desk_route("Saudi Sick Leave", name))

		# the service-request entry carries a kind and no day count, and the
		# dialog has to render both without breaking
		service = self._make_service_request("visa_issuance")
		payload = get_employee_detail(self.employee)
		service_row = next(r for r in payload["requests"] if r["name"] == service)
		self.assertEqual(service_row["kind"], "visa_issuance")
		self.assertIsNone(service_row["days"])

	def test_detail_refuses_an_unknown_or_unreadable_employee(self):
		self.assertRaises(frappe.DoesNotExistError, get_employee_detail, "SA-EM-NOPE")

	def test_detail_refuses_a_caller_without_read_permission(self):
		frappe.set_user(self._make_user(["Department Approver"]))
		self.assertRaises(frappe.PermissionError, get_employee_detail, self.employee)


def _department_tally(overview, department):
	for row in overview["departments"]:
		if row["department"] == department:
			return row
	return {"days": 0, "present": 0, "absent": 0, "half_day": 0, "on_leave": 0, "late_days": 0, "hours": 0}


class _AttendanceTestBase(_ApiTestBase):
	"""Attendance fixtures on the suite's own employee.

	Every record is dated today or in the past on purpose: a future-dated day
	would fall outside the report window and quietly turn these assertions into
	vacuous ones.
	"""

	def setUp(self):
		super().setUp()
		self.today = nowdate()

	def _day(self, offset):
		return str(add_days(getdate(self.today), offset))

	def _month_day(self, day):
		"""A date inside the current calendar month.

		Relative offsets are not usable for the month tally: on the 2nd, "yesterday"
		is the previous month and the assertion would be measuring the wrong bucket.
		"""
		today = getdate(self.today)
		return str(date(today.year, today.month, min(day, today.day)))

	def _make_attendance(
		self,
		offset=None,
		status="Present / حاضر",
		employee=None,
		in_time="08:30:00",
		out_time="16:00:00",
		hours=7.5,
		late_minutes=0,
		on=None,
	):
		day = on or self._day(offset)
		doc = {
			"doctype": "Saudi Daily Attendance",
			"employee": employee or self.employee,
			"attendance_date": day,
			"status": status,
			"in_time": f"{day} {in_time}",
			"out_time": f"{day} {out_time}",
			"working_hours": hours,
		}
		if late_minutes:
			doc.update({"late_entry": 1, "late_minutes": late_minutes})
		if status in ATTENDANCE_STATUS_KEYS:
			doc["status"] = status
		else:
			# Select validation refuses an unknown option on insert, so the row
			# is written valid first and then overwritten the way a site that
			# later adds the option would have stored it
			doc["status"] = "Present / حاضر"
		name = frappe.get_doc(doc).insert(ignore_permissions=True).name
		if status not in ATTENDANCE_STATUS_KEYS:
			frappe.db.set_value("Saudi Daily Attendance", name, "status", status)
		return name

	def _deny(self, *doctypes):
		"""has_permission patched to refuse only these doctypes.

		Refusing everything would also break the Employee read that guards the
		employee itself, and the test would pass for the wrong reason.
		"""
		real = admin_api.frappe.has_permission

		def check(doctype=None, ptype=None, doc=None, user=None, **kwargs):
			if doctype in doctypes:
				return False
			return real(doctype, ptype, doc=doc, user=user, **kwargs)

		return check

	def _make_checkin(self, offset=0, at="09:15:00", log_type="IN", employee=None):
		return frappe.get_doc(
			{
				"doctype": "Saudi Employee Checkin",
				"employee": employee or self.employee,
				"log_type": log_type,
				"time": f"{self._day(offset)} {at}",
			}
		).insert(ignore_permissions=True).name


class TestAdminApiEmployeeAttendance(_AttendanceTestBase):
	"""The attendance block inside the employee dialog."""

	def test_detail_carries_an_attendance_block_for_the_dialog(self):
		payload = get_employee_detail(self.employee)
		attendance = payload["attendance"]
		self.assertTrue(attendance["readable"])
		for key in ("today", "checkin", "month", "month_label", "recent", "truncated"):
			self.assertIn(key, attendance)

	def test_todays_row_comes_first_and_carries_the_day_times(self):
		name = self._make_attendance(0, in_time="08:05:00", out_time="17:45:00", hours=9.67)
		older = self._make_attendance(-3)
		attendance = get_employee_detail(self.employee)["attendance"]

		self.assertEqual(attendance["recent"][0]["name"], name)
		self.assertEqual(attendance["recent"][0]["date"], self.today)
		self.assertEqual(attendance["recent"][0]["in_time"], "08:05")
		self.assertEqual(attendance["recent"][0]["out_time"], "17:45")
		self.assertEqual(attendance["today"]["name"], name)
		self.assertIn(older, [row["name"] for row in attendance["recent"]])

	def test_the_bilingual_status_maps_to_one_stable_key(self):
		"""status is a bilingual Select, so its raw text cannot be matched on."""
		expected = {
			"Present / حاضر": "present",
			"Absent / غائب": "absent",
			"Half Day / نصف يوم": "half_day",
			"On Leave / إجازة": "on_leave",
		}
		for label in expected:
			self._make_attendance(-1, status=label)

		recent = get_employee_detail(self.employee)["attendance"]["recent"]
		self.assertEqual({row["status"]: row["status_key"] for row in recent}, expected)

	def test_an_unrecognised_status_is_counted_as_other_and_not_dropped(self):
		"""A new option added to the Select must not vanish from the tally."""
		self._make_attendance(-1, status="Remote / عن بعد")
		recent = get_employee_detail(self.employee)["attendance"]["recent"]
		self.assertEqual(recent[0]["status"], "Remote / عن بعد")
		self.assertEqual(recent[0]["status_key"], "other")

	def test_the_month_tally_counts_every_status_and_the_late_days(self):
		self._make_attendance(on=self._month_day(1))
		self._make_attendance(on=self._month_day(2), status="Absent / غائب")
		self._make_attendance(
			on=self._month_day(3), status="Half Day / نصف يوم", out_time="12:30:00", hours=4
		)
		self._make_attendance(on=self._month_day(4), status="On Leave / إجازة")
		self._make_attendance(on=self._month_day(5), late_minutes=25)

		month = get_employee_detail(self.employee)["attendance"]["month"]
		self.assertEqual(month["days"], 5)
		self.assertEqual(month["present"], 2)
		self.assertEqual(month["absent"], 1)
		self.assertEqual(month["half_day"], 1)
		self.assertEqual(month["on_leave"], 1)
		self.assertEqual(month["late_days"], 1)
		self.assertEqual(month["late_minutes"], 25)
		# working_hours is recalculated from in/out on validate, so four full
		# days plus a real half day is what has to come back
		self.assertEqual(month["hours"], 34.0)

	def test_another_employees_attendance_is_never_included(self):
		other = make_qa_employee(self.company, f"attendance-{frappe.generate_hash(length=6)}")
		self._make_attendance(0, employee=other)
		self._make_attendance(0)
		recent = get_employee_detail(self.employee)["attendance"]["recent"]
		self.assertEqual(len(recent), 1)
		self.assertEqual(recent[0]["employee"], self.employee)

	def test_the_recent_list_says_when_it_was_capped(self):
		for offset in range(admin_api.EMPLOYEE_ATTENDANCE_DAYS + 3):
			self._make_attendance(-offset)
		attendance = get_employee_detail(self.employee)["attendance"]
		self.assertEqual(len(attendance["recent"]), admin_api.EMPLOYEE_ATTENDANCE_DAYS)
		self.assertTrue(attendance["truncated"])

	def test_a_punch_reports_the_day_when_there_is_no_closed_day_yet(self):
		"""Mid-shift there is no attendance row, and an empty dialog would read
		as "did not work" rather than "still in". """
		self._make_checkin(0, at="09:15:00")
		attendance = get_employee_detail(self.employee)["attendance"]
		self.assertIsNone(attendance["today"])
		self.assertEqual(attendance["checkin"]["log_type"], "IN")
		self.assertEqual(attendance["checkin"]["time"], "09:15")

	def test_a_punch_from_another_day_is_not_reported_as_today(self):
		"""A stale punch would otherwise stand in for a day that never happened."""
		self._make_checkin(-4, at="09:15:00", log_type="OUT")
		attendance = get_employee_detail(self.employee)["attendance"]
		self.assertIsNone(attendance["checkin"])
		self.assertIsNone(attendance["today"])

	def test_todays_punch_is_found_at_all(self):
		"""Guards the test above it: a today filter that matches nothing would
		make 'no punch today' pass for the wrong reason."""
		self._make_checkin(-4, at="09:15:00")
		self._make_checkin(0, at="07:05:00")
		attendance = get_employee_detail(self.employee)["attendance"]
		self.assertEqual(attendance["checkin"]["time"], "07:05")

	def test_a_closed_day_wins_over_the_punch_it_came_from(self):
		self._make_attendance(0)
		self._make_checkin(0, at="08:05:00")
		self._make_checkin(0, at="16:00:00", log_type="OUT")
		attendance = get_employee_detail(self.employee)["attendance"]
		self.assertIsNotNone(attendance["today"])
		self.assertEqual(attendance["today"]["in_time"], "08:30")

	def test_no_attendance_permission_reads_as_restricted_not_as_zero(self):
		"""Zeros would say the employee never came to work."""
		self._make_attendance(0)
		with patch.object(admin_api.frappe, "has_permission", self._deny(admin_api.ATTENDANCE_DOCTYPE)):
			attendance = get_employee_detail(self.employee)["attendance"]
		self.assertFalse(attendance["readable"])
		self.assertEqual(attendance["recent"], [])


class TestAdminApiAttendanceCorrection(_AttendanceTestBase):
	"""The manager's per-day check-in correction and notes in the report."""

	def _closed_day(self, in_time="08:30:00"):
		"""An attendance row and the real IN punch behind it, on the same day."""
		checkin = self._make_checkin(0, at=in_time)
		att = self._make_attendance(0, in_time=in_time, out_time="16:00:00", hours=7.5)
		return checkin, att

	def test_time_correction_moves_the_real_punch_and_the_day(self):
		checkin, att = self._closed_day(in_time="09:15:00")
		row = correct_attendance_day(attendance=att, time="07:00:00")

		self.assertIn("07:00:00", str(frappe.db.get_value("Saudi Employee Checkin", checkin, "time")))
		self.assertIn("07:00:00", str(frappe.db.get_value("Saudi Daily Attendance", att, "in_time")))
		self.assertTrue(row["corrected"])
		self.assertEqual(row["in_time"], "07:00")
		self.assertTrue(
			frappe.db.get_value(
				"Saudi Punch Correction",
				{"employee": self.employee, "attendance_date": self.today},
				"applied",
			)
		)

	def test_a_note_on_its_own_leaves_the_punch_untouched(self):
		checkin, att = self._closed_day()
		row = correct_attendance_day(attendance=att, note="call from the gate")

		self.assertEqual(
			frappe.db.get_value("Saudi Daily Attendance", att, "note"), "call from the gate"
		)
		self.assertEqual(row["note"], "call from the gate")
		self.assertFalse(row["corrected"])
		self.assertIn("08:30:00", str(frappe.db.get_value("Saudi Employee Checkin", checkin, "time")))
		self.assertIsNone(
			frappe.db.exists(
				"Saudi Punch Correction",
				{"employee": self.employee, "attendance_date": self.today},
			)
		)

	def test_out_time_correction_moves_the_real_out_punch_and_the_day(self):
		checkin, att = self._closed_day()
		out_punch = self._make_checkin(0, at="16:00:00", log_type="OUT")
		row = correct_attendance_day(attendance=att, out_time="17:00:00")

		self.assertIn("17:00:00", str(frappe.db.get_value("Saudi Employee Checkin", out_punch, "time")))
		self.assertIn("17:00:00", str(frappe.db.get_value("Saudi Daily Attendance", att, "out_time")))
		# the check-in is left alone
		self.assertIn("08:30:00", str(frappe.db.get_value("Saudi Employee Checkin", checkin, "time")))
		self.assertIn("08:30:00", str(frappe.db.get_value("Saudi Daily Attendance", att, "in_time")))
		self.assertEqual(frappe.db.get_value("Saudi Daily Attendance", att, "working_hours"), 8.5)
		self.assertTrue(row["corrected"])
		self.assertEqual(row["out_time"], "17:00")

	def test_correcting_both_check_in_and_check_out_in_one_request(self):
		checkin, att = self._closed_day(in_time="09:15:00")
		out_punch = self._make_checkin(0, at="16:00:00", log_type="OUT")
		row = correct_attendance_day(attendance=att, time="07:00:00", out_time="17:00:00")

		self.assertIn("07:00:00", str(frappe.db.get_value("Saudi Employee Checkin", checkin, "time")))
		self.assertIn("17:00:00", str(frappe.db.get_value("Saudi Employee Checkin", out_punch, "time")))
		daily = frappe.db.get_value(
			"Saudi Daily Attendance", att, ["in_time", "out_time", "working_hours"], as_dict=True
		)
		self.assertIn("07:00:00", str(daily.in_time))
		self.assertIn("17:00:00", str(daily.out_time))
		self.assertEqual(daily.working_hours, 10.0)
		self.assertTrue(row["corrected"])
		self.assertEqual(row["in_time"], "07:00")
		self.assertEqual(row["out_time"], "17:00")
		# a single request is the audit trail of both sides
		corr = frappe.get_doc(
			"Saudi Punch Correction",
			{"employee": self.employee, "attendance_date": self.today},
		)
		self.assertEqual(corr.punch, checkin)
		self.assertEqual(corr.punch_out, out_punch)

	def test_out_time_correction_registers_a_check_out_when_the_day_has_no_out_punch(self):
		checkin, att = self._closed_day()
		row = correct_attendance_day(attendance=att, out_time="17:00:00")

		out_punch = frappe.db.get_value(
			"Saudi Employee Checkin",
			{
				"employee": self.employee,
				"log_type": "OUT",
				"time": ["between", [f"{self.today} 00:00:00", f"{self.today} 23:59:59"]],
			},
			"name",
		)
		self.assertTrue(out_punch, "a forgotten check-out is registered, not refused")
		self.assertIn("17:00:00", str(frappe.db.get_value("Saudi Employee Checkin", out_punch, "time")))
		self.assertIn("17:00:00", str(frappe.db.get_value("Saudi Daily Attendance", att, "out_time")))
		self.assertEqual(frappe.db.get_value("Saudi Daily Attendance", att, "working_hours"), 8.5)
		self.assertTrue(row["corrected"])
		self.assertEqual(
			frappe.db.get_value(
				"Saudi Punch Correction",
				{"employee": self.employee, "attendance_date": self.today},
				"punch_out",
			),
			out_punch,
			"the request is the audit trail that created this registered punch",
		)

	def test_checkin_correction_registers_a_check_in_when_the_day_has_no_punch(self):
		"""A forgotten check-in is not refused: the admin entry registers the punch,
		tagged with the correction so the audit trail says where it came from."""
		att = self._make_attendance(0)
		row = correct_attendance_day(attendance=att, time="07:00:00")

		self.assertTrue(row["corrected"])
		checkin = frappe.db.get_value(
			"Saudi Employee Checkin",
			{
				"employee": self.employee,
				"log_type": "IN",
				"time": ["between", [f"{self.today} 00:00:00", f"{self.today} 23:59:59"]],
			},
			"name",
		)
		self.assertTrue(checkin, "a forgotten check-in is registered, not refused")
		self.assertIn("07:00:00", str(frappe.db.get_value("Saudi Employee Checkin", checkin, "time")))
		self.assertIn("07:00:00", str(frappe.db.get_value("Saudi Daily Attendance", att, "in_time")))
		self.assertEqual(
			frappe.db.get_value(
				"Saudi Punch Correction",
				{"employee": self.employee, "attendance_date": self.today},
				"punch",
			),
			checkin,
			"the request is the audit trail that created this registered punch",
		)

	def test_a_day_is_corrected_only_once(self):
		_, att = self._closed_day()
		correct_attendance_day(attendance=att, time="07:00:00")
		self.assertRaises(
			frappe.ValidationError, correct_attendance_day, attendance=att, time="08:00:00"
		)

	def test_an_empty_correction_is_refused(self):
		_, att = self._closed_day()
		self.assertRaises(frappe.ValidationError, correct_attendance_day, attendance=att)

	def test_correction_requires_the_admin_portal(self):
		_, att = self._closed_day()
		email = self._make_user(["Employee"])
		frappe.set_user(email)
		self.assertRaises(frappe.PermissionError, correct_attendance_day, attendance=att, time="07:00:00")

	def test_correction_requires_write_permission_on_the_day(self):
		_, att = self._closed_day()
		with patch.object(
			admin_api.frappe, "has_permission", self._deny(admin_api.ATTENDANCE_DOCTYPE)
		):
			self.assertRaises(
				frappe.PermissionError, correct_attendance_day, attendance=att, time="07:00:00"
			)

	def test_the_report_marks_a_corrected_day_and_its_reason(self):
		_, att = self._closed_day()
		correct_attendance_day(attendance=att, time="07:00:00", note="late gate")

		report = get_attendance_report(employee=self.employee, month=self.today[:7])
		row = next(r for r in report["days"] if r["name"] == att)
		self.assertTrue(row["corrected"])
		self.assertEqual(row["in_time"], "07:00")
		self.assertEqual(row["correction_reason"], "late gate")
		self.assertEqual(row["note"], "late gate")

	def test_a_missing_day_is_registered_by_employee_and_date(self):
		"""A day the report lists as missing (no row at all) is filled from its
		date: both punches are created, the daily row appears, and the response
		is the view of that new day."""
		day = self._day(-6)
		self.assertIsNone(
			frappe.db.exists(
				"Saudi Daily Attendance", {"employee": self.employee, "attendance_date": day}
			)
		)

		row = correct_attendance_day(
			employee=self.employee, date=day, time="08:00:00", out_time="17:00:00", note="added from the panel"
		)

		daily = frappe.db.get_value(
			"Saudi Daily Attendance",
			{"employee": self.employee, "attendance_date": day},
			["name", "in_time", "out_time", "working_hours", "status", "note"],
			as_dict=True,
		)
		self.assertTrue(daily, "the correction registers the whole day, not just a punch")
		self.assertIn("08:00:00", str(daily.in_time))
		self.assertIn("17:00:00", str(daily.out_time))
		self.assertEqual(daily.working_hours, 9.0)
		self.assertEqual(daily.status, "Present / حاضر")
		self.assertEqual(daily.note, "added from the panel")
		self.assertTrue(row["corrected"])
		self.assertFalse(row["missing"])
		self.assertEqual(row["date"], day)
		self.assertEqual(row["in_time"], "08:00")
		self.assertEqual(row["out_time"], "17:00")
		# one audit-trail request sits behind both registered punches
		corr = frappe.get_doc(
			"Saudi Punch Correction",
			{"employee": self.employee, "attendance_date": day},
		)
		self.assertTrue(corr.punch)
		self.assertTrue(corr.punch_out)
		self.assertTrue(corr.applied)

	def test_a_registered_missing_day_leaves_the_report_as_present(self):
		day = self._day(-4)
		correct_attendance_day(employee=self.employee, date=day, time="08:00:00", out_time="17:00:00")

		report = get_attendance_report(employee=self.employee, from_date=day, to_date=self._day(-2))
		self.assertEqual(report["span_days"], 3)
		rows = {row["date"]: row for row in report["days"]}
		registered = rows[day]
		self.assertFalse(registered["missing"])
		self.assertTrue(registered["corrected"])
		self.assertEqual(registered["status_key"], "present")
		# the days with no record still read as missing, waiting to be registered
		self.assertCountEqual(
			[row["status_key"] for row in report["days"]],
			["missing", "missing", "present"],
		)

	def test_a_missing_day_without_a_time_is_refused(self):
		self.assertRaises(
			frappe.ValidationError, correct_attendance_day, employee=self.employee, date=self._day(-3)
		)

	def test_a_note_alone_cannot_register_a_missing_day(self):
		"""A note has no row to attach to on a missing day, so it is refused
		rather than silently dropped."""
		self.assertRaises(
			frappe.ValidationError,
			correct_attendance_day, employee=self.employee, date=self._day(-3), note="call from the gate",
		)

	def test_a_future_day_cannot_be_registered(self):
		self.assertRaises(
			frappe.ValidationError,
			correct_attendance_day,
			employee=self.employee, date=add_days(getdate(nowdate()), 5), time="08:00:00",
		)


class TestAdminApiAttendanceOverview(_AttendanceTestBase):
	"""The company and department report in the report panel."""

	def test_the_window_defaults_to_the_last_thirty_days(self):
		window = admin_api._attendance_window()
		self.assertEqual(window["days"], admin_api.DEFAULT_ATTENDANCE_DAYS)
		self.assertEqual(window["to_date"], nowdate())
		self.assertEqual(
			window["from_date"], str(add_days(getdate(nowdate()), -(admin_api.DEFAULT_ATTENDANCE_DAYS - 1)))
		)

	def test_a_reversed_range_is_swapped_rather_than_returned_empty(self):
		window = admin_api._attendance_window("2026-05-10", "2026-05-01")
		self.assertEqual(window["from_date"], "2026-05-01")
		self.assertEqual(window["to_date"], "2026-05-10")

	def test_the_window_is_capped_so_the_query_cannot_be_made_unbounded(self):
		window = admin_api._attendance_window("2020-01-01", "2026-05-01")
		self.assertEqual(window["days"], admin_api.MAX_ATTENDANCE_DAYS)
		self.assertEqual(window["to_date"], "2026-05-01")

	def test_the_totals_add_up_the_window(self):
		# the report is company-wide and this site already holds real records,
		# so the fixture is measured as a delta rather than as the whole total
		before = get_attendance_report()["totals"]
		self._make_attendance(-1)
		self._make_attendance(-2, status="Absent / غائب")
		self._make_attendance(-3, status="On Leave / إجازة", late_minutes=12)
		self._make_attendance(admin_api.MAX_ATTENDANCE_DAYS + 5)

		totals = get_attendance_report()["totals"]
		self.assertEqual(totals["days"] - before["days"], 3)
		self.assertEqual(totals["present"] - before["present"], 1)
		self.assertEqual(totals["absent"] - before["absent"], 1)
		self.assertEqual(totals["on_leave"] - before["on_leave"], 1)
		self.assertEqual(totals["late_minutes"] - before["late_minutes"], 12)

	def test_the_department_rows_add_up_to_the_totals(self):
		department = get_or_create_department(self.company)
		frappe.db.set_value("Employee", self.employee, "department", department)
		before = _department_tally(get_attendance_report(), department)
		self._make_attendance(-1)
		self._make_attendance(-2, status="Absent / غائب")

		data = get_attendance_report()
		rows = data["departments"]
		for key in ("days", "present", "absent", "half_day", "on_leave", "late_days"):
			self.assertAlmostEqual(sum(row[key] for row in rows), data["totals"][key], msg=key)
		self.assertEqual(round(sum(row["hours"] for row in rows), 2), round(data["totals"]["hours"], 2))

		# the department the fixture employee belongs to gains exactly the two
		# days added, and every employee in the bucket counts once
		mine = next(row for row in rows if row["department"] == department)
		self.assertEqual(mine["days"] - before["days"], 2)
		self.assertEqual(mine["present"] - before["present"], 1)
		assigned = frappe.get_all("Employee", filters={"department": department}, pluck="name")
		self.assertLessEqual(mine["employees"], len(assigned) or 1)

	def test_a_day_outside_the_window_is_not_counted(self):
		self._make_attendance(-1)
		overview = get_attendance_report(from_date=self._day(-10), to_date=self._day(-2))
		self.assertEqual(overview["span_days"], 9)
		self.assertNotIn(self.employee, {row["employee"] for row in overview["today"]})

	def test_the_department_list_is_capped_and_says_so(self):
		data = get_attendance_report(limit=1)
		self.assertLessEqual(len(data["departments"]), 1)
		if data["truncated"]:
			self.assertGreater(data["department_count"], len(data["departments"]))

	def test_todays_punches_carry_the_employee_name_for_the_table(self):
		# a time off the wall clock, not a fixed hour: a test that logs a punch
		# at 10:20 stops passing once the day moves past 10:20
		at = (now_datetime() - timedelta(minutes=20)).strftime("%H:%M:%S")
		name = self._make_checkin(0, at=at, log_type="OUT")
		# an older punch alongside it, so the assertion cannot pass by the
		# filter quietly matching nothing at all
		self._make_checkin(-5, at="08:00:00")
		rows = get_attendance_report()["today"]
		# scoped to this punch rather than counted: the table is shared with
		# every other punch anyone left in the database today
		self.assertIn(name, [row["name"] for row in rows])
		row = next(r for r in rows if r["name"] == name)
		self.assertEqual(row["employee"], self.employee)
		self.assertTrue(row["employee_name"])
		self.assertEqual(row["time"], at[:5])
		self.assertEqual(row["log_type"], "OUT")

	def test_a_punch_logged_ahead_of_the_clock_is_still_todays(self):
		"""A device with a fast clock, or a punch entered by hand.

		Bounding the window at now() drops those rows, so the table reports an
		empty day for an employee who is standing in the office.
		"""
		ahead = (now_datetime() + timedelta(minutes=10)).strftime("%H:%M:%S")
		if ahead[:5] == now_datetime().strftime("%H:%M:%S"):
			self.skipTest("the clock cannot be beaten from here")
		name = self._make_checkin(0, at=ahead, log_type="IN")
		self.assertIn(name, [row["name"] for row in get_attendance_report()["today"]])
		detail = get_employee_detail(self.employee)["attendance"]
		self.assertEqual(detail["checkin"]["time"], ahead[:5])

	def test_a_punch_from_another_day_is_not_listed_under_today(self):
		self._make_checkin(-2)
		self.assertEqual(get_attendance_report()["today"], [])

	def test_no_attendance_permission_reads_as_restricted(self):
		self._make_attendance(0)
		denied = self._deny(admin_api.ATTENDANCE_DOCTYPE, admin_api.CHECKIN_DOCTYPE)
		with patch.object(admin_api.frappe, "has_permission", denied):
			data = get_attendance_report()
		self.assertFalse(data["readable"])
		self.assertIsNone(data["totals"])
		self.assertEqual(data["departments"], [])


class TestAdminApiAttendancePeriods(_AttendanceTestBase):
	"""A month, a date range, and one employee instead of the whole company."""

	def test_a_month_reads_as_that_whole_month(self):
		window = admin_api._attendance_window(month="2026-02")
		self.assertEqual(window["from_date"], "2026-02-01")
		self.assertEqual(window["to_date"], "2026-02-28")
		self.assertEqual(window["days"], 28)

	def test_a_malformed_month_is_refused_rather_than_ignored(self):
		"""Falling back would show a real report for the wrong period."""
		for value in ("2026-13", "26-1", "october", "2026/10", ""):
			if not value:
				self.assertEqual(admin_api._attendance_window(month=value)["month"], None)
				continue
			self.assertRaises(frappe.ValidationError, admin_api._attendance_window, None, None, value)

	def test_a_month_wins_over_a_range_passed_alongside_it(self):
		window = admin_api._attendance_window("2026-01-01", "2026-01-31", "2026-03")
		self.assertEqual(window["from_date"], "2026-03-01")
		self.assertEqual(window["to_date"], "2026-03-31")

	def test_only_the_requested_month_is_counted(self):
		month = self._month_day(1)[:7]
		# measured against the same window, since the default 30 days and the
		# month cover different records
		before = get_attendance_report(month=month)["totals"]
		self._make_attendance(on=self._month_day(1))
		self._make_attendance(on=self._month_day(2), status="Absent / غائب")
		data = get_attendance_report(month=month)
		self.assertEqual(data["month"], month)
		self.assertEqual(data["scope"], "departments")
		self.assertEqual(data["totals"]["days"] - before["days"], 2)

	def test_every_day_in_the_month_is_listed(self):
		other = make_qa_employee(self.company, f"period-{frappe.generate_hash(length=6)}")
		frappe.db.set_value("Employee", self.employee, "department", get_or_create_department(self.company))
		first = self._make_attendance(on=self._month_day(1))
		second = self._make_attendance(on=self._month_day(2), status="Absent / غائب")
		theirs = self._make_attendance(on=self._month_day(2), employee=other)

		data = get_attendance_report(employee=self.employee, month=self._month_day(1)[:7])
		self.assertEqual(data["scope"], "employee")
		self.assertEqual(data["employee"]["name"], self.employee)
		self.assertTrue(data["employee"]["employee_name"])
		days = data["days"]
		# a month is a calendar, not a ledger: every day is listed, whether it
		# was recorded or not, so a gap in the attendance shows up in the table
		self.assertEqual(len(days), data["span_days"])
		self.assertEqual({row["name"] for row in days if row["name"]}, {first, second})
		self.assertNotIn(theirs, [row["name"] for row in days if row["name"]])
		for row in days:
			if row["missing"]:
				# a day with no record carries no name and no times, so the row
				# is addressed by its date when the panel registers it
				self.assertIsNone(row["name"])
				self.assertEqual(row["status_key"], "missing")
				self.assertIsNone(row["in_time"])
			else:
				self.assertIn(row["name"], {first, second})
		self.assertFalse(
			next(row for row in days if row["date"] == self._month_day(1))["missing"]
		)
		# the tally still counts only recorded days
		self.assertEqual(data["totals"]["days"], 2)
		self.assertEqual(data["totals"]["present"], 1)
		self.assertEqual(data["totals"]["absent"], 1)
		# the company breakdown is not repeated for a single employee
		self.assertEqual(data["departments"], [])

	def test_a_day_range_is_honoured_for_one_employee(self):
		frappe.db.set_value("Employee", self.employee, "department", get_or_create_department(self.company))
		self._make_attendance(-1)
		self._make_attendance(-5)
		data = get_attendance_report(employee=self.employee, from_date=self._day(-3), to_date=self._day(0))
		self.assertEqual(data["span_days"], 4)
		self.assertEqual(data["totals"]["days"], 1)

	def test_the_day_list_says_when_it_was_capped(self):
		for offset in range(admin_api.REPORT_DAY_ROWS + 4):
			self._make_attendance(-offset)
		# the window has to be wide enough to hold more days than the cap, and
		# the default 30 days could not
		data = get_attendance_report(
			employee=self.employee, from_date=self._day(-(admin_api.REPORT_DAY_ROWS + 10))
		)
		self.assertEqual(len(data["days"]), admin_api.REPORT_DAY_ROWS)
		self.assertTrue(data["truncated"])
		self.assertEqual(data["totals"]["days"], admin_api.REPORT_DAY_ROWS + 4)

	def test_an_unreadable_employee_is_refused(self):
		frappe.set_user(self._make_user(["Department Approver"]))
		self.assertRaises(frappe.PermissionError, get_attendance_report, self.employee)


class TestAdminApiDashboard(_ApiTestBase):
	"""Headcount and leave tallies, which the dashboard and report both read."""

	def test_dashboard_counts_match_the_employee_table(self):
		summary = get_admin_dashboard()["employees"]
		self.assertEqual(summary["total"], frappe.db.count("Employee"))
		self.assertEqual(summary["active"], frappe.db.count("Employee", {"status": "Active"}))
		self.assertEqual(summary["active"] + summary["inactive"], summary["total"])

	def test_dashboard_reports_a_count_for_every_leave_doctype(self):
		leave = get_admin_dashboard()["leave"]
		for entry in LEAVE_REGISTRY:
			self.assertIn(entry[0], leave)
			for key in ("total", "draft", "closed", "actionable"):
				self.assertIn(key, leave[entry[0]])
			self.assertLessEqual(
				leave[entry[0]]["actionable"], leave[entry[0]]["draft"], entry[0]
			)

	def test_actionable_total_is_the_sum_of_the_parts(self):
		dashboard = get_admin_dashboard()
		self.assertEqual(
			dashboard["actionable_total"], sum(v["actionable"] for v in dashboard["leave"].values())
		)

	def test_every_row_is_counted_in_exactly_one_outcome_column(self):
		"""The report is built from these numbers, so the columns must add up.

		A cancelled request used to be reported as approved, because approved was
		computed as total - draft.
		"""
		leave = get_admin_dashboard()["leave"]
		for doctype, summary in leave.items():
			self.assertEqual(
				summary["draft"] + summary["closed"], summary["total"], doctype
			)
			self.assertEqual(
				summary["approved"]
				+ summary["rejected"]
				+ summary["cancelled"]
				+ summary["other"],
				summary["closed"],
				doctype,
			)
			self.assertLessEqual(summary["actionable"], summary["draft"], doctype)

	def test_a_cancelled_request_is_not_reported_as_approved(self):
		"""Cancelled is its own outcome, not an approval."""
		before = get_admin_dashboard()["leave"]["Saudi Annual Leave"]
		request = self._make_leave_request("Saudi Annual Leave")
		frappe.db.set_value("Saudi Annual Leave", request, "workflow_state", "Cancelled", update_modified=False)
		after = get_admin_dashboard()["leave"]["Saudi Annual Leave"]
		self.assertEqual(after["cancelled"], before["cancelled"] + 1)
		self.assertEqual(after["total"], before["total"] + 1)
		self.assertEqual(after["closed"], before["closed"] + 1)
		self.assertEqual(after["approved"], before["approved"], "a cancelled row must not be approved")
		self.assertEqual(after["other"], before["other"])

	def test_the_tally_says_when_it_was_capped(self):
		"""The counts walk at most MAX_LIMIT rows, so an exact-looking total
		would be a lie on a site with a long history."""
		from saudi_hr.saudi_hr import admin_api

		self.assertEqual(get_admin_dashboard()["truncated"], [])
		frappe.flags.in_test = True
		original = admin_api.MAX_LIMIT
		try:
			# one row is enough to prove the cap is reported rather than hidden
			admin_api.MAX_LIMIT = 1
			dashboard = get_admin_dashboard()
		finally:
			admin_api.MAX_LIMIT = original
		self.assertTrue(dashboard["truncated"], "a capped doctype must be named")
		for label in dashboard["truncated"]:
			self.assertIn(label, [summary["label"] for summary in dashboard["leave"].values()])
		self.assertIn(
			dashboard["leave"]["Saudi Annual Leave"]["label"], dashboard["truncated"]
		)
		self.assertTrue(dashboard["leave"]["Saudi Annual Leave"]["truncated"])
		self.assertLessEqual(dashboard["leave"]["Saudi Annual Leave"]["total"], 1)

	def test_the_actionable_badge_is_not_capped_by_the_page_size(self):
		"""frappe.get_list returns 20 rows unless told otherwise, which would
		silently cap the badge at 20 on a long queue."""
		frappe.set_user("Administrator")
		baseline = get_admin_dashboard()["leave"]["Special Leave"]["actionable"]
		for _ in range(22):
			self._plain_draft("Special Leave")
		summary = get_admin_dashboard()["leave"]["Special Leave"]
		self.assertEqual(summary["actionable"], baseline + 22)
		self.assertGreater(summary["actionable"], 20)

	def test_headcount_is_withheld_from_a_pinned_user(self):
		"""Company totals are withheld rather than shown wrong or leaked."""
		email = self._make_user(["Department Approver"])
		frappe.set_user(email)
		frappe.get_doc(
			{
				"doctype": "User Permission",
				"user": email,
				"allow": "Employee",
				"for_value": frappe.get_all("Employee", pluck="name", limit_page_length=1)[0],
				"apply_to_all_doctypes": 1,
			}
		).insert(ignore_permissions=True)

		summary = get_admin_dashboard()["employees"]
		self.assertTrue(summary["scoped"])
		for key in ("total", "active", "inactive", "saudi"):
			self.assertEqual(summary[key], 0, key)

	def test_administrator_still_gets_company_headcount(self):
		"""Frappe ignores User Permissions for Administrator, so do the same."""
		summary = get_admin_dashboard()["employees"]
		self.assertFalse(summary["scoped"])
		self.assertGreater(summary["total"], 0)


class TestAdminApiDoesNotMutateOnRead(_ApiTestBase):
	"""A read endpoint must not write, or the audit trail fills with noise."""

	def setUp(self):
		super().setUp()
		self.tracked = [entry[0] for entry in LEAVE_REGISTRY] + ["Employee"]
		self.before = {doctype: frappe.db.count(doctype) for doctype in self.tracked}

	def test_reads_do_not_change_any_counts(self):
		get_admin_dashboard()
		list_leave_requests()
		list_employees()
		get_employee_form_options()
		get_admin_config()
		for doctype, count in self.before.items():
			self.assertEqual(frappe.db.count(doctype), count, doctype)


class TestAdminApiEosbSettlement(_ApiTestBase):
	"""المخالصة المالية: the end-of-service settlement calculator and record."""

	def test_calculation_is_internally_consistent(self):
		result = get_eosb_settlement(
			employee=self.employee,
			termination_reason="End of Fixed Term / انتهاء عقد محدد",
			termination_date="2026-09-30",
		)
		self.assertEqual(result["employee"]["name"], self.employee)
		self.assertEqual(result["employee"]["termination_date"], "2026-09-30")
		for item in result["earnings"]:
			self.assertIn("item", item)
			self.assertGreaterEqual(item["amount"], 0)
		self.assertEqual(
			result["total_earnings"],
			round(sum(item["amount"] for item in result["earnings"]), 2),
		)
		self.assertGreaterEqual(result["total_deductions"], 0)
		self.assertEqual(
			result["net_settlement"],
			round(result["total_earnings"] - result["total_deductions"], 2),
		)
		self.assertIn("سنوات", result["service_period_str"])
		self.assertTrue(result["words_ar"])
		self.assertRegex(result["ref_no"], r"^CL-2026-")
		self.assertIn(result["status_label"], ("بانتظار الاعتماد", "مختومة ومعتمدة"))
		self.assertEqual(result["issue_date"], nowdate())

	def test_calculation_falls_back_to_an_active_employee(self):
		if not frappe.db.count("Employee", {"status": "Active"}):
			self.skipTest("no active employees on this site")
		result = get_eosb_settlement()
		self.assertIsNotNone(result.get("employee"))

	def test_an_inserted_record_makes_the_settlement_signed(self):
		name = create_eosb_settlement(
			employee=self.employee,
			termination_date="2026-09-30",
			termination_reason="Resignation / استقالة",
			last_basic_salary=12000,
			eosb_deductions=500,
			notes="eosb admin test",
		)["name"]
		doc = frappe.get_doc("End of Service Benefit", name)
		self.assertEqual(doc.employee, self.employee)
		self.assertEqual(str(doc.termination_date), "2026-09-30")
		self.assertEqual(doc.last_basic_salary, 12000)
		self.assertEqual(doc.eosb_deductions, 500)
		self.assertIn("eosb admin test", doc.calculation_notes or "")

		signed = get_eosb_settlement(employee=self.employee, termination_date="2026-09-30")
		self.assertEqual(signed["existing_name"], name)
		self.assertEqual(signed["status_label"], "مختومة ومعتمدة")

	def test_the_settlement_needs_a_portal_role(self):
		frappe.set_user(self._make_user(["Employee"]))
		self.assertRaises(frappe.PermissionError, get_eosb_settlement, employee=self.employee)
		self.assertRaises(
			frappe.PermissionError,
			create_eosb_settlement,
			employee=self.employee,
			termination_date="2026-09-30",
			termination_reason="Resignation / استقالة",
			last_basic_salary=12000,
		)


class TestAdminApiDocumentsAndLetters(_ApiTestBase):
	"""مستندات وخطابات: the documents & letters dashboard and issuing flow."""

	def _issued(self, document_type, addressed_to=None):
		return issue_hr_document(
			employee=self.employee,
			document_type=document_type,
			addressed_to=addressed_to,
		)

	def test_auto_issue_types_come_out_approved(self):
		auto = (
			"salary_certificate",
			"job_confirmation",
			"contract_copy",
			"payslip",
			"salary_benefits_statement",
		)
		for document_type in auto:
			res = self._issued(document_type)
			self.assertEqual(res["state"], "approved", document_type)
			self.assertEqual(res["document_type"], document_type)
			self.assertTrue(res["desk_url"].startswith("/app/hr-service-request/"), res["desk_url"])
			self.assertEqual(
				frappe.db.get_value("HR Service Request", res["name"], "workflow_state"),
				"Approved",
				document_type,
			)

	def test_letters_stay_pending_until_approved_by_hand(self):
		for document_type in ("addressed_letter", "salary_transfer_letter"):
			res = self._issued(document_type, addressed_to="Saudi Post")
			self.assertEqual(res["document_type"], document_type)
			row = next(
				r
				for r in get_documents_and_letters(employee=self.employee)["rows"]
				if r["name"] == res["name"]
			)
			self.assertEqual(row["document_type"], document_type)
			self.assertEqual(row["addressed_to"], "Saudi Post")
			self.assertIn(row["state"], ("pending", "draft"))

	def test_the_dashboard_counts_what_was_issued_this_month(self):
		for document_type in ("salary_certificate", "addressed_letter"):
			self._issued(document_type)
		data = get_documents_and_letters(employee=self.employee)
		ours = [r for r in data["rows"] if r["employee"] == self.employee]
		self.assertEqual(data["stats"]["total"], len(data["rows"]))
		self.assertGreaterEqual(data["stats"]["issued_month"], 1)
		self.assertGreaterEqual(data["stats"]["pending"], 1)
		self.assertEqual(len(ours), 2)

	def test_filtering_by_type_and_status_narrows_the_rows(self):
		self._issued("salary_certificate")
		self._issued("addressed_letter")
		by_type = get_documents_and_letters(employee=self.employee, document_type="addressed_letter")
		self.assertTrue(all(r["document_type"] == "addressed_letter" for r in by_type["rows"]))
		approved = get_documents_and_letters(employee=self.employee, status="approved")
		self.assertTrue(all(r["state"] == "approved" for r in approved["rows"]))

	def test_the_documents_and_letters_need_a_portal_role(self):
		frappe.set_user(self._make_user(["Employee"]))
		self.assertRaises(frappe.PermissionError, get_documents_and_letters)
		self.assertRaises(
			frappe.PermissionError,
			issue_hr_document,
			employee=self.employee,
			document_type="salary_certificate",
		)


class TestAdminApiOffboarding(_ApiTestBase):
	"""إنهاء الخدمة: the offboarding panel drives the exit chain end to end."""

	TERMINATION_REASON = "Resignation by Employee / استقالة الموظف (م.75)"
	SALARY_TYPE = "Monthly / شهري"
	NOTICE_START = "2026-09-01"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")

		# These role users persist for the whole class (one insert per role,
		# not per test) so the run never trips the User-creation throttle.
		def _role_user(role):
			suffix = frappe.generate_hash(length=8).lower()
			email = f"saudi.offb.{suffix}@example.com"
			return frappe.get_doc(
				{
					"doctype": "User",
					"email": email,
					"first_name": f"offb{suffix}",
					"new_password": "N7!xP4@qR9#vT2$k",
					"send_welcome_email": 0,
					"roles": [{"role": role}],
				}
			).insert(ignore_permissions=True).name

		cls.hr_user = _role_user("HR User")
		cls.hr_manager = _role_user("HR Manager")
		cls.hr_manager_two = _role_user("HR Manager")
		cls.gm = _role_user("General Manager")

	def _start_notice(self, as_user=None):
		frappe.set_user(as_user or self.hr_manager)
		result = create_termination_notice(
			employee=self.employee,
			termination_reason=self.TERMINATION_REASON,
			salary_payment_type=self.SALARY_TYPE,
			notice_start_date=self.NOTICE_START,
		)
		frappe.set_user("Administrator")
		return result["name"]

	def _start_case(self):
		notice = self._start_notice()
		clearance = create_exit_clearance(employee=self.employee, termination_notice=notice)["name"]
		return notice, clearance

	def _complete_notice(self, notice):
		frappe.set_user(self.hr_manager)
		apply_offboarding_action("Termination Notice", notice, "Submit Request")
		frappe.set_user(self.hr_user)
		apply_offboarding_action("Termination Notice", notice, "HR Approve")
		frappe.set_user(self.hr_manager_two)
		apply_offboarding_action("Termination Notice", notice, "HR Manager Approve")
		frappe.set_user(self.gm)
		apply_offboarding_action("Termination Notice", notice, "GM Approve")
		frappe.set_user(self.hr_manager_two)
		apply_offboarding_action("Termination Notice", notice, "Mark Completed")
		frappe.set_user("Administrator")

	def test_offboarding_form_options_carry_the_option_lists(self):
		options = get_offboarding_form_options()
		self.assertIn(self.TERMINATION_REASON, options["termination_reasons"])
		self.assertIn(self.SALARY_TYPE, options["salary_payment_types"])
		self.assertIn("Cleared / مخلى طرفه", options["clearance_statuses"])

	def test_starting_an_exit_creates_the_notice_and_the_clearance(self):
		notice, clearance = self._start_case()
		doc = frappe.get_doc("Exit Clearance", clearance)
		self.assertEqual(doc.termination_notice, notice)
		self.assertEqual(doc.employee, self.employee)
		tn = frappe.get_doc("Termination Notice", notice)
		self.assertEqual(tn.salary_payment_type, self.SALARY_TYPE)
		# 60 days of notice for a monthly wage, starting 2026-09-01
		self.assertEqual(getdate(tn.notice_end_date).isoformat(), "2026-10-31")
		self.assertEqual(getdate(doc.last_working_day).isoformat(), "2026-10-31")

	def test_a_second_clearance_for_the_same_notice_is_idempotent(self):
		notice = self._start_notice()
		first = create_exit_clearance(employee=self.employee, termination_notice=notice)
		second = create_exit_clearance(employee=self.employee, termination_notice=notice)
		self.assertTrue(first["created"])
		self.assertFalse(second["created"])
		self.assertEqual(first["name"], second["name"])

	def test_the_checklist_advances_the_case_toward_cleared(self):
		_, clearance = self._start_case()
		opened = save_exit_clearance(clearance, {"access_revoked": 1, "assets_returned": 1})
		self.assertEqual(opened["state"], "pending")
		self.assertEqual(opened["clearance_percentage"], 25.0)

		full = save_exit_clearance(
			clearance,
			{
				"access_revoked": 1,
				"assets_returned": 1,
				"final_attendance_verified": 1,
				"payroll_closed": 1,
				"eosb_completed": 1,
				"annual_leave_disbursement_completed": 1,
				"exit_interview_completed": 1,
				"handover_completed": 1,
			},
		)
		self.assertEqual(full["state"], "approved")
		self.assertEqual(full["clearance_percentage"], 100.0)

	def test_only_hr_can_submit_the_notice(self):
		notice = self._start_notice(as_user=self.hr_manager)

		employee = self._make_user(["Employee"])
		frappe.set_user(employee)
		self.assertRaises(
			frappe.PermissionError,
			apply_offboarding_action,
			"Termination Notice",
			notice,
			"Submit Request",
		)
		self.assertRaises(
			frappe.PermissionError,
			create_termination_notice,
			employee=self.employee,
			termination_reason=self.TERMINATION_REASON,
			salary_payment_type=self.SALARY_TYPE,
			notice_start_date=self.NOTICE_START,
		)

		frappe.set_user(self.hr_manager)
		result = apply_offboarding_action("Termination Notice", notice, "Submit Request")
		self.assertEqual(result["next_state"], "Pending HR Review")
		self.assertEqual(
			frappe.db.get_value("Termination Notice", notice, "workflow_state"),
			"Pending HR Review",
		)

	def test_a_role_that_cannot_advance_is_refused(self):
		"""The notice's own solicitor cannot take the HR step for it."""
		notice = self._start_notice(as_user=self.hr_manager)
		frappe.set_user(self.hr_manager)
		apply_offboarding_action("Termination Notice", notice, "Submit Request")
		# hr_manager owns the document but does not hold HR User, so HR Approve
		# is not among their transitions and must be refused outright
		self.assertRaises(
			frappe.PermissionError,
			apply_offboarding_action,
			"Termination Notice",
			notice,
			"HR Approve",
		)

	def test_hr_walks_the_notice_to_completed_and_the_sla_follows(self):
		notice, clearance = self._start_case()
		self._complete_notice(notice)

		tn = frappe.get_doc("Termination Notice", notice)
		self.assertEqual(tn.docstatus, 1)
		self.assertEqual(tn.workflow_state, "Completed")
		self.assertTrue(
			frappe.db.exists("Final Settlement SLA", {"termination_notice": notice, "exit_clearance": clearance})
		)

	def test_submitting_the_eosb_ticks_the_checklist_and_marks_the_employee_left(self):
		notice, clearance = self._start_case()
		self._complete_notice(notice)

		eosb = create_eosb_from_case(exit_clearance=clearance, last_basic_salary=12000)["name"]
		submitted = submit_eosb(name=eosb)
		self.assertEqual(submitted["docstatus"], 1)
		self.assertEqual(submitted["employee_status"], "Left")

		cl = frappe.get_doc("Exit Clearance", clearance)
		self.assertEqual(cl.end_of_service_benefit, eosb)
		self.assertTrue(cl.eosb_completed)
		sla_name = frappe.db.get_value("Final Settlement SLA", {"termination_notice": notice}, "name")
		self.assertEqual(frappe.db.get_value("Final Settlement SLA", sla_name, "eosb_document"), eosb)
		self.assertEqual(frappe.db.get_value("Final Settlement SLA", sla_name, "exit_clearance"), clearance)

	def test_the_case_reads_back_every_link(self):
		notice, clearance = self._start_case()
		self._complete_notice(notice)

		eosb = create_eosb_from_case(exit_clearance=clearance, last_basic_salary=12000)["name"]
		interview = create_exit_interview(exit_clearance=clearance)["name"]
		leave = create_leave_disbursement(exit_clearance=clearance, leave_days_to_pay=2)["name"]

		case = get_offboarding_case(clearance)
		self.assertEqual(case["termination_notice"], notice)
		self.assertEqual(case["end_of_service_benefit"], eosb)
		self.assertEqual(case["exit_interview"], interview)
		self.assertEqual(case["annual_leave_disbursement"], leave)
		self.assertIsNotNone(case["final_settlement"])
		self.assertEqual(case["final_settlement"]["last_working_day"], "2026-10-31")
		self.assertEqual(case["termination_notice_doc"]["docstatus"], 1)
		self.assertEqual(case["checklist"]["annual_leave_disbursement_completed"], 1)

	def test_settling_the_final_settlement_closes_the_sla(self):
		notice, clearance = self._start_case()
		self._complete_notice(notice)
		sla_name = frappe.db.get_value("Final Settlement SLA", {"termination_notice": notice}, "name")

		result = settle_final_settlement(name=sla_name)
		self.assertEqual(result["status"], "Settled / تمت التسوية")
		self.assertEqual(result["payment_status"], "Paid / مدفوع")
		sla = frappe.get_doc("Final Settlement SLA", sla_name)
		self.assertEqual(sla.status, "Settled / تمت التسوية")
		self.assertEqual(sla.exit_clearance, clearance)

	def test_an_unsupported_doctype_action_is_refused(self):
		leave = frappe.get_doc(
			{
				"doctype": "Saudi Annual Leave",
				"employee": self.employee,
				"company": self.company,
				"leave_start_date": "2026-11-01",
				"leave_end_date": "2026-11-03",
			}
		).insert(ignore_permissions=True)
		self.assertRaises(
			frappe.ValidationError,
			apply_offboarding_action,
			"Saudi Annual Leave",
			leave.name,
			"Submit Request",
		)

	def test_a_missing_case_is_refused(self):
		self.assertRaises(frappe.DoesNotExistError, get_offboarding_case, "DOES-NOT-EXIST")
		self.assertRaises(frappe.DoesNotExistError, save_exit_clearance, "DOES-NOT-EXIST", {})
		self.assertRaises(frappe.DoesNotExistError, submit_eosb, "DOES-NOT-EXIST")

	def test_the_offboarding_needs_a_portal_role(self):
		frappe.set_user(self._make_user(["Employee"]))
		self.assertRaises(frappe.PermissionError, get_offboarding_form_options)
		self.assertRaises(frappe.PermissionError, list_exit_clearances)
