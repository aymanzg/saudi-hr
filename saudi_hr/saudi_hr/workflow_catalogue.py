"""
workflow_catalogue.py — the single source of truth for Saudi HR approval workflows.

Every approval-minded doctype in the app follows one canonical approval chain,
defined once here in English, with Arabic supplied by the label layer.  The
chain is:

    Draft
      -> Pending Supervisor Review        (Supervisor Approve / Reject)
           -> Pending HR Review           (HR Approve / Reject)
                -> Pending HR Manager Review   (HR Manager Approve / Reject)
                     -> Pending GM Review       (GM Approve / Reject)
                          -> GM Approved        (Mark Completed)
                               -> Completed

Each approval level has its own ``Rejected by <level>`` state; the applicant
resubmits from that state back into the same level.  ``Completed`` is the only
state that can carry a submitted ``doc_status``; whether it does depends on the
doctype — a doctype that is not submittable ends on ``doc_status 0`` so the
chain works identically for case-tracker doctypes and approval doctypes alike.

The installer reconciles this catalogue on every ``bench migrate``, so editing
here is how workflows change; the old per-doctype JSON fixtures are gone.
"""

from __future__ import annotations

import frappe
from frappe.utils import cint, cstr

# ─── Canonical vocabulary ────────────────────────────────────────────────────

CANONICAL_STATES = (
	"Pending Supervisor Review",
	"Rejected by Supervisor",
	"Pending HR Review",
	"Rejected by HR",
	"Pending HR Manager Review",
	"Rejected by HR Manager",
	"Pending GM Review",
	"Rejected by GM",
	"GM Approved",
	"Completed",
)
FIRST_STATE = "Draft"
TERMINAL_STATE = "Completed"
CANCELLED_STATE = "Cancelled"

ALL_STATES = (FIRST_STATE,) + CANONICAL_STATES + (CANCELLED_STATE,)

SUBMIT_ROLES = ("Employee Self Service", "Employee")
SUBMIT_ACTIONS = ("Submit Request", "Resubmit Request")
SUPERVISOR_ROLE = "Supervisor"
HR_ROLE = "HR User"
HR_MANAGER_ROLE = "HR Manager"
GM_ROLE = "General Manager"
EXECUTOR_ROLES = ("HR User", "HR Manager")
CHAIN_ROLES = (SUPERVISOR_ROLE, HR_ROLE, HR_MANAGER_ROLE, GM_ROLE)

# Doctypes whose Submit/Resubmit is performed by HR rather than the employee.
# An offboarding is initiated by HR/Administration on the employee's behalf, so
# the employee must not be able to start or restart it.
SUBMIT_ROLE_OVERRIDES = {
	"Termination Notice": (HR_ROLE, HR_MANAGER_ROLE),
}

# Doctypes that HR drives end to end: there is no employee submitter and no
# supervisor leg, so the chain runs HR -> HR Manager -> General Manager.
HR_INITIATED_CHAIN = ("Termination Notice",)

# The one workflow vocabulary the rest of the app speaks.  Arabic on the desk
# comes from the label layer, never from these names.
BUCKET_BY_STATE = {
	FIRST_STATE: "draft",
	"Pending Supervisor Review": "pending",
	"Rejected by Supervisor": "rejected",
	"Pending HR Review": "pending",
	"Rejected by HR": "rejected",
	"Pending HR Manager Review": "pending",
	"Rejected by HR Manager": "rejected",
	"Pending GM Review": "pending",
	"Rejected by GM": "rejected",
	"GM Approved": "approved",
	TERMINAL_STATE: "approved",
	CANCELLED_STATE: "cancelled",
}

# The doctypes that follow the chain, in display order.
WORKFLOW_DOCUMENT_TYPES = (
	"Absence Case",
	"Disciplinary Appeal",
	"Employee Grievance",
	"HR Compliance Action Log",
	"HR Policy Document",
	"HR Service Request",
	"Investigation Record",
	"Legal Reference Matrix",
	"Mobile Leave Request",
	"Overtime Request",
	"Salary Adjustment",
	"Saudi Annual Leave",
	"Saudi Emergency Leave",
	"Saudi Punch Correction",
	"Saudi Sick Leave",
	"Termination Notice",
)

# Relative labels for the four chain roles plus the legacy roles they replace.
ROLE_LABELS = {
	"Supervisor": "المشرف",
	"Department Approver": "مشرف القسم",
	"General Manager": "المدير العام",
	"HR Manager": "مدير الموارد البشرية",
	"HR User": "اخصائي العمليات",
	"Employee": "موظف",
	"Employee Self Service": "خدمة ذاتية للموظف",
	"Accounts Manager": "مدير الحسابات",
	"Leave Approver": "معتمد الإجازات",
}

# ─── Helpers ─────────────────────────────────────────────────────────────────

def workflow_name(doctype: str) -> str:
	return f"{doctype} Approval Workflow"


def state_bucket(state) -> str | None:
	"""Normalise any workflow/status value into the six-word portal vocabulary."""
	state = cstr(state or "").strip()
	if not state:
		return None
	if state in BUCKET_BY_STATE:
		return BUCKET_BY_STATE[state]

	lowered = state.lower()
	if "reject" in lowered or "مرفوض" in lowered:
		return "rejected"
	if "cancel" in lowered or "ملغ" in lowered:
		return "cancelled"
	if "approv" in lowered or "معتمد" in lowered or "مكتمل" in lowered or "مغلق" in lowered \
		or "تم البت" in lowered or "محلول" in lowered:
		return "approved"
	if "pending" in lowered or "awaiting" in lowered or "بانتظار" in lowered or "قيد" in lowered:
		return "pending"
	if "draft" in lowered or "مسودة" in lowered or "مفتوح" in lowered:
		return "draft"
	return lowered or "unknown"


def role_label(role) -> str:
	return ROLE_LABELS.get(cstr(role or ""), cstr(role or ""))


# ─── State / transition definitions ─────────────────────────────────────────

def _state_specs(is_submittable: bool, doctype: str):
	terminal_doc_status = "1" if is_submittable else "0"
	cancel_doc_status = "2" if is_submittable else "0"
	specs = (
		(FIRST_STATE, "Employee Self Service", "0", "Warning"),
		("Pending Supervisor Review", SUPERVISOR_ROLE, "0", "Primary"),
		("Rejected by Supervisor", "Employee Self Service", "0", "Danger"),
		("Pending HR Review", HR_ROLE, "0", "Primary"),
		("Rejected by HR", "Employee Self Service", "0", "Danger"),
		("Pending HR Manager Review", HR_MANAGER_ROLE, "0", "Primary"),
		("Rejected by HR Manager", "Employee Self Service", "0", "Danger"),
		("Pending GM Review", GM_ROLE, "0", "Primary"),
		("Rejected by GM", "Employee Self Service", "0", "Danger"),
		("GM Approved", HR_ROLE, "0", "Success"),
		(TERMINAL_STATE, HR_ROLE, terminal_doc_status, "Success"),
		(CANCELLED_STATE, HR_ROLE, cancel_doc_status, "Danger"),
	)
	if doctype in HR_INITIATED_CHAIN:
		# HR owns the notice from the first state; the supervisor leg never runs.
		specs = tuple(
			row for row in specs if row[0] not in ("Pending Supervisor Review", "Rejected by Supervisor")
		)
		specs = ((FIRST_STATE, HR_ROLE, "0", "Warning"),) + specs[1:]
	return specs


def _transition(specs, action, state, next_state, roles, self_approval):
	for role in roles:
		specs.append(
			{
				"action": action,
				"state": state,
				"next_state": next_state,
				"allowed": role,
				"allow_self_approval": self_approval,
			}
		)


def _hr_initiated_transition_specs(doctype: str):
	"""HR-driven chain: no supervisor leg, Submit/Resubmit stay with HR."""
	submit_roles = SUBMIT_ROLE_OVERRIDES.get(doctype, SUBMIT_ROLES)
	specs = []
	_add = lambda action, state, next_state, roles, self_approval: _transition(
		specs, action, state, next_state, roles, self_approval
	)

	_add("Submit Request", FIRST_STATE, "Pending HR Review", submit_roles, 1)
	for rejected, review in (
		("Rejected by HR", "Pending HR Review"),
		("Rejected by HR Manager", "Pending HR Manager Review"),
		("Rejected by GM", "Pending GM Review"),
	):
		_add("Resubmit Request", rejected, review, submit_roles, 1)
	_add("HR Approve", "Pending HR Review", "Pending HR Manager Review", (HR_ROLE,), 0)
	_add("HR Reject", "Pending HR Review", "Rejected by HR", (HR_ROLE,), 0)
	_add("HR Manager Approve", "Pending HR Manager Review", "Pending GM Review", (HR_MANAGER_ROLE,), 0)
	_add("HR Manager Reject", "Pending HR Manager Review", "Rejected by HR Manager", (HR_MANAGER_ROLE,), 0)
	_add("GM Approve", "Pending GM Review", "GM Approved", (GM_ROLE,), 0)
	_add("GM Reject", "Pending GM Review", "Rejected by GM", (GM_ROLE,), 0)
	_add("Mark Completed", "GM Approved", TERMINAL_STATE, EXECUTOR_ROLES, 0)
	return specs


def _transition_specs(doctype: str | None = None):
	if doctype in HR_INITIATED_CHAIN:
		return _hr_initiated_transition_specs(doctype)
	specs = []
	submit_roles = SUBMIT_ROLE_OVERRIDES.get(doctype, SUBMIT_ROLES)

	def _add(action, state, next_state, roles, self_approval):
		_transition(specs, action, state, next_state, roles, self_approval)

	_add("Submit Request", FIRST_STATE, "Pending Supervisor Review", submit_roles, 1)
	for rejected, review in (
		("Rejected by Supervisor", "Pending Supervisor Review"),
		("Rejected by HR", "Pending HR Review"),
		("Rejected by HR Manager", "Pending HR Manager Review"),
		("Rejected by GM", "Pending GM Review"),
	):
		_add("Resubmit Request", rejected, review, submit_roles, 1)

	_add("Supervisor Approve", "Pending Supervisor Review", "Pending HR Review", (SUPERVISOR_ROLE,), 0)
	_add("Supervisor Reject", "Pending Supervisor Review", "Rejected by Supervisor", (SUPERVISOR_ROLE,), 0)
	_add("HR Approve", "Pending HR Review", "Pending HR Manager Review", (HR_ROLE,), 0)
	_add("HR Reject", "Pending HR Review", "Rejected by HR", (HR_ROLE,), 0)
	_add("HR Manager Approve", "Pending HR Manager Review", "Pending GM Review", (HR_MANAGER_ROLE,), 0)
	_add("HR Manager Reject", "Pending HR Manager Review", "Rejected by HR Manager", (HR_MANAGER_ROLE,), 0)
	_add("GM Approve", "Pending GM Review", "GM Approved", (GM_ROLE,), 0)
	_add("GM Reject", "Pending GM Review", "Rejected by GM", (GM_ROLE,), 0)
	_add("Mark Completed", "GM Approved", TERMINAL_STATE, EXECUTOR_ROLES, 0)
	return specs


def build_workflow(doctype: str, is_submittable: bool | None = None) -> dict:
	"""Assemble the Workflow document payload for one doctype."""
	if is_submittable is None:
		is_submittable = bool(cint(frappe.get_meta(doctype).is_submittable))

	name = workflow_name(doctype)
	states = [
		{"state": state, "allow_edit": allow_edit, "doc_status": doc_status}
		for state, allow_edit, doc_status, _style in _state_specs(is_submittable, doctype)
	]
	transitions = _transition_specs(doctype)
	return {
		"doctype": "Workflow",
		"name": name,
		"workflow_name": name,
		"document_type": doctype,
		"is_active": 1,
		"override_status": 0,
		"send_email_alert": 1,
		"workflow_state_field": "workflow_state",
		"states": states,
		"transitions": transitions,
	}


def build_all() -> dict[str, dict]:
	return {doctype: build_workflow(doctype) for doctype in WORKFLOW_DOCUMENT_TYPES}


# ─── Validation (unit-testable without a live site) ─────────────────────────

def _assert_reachable(workflow: dict):
	incoming = {t.get("next_state") for t in workflow["transitions"]}
	first = FIRST_STATE
	for state_row in workflow["states"]:
		state = state_row.get("state")
		if state in (first, CANCELLED_STATE):
			continue
		if state not in incoming:
			raise AssertionError(f"{workflow['workflow_name']}: '{state}' is unreachable")


def _assert_no_bilingual(workflow: dict):
	import unicodedata

	for value in (workflow["document_type"], workflow["workflow_name"], FIRST_STATE):
		for char in value:
			if unicodedata.name(char).startswith(("ARABIC_", "HEBREW_")):
				raise AssertionError(f"{workflow['workflow_name']}: non-Latin char in '{value}'")
	for state_row in workflow["states"]:
		state = state_row.get("state")
		for char in state:
			if unicodedata.name(char).startswith(("ARABIC_", "HEBREW_")):
				raise AssertionError(f"{workflow['workflow_name']}: non-Latin state '{state}'")
	for transition in workflow["transitions"]:
		for field in ("action", "state", "next_state", "allowed"):
			for char in cstr(transition.get(field)):
				if unicodedata.name(char).startswith(("ARABIC_", "HEBREW_")):
					raise AssertionError(
						f"{workflow['workflow_name']}: non-Latin {field} '{transition.get(field)}'"
					)


def _assert_terminal_docstatus(workflow: dict, is_submittable: bool):
	expected_terminal = "1" if is_submittable else "0"
	expected_cancel = "2" if is_submittable else "0"
	for state_row in workflow["states"]:
		status = cstr(state_row.get("doc_status"))
		if state_row.get("state") == TERMINAL_STATE:
			if status != expected_terminal:
				raise AssertionError(
					f"{workflow['workflow_name']}: terminal doc_status {status} != {expected_terminal}"
				)
		elif state_row.get("state") == CANCELLED_STATE:
			if status != expected_cancel:
				raise AssertionError(
					f"{workflow['workflow_name']}: cancelled doc_status {status} != {expected_cancel}"
				)
		elif status not in ("", "0"):
			raise AssertionError(f"{workflow['workflow_name']}: non-terminal state carries doc_status {status}")


def validate_workflow_catalogue(is_submittable: dict[str, bool] | None = None, expected_roles: set[str] | None = None) -> dict[str, dict]:
	"""Check every generated workflow before anything touches the database.

	``is_submittable`` and ``expected_roles`` are injectable so the unit test can
	run without a live site; the installer passes nothing and reads live meta.
	"""
	workflows = {}
	submittable_map = {}
	for doctype in WORKFLOW_DOCUMENT_TYPES:
		is_sub = is_submittable[doctype] if is_submittable is not None else bool(cint(frappe.get_meta(doctype).is_submittable))
		submittable_map[doctype] = is_sub
		workflows[doctype] = build_workflow(doctype, is_submittable=is_sub)
	for doctype, workflow in workflows.items():
		_assert_reachable(workflow)
		_assert_no_bilingual(workflow)
		_assert_terminal_docstatus(workflow, submittable_map[doctype])
		for state_row in workflow["states"]:
			if state_row.get("state") != FIRST_STATE and state_row.get("state") not in CANONICAL_STATES + (CANCELLED_STATE,):
				raise AssertionError(f"{workflow['workflow_name']}: unexpected state {state_row.get('state')}")
		for transition in workflow["transitions"]:
			for keyword in ("rejected", "مسودة"):
				if keyword in cstr(transition.get("allowed")).lower():
					raise AssertionError(f"{workflow['workflow_name']}: stale role '{transition.get('allowed')}'")
		if expected_roles is not None:
			for transition in workflow["transitions"]:
				if transition.get("allowed") not in expected_roles:
					raise AssertionError(
						f"{workflow['workflow_name']}: role '{transition.get('allowed')}' does not exist"
					)
	return workflows


# ─── Reconciliation helpers (callable from install.py) ──────────────────────

def ensure_workflow_states():
	"""Create the Workflow State master rows behind the canonical chain."""
	style_by_state = {
		FIRST_STATE: "Warning",
		"Pending Supervisor Review": "Primary",
		"Rejected by Supervisor": "Danger",
		"Pending HR Review": "Primary",
		"Rejected by HR": "Danger",
		"Pending HR Manager Review": "Primary",
		"Rejected by HR Manager": "Danger",
		"Pending GM Review": "Primary",
		"Rejected by GM": "Danger",
		"GM Approved": "Success",
		TERMINAL_STATE: "Success",
		CANCELLED_STATE: "Danger",
	}
	for state, style in style_by_state.items():
		if not frappe.db.exists("Workflow State", state):
			frappe.get_doc(
				{
					"doctype": "Workflow State",
					"workflow_state_name": state,
					"style": style,
				}
			).insert(ignore_permissions=True)
		elif frappe.db.get_value("Workflow State", state, "style") != style:
			frappe.db.set_value("Workflow State", state, "style", style)


def ensure_workflow_roles():
	"""Create the English chain roles and their Arabic translations."""
	translations = [
		(SUPERVISOR_ROLE, ROLE_LABELS[SUPERVISOR_ROLE]),
		(HR_ROLE, ROLE_LABELS[HR_ROLE]),
		(HR_MANAGER_ROLE, ROLE_LABELS[HR_MANAGER_ROLE]),
		(GM_ROLE, ROLE_LABELS[GM_ROLE]),
		("Employee", ROLE_LABELS["Employee"]),
		("Employee Self Service", ROLE_LABELS["Employee Self Service"]),
	]
	for role_name, arabic in translations:
		if not frappe.db.exists("Role", role_name):
			frappe.get_doc(
				{
					"doctype": "Role",
					"role_name": role_name,
					"desk_access": 1,
				}
			).insert(ignore_permissions=True)
		if not frappe.db.exists("Translation", {"source_text": role_name, "language": "ar"}):
			frappe.get_doc(
				{
					"doctype": "Translation",
					"source_text": role_name,
					"translated_text": arabic,
					"language": "ar",
				}
			).insert(ignore_permissions=True)


def ensure_workflow_actions():
	"""Create the Workflow Action Master rows behind every transition.

	Workflow Transition.action is a Link to Workflow Action Master in this
	Frappe version, so the insert of a Workflow document fails unless each
	action name already has a master row.
	"""
	missing = 0
	actions = {transition["action"] for transition in _transition_specs()}
	for action in sorted(actions):
		if frappe.db.exists("Workflow Action Master", action):
			continue
		frappe.get_doc(
			{
				"doctype": "Workflow Action Master",
				"workflow_action_name": action,
			}
		).insert(ignore_permissions=True)
		missing += 1
	return missing


def reconcile_workflows():
	"""Make the database match the catalogue: one active workflow per doctype."""
	workflows = build_all()
	for doctype, payload in workflows.items():
		canonical_name = payload["workflow_name"]

		# Sweep any other workflow definition for the same doctype first, so
		# the doctype never holds a stale dormant alternative.
		for name in frappe.get_all(
			"Workflow",
			filters={"document_type": doctype, "workflow_name": ["!=", canonical_name]},
			pluck="name",
		):
			frappe.delete_doc("Workflow", name, force=1, ignore_permissions=True)

		if frappe.db.exists("Workflow", canonical_name):
			workflow = frappe.get_doc("Workflow", canonical_name)
			workflow.update(payload)
			workflow.save(ignore_permissions=True)
		else:
			frappe.get_doc(payload).insert(ignore_permissions=True)


# ─── Backfill ────────────────────────────────────────────────────────────────

_BACKFILL_TARGET = {
	"Draft": FIRST_STATE,
	"مسودة / Draft": FIRST_STATE,
	"Open": FIRST_STATE,
	"مفتوح / Open": FIRST_STATE,
	"Pending Manager Approval": "Pending Supervisor Review",
	"Pending Manager": "Pending Supervisor Review",
	"بانتظار موافقة المدير / Pending Manager": "Pending Supervisor Review",
	"Pending HR Approval": "Pending HR Review",
	"Pending HR": "Pending HR Review",
	"بانتظار HR / Pending HR": "Pending HR Review",
	"HR Review": "Pending HR Review",
	"مراجعة HR / HR Review": "Pending HR Review",
	"Under Review": "Pending HR Review",
	"قيد المراجعة / Under Review": "Pending HR Review",
	"In Progress": "Pending HR Review",
	"قيد التحقيق / In Progress": "Pending HR Review",
	"قيد التنفيذ / In Progress": "Pending HR Review",
	"Notice Sent": "Pending HR Review",
	"تم الإشعار / Notice Sent": "Pending HR Review",
	"Pending Finance Approval": "Pending HR Review",
	"Management Approval": "Pending HR Manager Review",
	"موافقة الإدارة / Management Approval": "Pending HR Manager Review",
	"Approved": TERMINAL_STATE,
	"معتمد / Approved": TERMINAL_STATE,
	"Completed": TERMINAL_STATE,
	"مكتمل / Completed": TERMINAL_STATE,
	"Closed": TERMINAL_STATE,
	"مغلق / Closed": TERMINAL_STATE,
	"Decided": TERMINAL_STATE,
	"تم البت / Decided": TERMINAL_STATE,
	"Resolved": TERMINAL_STATE,
	"محلول / Resolved": TERMINAL_STATE,
	"Rejected": "Rejected by Supervisor",
	"مرفوض / Rejected": "Rejected by Supervisor",
	"Cancelled": CANCELLED_STATE,
	"ملغى / Cancelled": CANCELLED_STATE,
}


def _backfill_target(state: str) -> str:
	if state in ALL_STATES:
		return state
	if state in _BACKFILL_TARGET:
		return _BACKFILL_TARGET[state]
	# Legacy value with no explicit mapping: parked back in Draft where a human
	# can still act on it instead of hiding it as an unknown state.
	frappe.log_error(
		f"No backfill mapping for workflow state '{state}'", "Saudi HR Workflow Backfill"
	)
	return FIRST_STATE


def backfill_workflow_states():
	"""Remap legacy and period values onto the canonical chain (idempotent)."""
	for doctype in WORKFLOW_DOCUMENT_TYPES:
		if not frappe.db.table_exists(doctype) or not frappe.db.exists("DocType", doctype):
			continue
		meta = frappe.get_meta(doctype)
		if not meta.has_field("workflow_state"):
			continue
		reloaded = 0
		for row in frappe.get_all(
			doctype, fields=["name", "workflow_state", "docstatus"]
		):
			current = cstr(row.get("workflow_state") or "")
			if current in ALL_STATES:
				continue
			target = _backfill_target(current)
			# A submitted document may only sit on the submitted terminal; an
			# approved-looking doc that never submitted stays editable at GM.
			if target == TERMINAL_STATE and bool(cint(meta.is_submittable)) and cint(row.get("docstatus")) != 1:
				target = "GM Approved"
			frappe.db.set_value(doctype, row.get("name"), "workflow_state", target, update_modified=False)
			reloaded += 1
		if reloaded:
			frappe.log_error(
				f"Backfilled {reloaded} workflow_state rows on {doctype}", "Saudi HR Workflow Backfill"
			)