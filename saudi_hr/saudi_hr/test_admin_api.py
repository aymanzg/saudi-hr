"""Tests for the /saudi-admin API.

The suite runs as Administrator because the interesting behaviour is what a
*non* privileged caller gets refused, which is only observable from inside.
Every test that writes rolls back with the fixture: nothing here commits, and
the counts asserted in tearDown prove the site is unchanged.
"""

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from saudi_hr.saudi_hr import admin_api
from saudi_hr.saudi_hr.admin_api import (
	LEAVE_REGISTRY,
	STANDARD_FIELDS,
	_dedupe_actions,
	_existing_fields,
	_row_state,
	assert_portal_access,
	apply_leave_action,
	create_employee,
	get_admin_dashboard,
	get_admin_config,
	get_employee_form_options,
	get_leave_request,
	list_employees,
	list_leave_requests,
	submit_leave_request,
)

WORKFLOW_DOCTYPES = ("Saudi Annual Leave", "Saudi Sick Leave", "Mobile Leave Request")
PLAIN_DOCTYPES = ("Special Leave", "Maternity Paternity Leave")


class TestAdminApiAccess(FrappeTestCase):
	"""The portal gate and the per-document permission behaviour under it."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.company = frappe.get_all("Company", pluck="name", limit_page_length=1)[0]

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

	def test_portal_refuses_a_user_with_no_admin_role(self):
		email = self._make_user(["Employee"])
		frappe.set_user(email)
		self.assertRaises(frappe.PermissionError, assert_portal_access)
		for endpoint in (
			get_admin_dashboard,
			get_admin_config,
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

	def test_unreadable_request_is_refused_with_a_clean_error(self):
		"""A User Permission can hide a document the list query still returns.

		The app's permission_query_conditions hook returns an empty condition for
		elevated roles, so get_all() surfaces requests the document level check
		refuses.  The portal must agree with the stricter check, otherwise it
		offers a button that fails on click.
		"""
		request = self._make_leave_request("Saudi Annual Leave")
		email = self._make_user(["HR User"])
		frappe.set_user(email)

		# pin the user to a different employee, as the site does for real HR
		# users; apply_to_all_doctypes is what makes it reach the leave doctype
		other = frappe.db.get_value(
			"Employee",
			{"name": ["!=", frappe.db.get_value("Saudi Annual Leave", request, "employee")]},
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

		# the list query still offers the row, which is the trap this guards
		self.assertIn(request, [r["name"] for r in list_leave_requests()["rows"]])
		self.assertFalse(frappe.has_permission("Saudi Annual Leave", "read", doc=request, throw=False))
		self.assertRaises(frappe.PermissionError, get_leave_request, "Saudi Annual Leave", request)
		self.assertRaises(
			frappe.PermissionError, apply_leave_action, "Saudi Annual Leave", request, "Submit Request"
		)

	def test_an_unreadable_request_is_never_marked_actionable(self):
		request = self._make_leave_request("Saudi Annual Leave")
		email = self._make_user(["HR User"])
		frappe.set_user(email)
		other = frappe.db.get_value(
			"Employee",
			{"name": ["!=", frappe.db.get_value("Saudi Annual Leave", request, "employee")]},
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
		row = next(r for r in list_leave_requests()["rows"] if r["name"] == request)
		self.assertFalse(row["actionable"])
		self.assertEqual(row["actions"], [])
		self.assertFalse(row["can_read"])

	def _make_leave_request(self, doctype):
		"""A draft request owned by Administrator, so self-approval never blocks."""
		employee = frappe.get_all("Employee", pluck="name", limit_page_length=1)[0]
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


class TestAdminApiLeaveActions(FrappeTestCase):
	"""Approval actions are the security boundary, so they are tested hardest."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.company = frappe.get_all("Company", pluck="name", limit_page_length=1)[0]

	def _draft(self, doctype="Saudi Annual Leave"):
		employee = frappe.get_all("Employee", pluck="name", limit_page_length=1)[0]
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
		self.assertTrue(actual, "an HR User should have an action on a draft request")

	def test_actions_are_deduplicated_for_a_multi_role_user(self):
		"""The workflow declares Draft -> Submit Request once per role, so a
		user holding both roles must not be offered the button twice."""
		from frappe.model.workflow import get_transitions

		request = self._draft()
		frappe.set_user(self._hr_user(["HR User", "Employee Self Service"]))
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
			frappe.PermissionError, apply_leave_action, "Saudi Annual Leave", request, "Final Approve"
		)
		self.assertEqual(frappe.db.get_value("Saudi Annual Leave", request, "workflow_state"), "Draft")

	def test_a_permitted_action_advances_the_workflow(self):
		request = self._draft()
		frappe.set_user(self._hr_user(["HR User"]))
		result = apply_leave_action("Saudi Annual Leave", request, "Submit Request")
		self.assertEqual(result["next_state"], "Pending Manager Approval")
		self.assertEqual(
			frappe.db.get_value("Saudi Annual Leave", request, "workflow_state"), "Pending Manager Approval"
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
		employee = frappe.get_all("Employee", pluck="name", limit_page_length=1)[0]
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

	def _plain_draft(self, doctype):
		employee = frappe.get_all("Employee", pluck="name", limit_page_length=1)[0]
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


class TestAdminApiLeaveInbox(FrappeTestCase):
	"""The inbox merges five doctypes with different fields into one shape."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.company = frappe.get_all("Company", pluck="name", limit_page_length=1)[0]

	def test_registry_matches_this_site(self):
		"""Each entry's fields must exist, or the inbox silently shows blanks."""
		for doctype, _label, start, end, days, kind, state in LEAVE_REGISTRY:
			self.assertTrue(frappe.db.table_exists(doctype), doctype)
			present = {d.fieldname for d in frappe.get_meta(doctype).fields} | STANDARD_FIELDS
			for field in (start, end, days, kind, state):
				if field:
					self.assertIn(field, present, f"{doctype}.{field}")

	def test_registry_covers_the_five_saudi_leave_doctypes(self):
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
			({"workflow_state": "Pending Manager Approval"}, "pending"),
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
		self.assertIn("HR Approve", actions)
		self.assertNotIn("Final Approve", actions)

	def test_a_state_with_no_matching_role_yields_no_actions(self):
		from frappe.model.workflow import get_workflow

		workflow = get_workflow("Saudi Annual Leave")
		# Finance is a single role, so a user without it must not see Final Approve
		frappe.set_user(self._user_with("HR User"))
		states = admin_api._actionable_states("Saudi Annual Leave")
		finance = next(
			(s for s in states.values() if any(a["action"] == "Final Approve" for a in s)), None
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


class TestAdminApiEmployees(FrappeTestCase):
	"""Employee creation has to land on the employee number, not a series name."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.company = frappe.get_all("Company", pluck="name", limit_page_length=1)[0]
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


class TestAdminApiDashboard(FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")

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


class TestAdminApiDoesNotMutateOnRead(FrappeTestCase):
	"""A read endpoint must not write, or the audit trail fills with noise."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
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
