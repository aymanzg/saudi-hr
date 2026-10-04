"""Whitelisted API backing the admin portal at /saudi-admin.

Three rules shape everything in this module.

It never trusts an action name from the client.  ``apply_leave_action``
re-derives the transitions the server is willing to honour and refuses
anything outside that set, so a crafted POST cannot approve a request the
caller has no rights over.

It does not hardcode which leave doctypes carry a workflow.  The registry
below records the field names each doctype actually has, and the workflow is
resolved per doctype at call time.  The three request types use one, while
Special Leave and Maternity Paternity Leave use a plain submit instead, and
attaching a workflow to one of them later needs no change here.

It does not grant visibility.  Every read goes through ``frappe.get_list``,
which applies the caller's own permissions, so an approver sees the stage
they are responsible for rather than the whole inbox.  Counts the caller
cannot legitimately make, such as company headcount while pinned to one
employee, are withheld rather than approximated.
"""

import json
import re
from urllib.parse import quote

import frappe
from frappe import _
from frappe.model.rename_doc import rename_doc
from frappe.permissions import get_user_permissions
from frappe.model.workflow import (
	apply_workflow,
	get_transitions,
	get_workflow,
	get_workflow_name,
	has_approval_access,
)
from frappe.utils import cint, cstr, flt, getdate, now

from saudi_hr.scripts.rename_employees_to_employee_number import (
	is_valid_name,
	rename_named_after_employee,
)
from saudi_hr.saudi_hr.utils import assert_doctype_permissions, is_saudi_nationality

# Roles allowed to open the admin portal at all.  Approval rights are
# deliberately absent here: they come from each workflow, so a Department
# Approver reaches the page and sees only their own queue without being a
# general administrator.
# The verb each endpoint allows. The page mirrors this to decide whether to
# send a GET or a POST, and the tests assert the two stay in step, because
# Frappe refuses a mismatched verb with "Not permitted" before the permission
# check even runs.
POST_ONLY_METHODS = frozenset(
	{"create_employee", "apply_leave_action", "submit_leave_request"}
)

ADMIN_PORTAL_ROLES = frozenset(
	{
		"System Manager",
		"HR Manager",
		"HR User",
		"Department Approver",
		"Leave Approver",
		"Accounts Manager",
	}
)

# Leave doctypes the admin inbox covers, in display order.  The five tuples are
# (doctype, label, start field, end field, days field, kind field, status field).
# Every field is verified against meta at call time, so a field that disappears
# in a future site upgrade degrades to None instead of raising.
LEAVE_REGISTRY = (
	(
		"Saudi Annual Leave",
		"Annual Leave / إجازة سنوية",
		"leave_start_date",
		"leave_end_date",
		"total_leave_days",
		None,
		"workflow_state",
	),
	(
		"Saudi Sick Leave",
		"Sick Leave / إجازة مرضية",
		"from_date",
		"to_date",
		"total_days",
		None,
		"workflow_state",
	),
	(
		"Mobile Leave Request",
		"Mobile Leave / طلبات إجازة من الجوال",
		"from_date",
		"to_date",
		"total_days",
		"request_type",
		"workflow_state",
	),
	(
		"Saudi Emergency Leave",
		"Emergency Leave / إجازة طارئة",
		"from_date",
		"to_date",
		"total_days",
		"reason",
		"workflow_state",
	),
	(
		"Special Leave",
		"Special Leave / إجازة خاصة",
		"leave_start_date",
		"leave_end_date",
		"actual_days",
		"leave_type",
		"status",
	),
	(
		"Maternity Paternity Leave",
		"Maternity & Paternity / أمومة وأبوة",
		"leave_start_date",
		"leave_end_date",
		"entitled_days",
		"leave_type",
		None,
	),
)

# Employee fields the admin form may write.  Anything not listed is dropped
# even if the client sends it, so the form cannot reach the salary, bank or
# review fields that Desk manages.
EMPLOYEE_WRITABLE_FIELDS = (
	"employee_number",
	"first_name",
	"middle_name",
	"last_name",
	"date_of_birth",
	"gender",
	"marital_status",
	"company_email",
	"personal_email",
	"mobile_no",
	"nationality",
	"date_of_joining",
	"date_of_leaving",
	"employment_type",
	"status",
	"company",
	"department",
	"designation",
	"branch",
	"grade",
	"reports_to",
	"user_id",
	"description",
	"custom_full_name_english",
	"custom_nationality",
	"custom_id_type",
	"custom_id_number",
	"custom_id_expiration_date",
	"custom_iban",
)

REQUIRED_EMPLOYEE_FIELDS = ("first_name", "company", "gender", "date_of_birth", "date_of_joining")

# A bounded page size keeps one request from pulling an entire employee table.
MAX_LIMIT = 200
DEFAULT_LIMIT = 50


def assert_portal_access():
	"""Refuse the whole API to users who hold none of the admin roles."""
	if frappe.session.user == "Guest":
		frappe.throw(_("يجب تسجيل الدخول أولاً."), frappe.PermissionError)

	if not ADMIN_PORTAL_ROLES.intersection(frappe.get_roles()):
		frappe.throw(
			_("You do not have access to the HR administration portal."),
			frappe.PermissionError,
		)


# Frappe's implicit fields are stored on every document but are not listed in
# meta.fields, so they have to bypass the meta check below.
STANDARD_FIELDS = frozenset(
	{"name", "docstatus", "owner", "creation", "modified", "idx", "_user_tags"}
)


def _existing_fields(doctype, names):
	"""Keep only the fields this site actually has on the doctype.

	Used so a field that disappears in a future site upgrade degrades to None
	instead of raising, which is the difference between a blank cell and a
	broken approvals page.
	"""
	present = {d.fieldname for d in frappe.get_meta(doctype).fields} | STANDARD_FIELDS
	return [name for name in names if name in present]


def _clean_limit(limit, default=DEFAULT_LIMIT):
	try:
		value = cint(limit)
	except (TypeError, ValueError):
		value = default
	return max(1, min(value or default, MAX_LIMIT))


def desk_route(doctype, name):
	"""Deep link into the Desk form for ``doctype``/``name``.

	The desk router keys its routes off ``frappe.router.slug``, which is a
	lower-cased, dash-separated form of the doctype name (see
	``frappe/public/js/frappe/router.js``).  Percent-encoding the spaces
	instead, as this used to, produces a URL the SPA cannot resolve and the
	click silently lands on "Page Not Found".
	"""
	slug = cstr(doctype).strip().lower().replace(" ", "-")
	return "/app/{}/{}".format(slug, quote(cstr(name), safe=""))


def _doctype_entry(entry):
	doctype, label, start, end, days, kind, state = entry
	return {
		"doctype": doctype,
		"label": label,
		"fields": {
			"start": start,
			"end": end,
			"days": days,
			"kind": kind,
			"state": state,
		},
		# resolved at call time: a doctype may gain or lose its workflow
		"has_workflow": bool(get_workflow_name(doctype)),
	}


def get_admin_config():
	"""Everything the shell needs before the first panel renders."""
	assert_portal_access()
	return {
		"user": frappe.session.user,
		"roles": sorted(frappe.get_roles()),
		"can_manage_employees": _can_manage_employees(),
		"leave_types": [_doctype_entry(entry) for entry in LEAVE_REGISTRY],
		"lang": frappe.db.get_value("User", frappe.session.user, "language") or "en",
	}


def _can_manage_employees():
	return bool(frappe.has_permission("Employee", "create", throw=False))


@frappe.whitelist(methods=["GET"])
def get_admin_dashboard():
	assert_portal_access()

	leave = {}
	actionable_total = 0
	for entry in LEAVE_REGISTRY:
		doctype, label = entry[0], entry[1]
		if not frappe.db.table_exists(doctype):
			continue

		# An approver role may hold read on one leave doctype and not another.
		# get_list raises rather than returning nothing, so the doctype is
		# reported as unreadable instead of failing the whole dashboard.
		readable = bool(frappe.has_permission(doctype, "read", throw=False))
		summary = {
			"doctype": doctype,
			"label": label,
			"total": 0,
			"draft": 0,
			"closed": 0,
			"approved": 0,
			"rejected": 0,
			"cancelled": 0,
			# closed with a state the portal does not recognise
			"other": 0,
			"readable": readable,
			# the tally below is capped, so say so rather than report a wrong total
			"truncated": False,
		}
		fields = _existing_fields(doctype, ["workflow_state", "status", "docstatus", "employee"])
		# get_list, not get_all: a Department Approver must not see headcounts for
		# requests the permission query hides from them.
		rows = (
			frappe.get_list(
				doctype, fields=fields, order_by="creation desc", limit_page_length=MAX_LIMIT
			)
			if readable
			else []
		)
		# Permissions are applied by get_list, so an exact count would need a
		# second, permission-free query. Capping and flagging is the honest
		# trade: the number is right for what it covers and the page says when
		# there is more.
		summary["truncated"] = len(rows) >= MAX_LIMIT
		for row in rows:
			summary["total"] += 1
			state = _row_state(row)
			# Report and dashboard must agree, so the same normalisation decides
			# both. An open state is a draft; anything else is settled and is
			# counted under the outcome it actually carries.
			if _is_open(row):
				summary["draft"] += 1
			else:
				summary["closed"] += 1
				# anything unrecognised is closed but has no outcome, so it must
				# not be counted as approved
				summary[state if state in ("approved", "rejected", "cancelled") else "other"] += 1

		actionable = _count_actionable(doctype, entry) if readable else 0
		summary["actionable"] = actionable
		actionable_total += actionable
		leave[doctype] = summary

	return {
		"employees": _employee_counts(),
		"leave": leave,
		"actionable_total": actionable_total,
		# labels of the doctypes whose tallies cover only the newest MAX_LIMIT rows
		"truncated": sorted(
			summary["label"] for summary in leave.values() if summary["truncated"]
		),
		"generated_at": now(),
	}


def _employee_counts():
	"""Headcount as this user is allowed to see it.

	Headcount is a company-wide number, so it is only meaningful to roles that
	can read the whole employee list. A Department Approver arriving here has a
	User Permission pinning them to their own department; company totals would
	be both wrong and a leak, so they are withheld rather than approximated.
	"""
	counts = {"total": 0, "active": 0, "inactive": 0, "saudi": 0, "scoped": True}
	if not frappe.has_permission("Employee", "read", throw=False):
		return counts
	# Frappe's own view of whether this user is pinned. It deliberately returns
	# nothing for Administrator and Guest, so querying User Permission directly
	# would wrongly report them as scoped.
	if get_user_permissions(frappe.session.user).get("Employee"):
		# a pinned user sees only their own slice, so no company total is shown
		return counts
	counts["scoped"] = False

	status_field = _existing_fields("Employee", ["status"])
	rows = (
		frappe.get_list(
			"Employee",
			fields=["name"] + status_field,
			limit_page_length=0,
		)
		if status_field
		else []
	)
	counts["total"] = len(rows)
	counts["active"] = sum(1 for row in rows if cstr(row.get("status")) == "Active")
	counts["inactive"] = counts["total"] - counts["active"]

	# The site stores nationality as free text in either direction, so reuse the
	# app's own matcher rather than reimplementing it as a SQL LIKE.
	nationality_field = _existing_fields("Employee", ["nationality", "custom_nationality"])
	if nationality_field:
		primary = nationality_field[0]
		values = frappe.get_list("Employee", pluck=primary, limit_page_length=0) or []
		counts["saudi"] = sum(1 for value in values if is_saudi_nationality(value))
	return counts


def _row_state(row):
	"""Normalise a workflow state, a status select, or a docstatus into one word.

	The five doctypes disagree: three carry ``workflow_state``, Special Leave
	carries a ``status`` select, and Maternity Paternity Leave carries neither,
	so the inbox needs a single vocabulary.
	"""
	state = cstr(row.get("workflow_state") or "").strip()
	if state:
		lowered = state.lower()
		if "pending" in lowered or "awaiting" in lowered or "to be approved" in lowered:
			return "pending"
		if "approved" in lowered:
			return "approved"
		if "rejected" in lowered:
			return "rejected"
		if "cancel" in lowered:
			return "cancelled"
		return lowered or "unknown"

	status = cstr(row.get("status") or "").strip()
	if status:
		lowered = status.lower()
		if "approved" in lowered or "موافق" in lowered:
			return "approved"
		if "reject" in lowered or "مرفوض" in lowered:
			return "rejected"
		if "cancel" in lowered or "ملغ" in lowered:
			return "cancelled"
		if "draft" in lowered or "مسودة" in lowered:
			return "draft"
		return lowered

	if cint(row.get("docstatus")) == 1:
		return "approved"
	return "draft"


def _is_open(row):
	return _row_state(row) in ("pending", "draft")


def _actionable_states(doctype):
	"""Map current workflow state to the actions this user may take there.

	The list view needs this for every row, and calling ``get_transitions`` per
	document would mean a permission check and a workflow lookup per row.  The
	workflow table already states which roles may act in which state, so the
	roles are resolved once and matched per row.  ``get_leave_request`` and
	``apply_leave_action`` still use the authoritative ``get_transitions``.
	"""
	workflow_name = get_workflow_name(doctype)
	if not workflow_name:
		return {}

	try:
		workflow = get_workflow(doctype)
	except frappe.DoesNotExistError:
		return {}
	if not workflow:
		return {}

	roles = set(frappe.get_roles())
	states = {}
	for transition in workflow.transitions or []:
		# `allowed` is a multiline Text column, not a JSON array, so it has to be
		# split explicitly; treating it as a list would match single characters
		allowed = transition.get("allowed") or ""
		allowed_roles = {role.strip() for role in re.split(r"[,\n]", allowed) if role.strip()}
		if not roles.intersection(allowed_roles):
			continue
		actions = states.setdefault(transition.get("state"), [])
		entry = {
			"action": transition.get("action"),
			"next_state": transition.get("next_state"),
			"allow_self_approval": cint(transition.get("allow_self_approval")),
		}
		# the same action is often declared once per role, so a user holding two
		# of those roles would otherwise be offered the same button twice
		if not any(
			existing["action"] == entry["action"]
			and existing["next_state"] == entry["next_state"]
			for existing in actions
		):
			actions.append(entry)
	return states


def _count_actionable(doctype, entry):
	"""How many open requests the current user could act on right now.

	Every branch goes through get_list, so the badge cannot advertise more work
	than this user is actually allowed to see.
	"""
	if not get_workflow_name(doctype):
		# no workflow: a draft the user is allowed to submit counts as actionable
		# no limit_page_length: get_list defaults to 20 rows, which would cap the
		# badge at 20 on a site with a long queue of unsubmitted drafts
		return len(
			frappe.get_list(doctype, pluck="name", filters={"docstatus": 0}, limit_page_length=0) or []
		)

	states = _actionable_states(doctype)
	if not states:
		return 0

	# narrow to the states this user can act in before loading anything, so a
	# site with a long leave history does not pay a document load per request
	rows = frappe.get_list(
		doctype,
		filters={"workflow_state": ["in", list(states)]},
		fields=["name", "workflow_state", "docstatus", "owner"],
		limit_page_length=MAX_LIMIT,
	) or []

	count = 0
	for row in rows:
		_doc, can_read = _load_row(doctype, row)
		if _row_actions(doctype, row, states, can_read):
			count += 1
	return count


@frappe.whitelist(methods=["GET"])
def list_employees(search=None, company=None, department=None, status=None, limit=None):
	assert_portal_access()
	limit = _clean_limit(limit)

	# An approver role reaches the portal to clear leave, not to browse the
	# employee directory. Withhold it rather than returning an empty table that
	# looks like a broken query.
	if not frappe.has_permission("Employee", "read", throw=False):
		return {"rows": [], "limit": limit, "returned": 0, "restricted": True}

	candidate_fields = _existing_fields(
		"Employee",
		(
			"name",
			"employee_name",
			"employee_number",
			"company_email",
			"custom_id_number",
			"custom_full_name_english",
		),
	)
	fields = _existing_fields(
		"Employee",
		(
			"name",
			"employee_name",
			"employee_number",
			"company",
			"department",
			"designation",
			"status",
			"date_of_joining",
			"company_email",
			"mobile_no",
			"nationality",
			"custom_nationality",
			"custom_id_number",
			"modified",
		),
	)

	filters = {}
	if company:
		filters["company"] = company
	if department:
		filters["department"] = department
	if status:
		filters["status"] = status

	or_filters = None
	if search:
		like = "%{}%".format(cstr(search).strip())
		or_filters = [
			[field, "like", like]
			for field in ("name", "employee_name", "employee_number", "company_email", "custom_id_number")
			if field in candidate_fields
		]

	# get_list so a User Permission on Employee narrows this list the same way
	# it narrows the Desk list view.
	rows = frappe.get_list(
		"Employee",
		filters=filters,
		or_filters=or_filters,
		fields=fields,
		order_by="modified desc",
		limit_page_length=limit,
	)

	return {
		"rows": [_employee_row(row) for row in rows],
		"limit": limit,
		"returned": len(rows),
		"has_more": len(rows) == limit,
		# the UI hides the employee panel rather than showing a bare table
		"restricted": False,
	}


def _employee_row(row):
	nationality = row.get("custom_nationality") or row.get("nationality")
	return {
		"name": row.get("name"),
		"employee_number": row.get("employee_number") or row.get("name"),
		"full_name": row.get("employee_name") or row.get("name"),
		"full_name_english": row.get("custom_full_name_english"),
		"company": row.get("company"),
		"department": row.get("department"),
		"designation": row.get("designation"),
		"status": row.get("status"),
		"joining_date": row.get("date_of_joining"),
		"company_email": row.get("company_email"),
		"mobile_no": row.get("mobile_no"),
		"nationality": nationality,
		"is_saudi": is_saudi_nationality(nationality),
		"id_number": row.get("custom_id_number"),
		"modified": str(row.get("modified")) if row.get("modified") else None,
		# a renamed employee is reachable under its number, so both routes open
		"desk_url": desk_route("Employee", row.get("name")),
	}


@frappe.whitelist(methods=["GET"])
def get_employee_form_options():
	assert_portal_access()
	assert_doctype_permissions("Employee", "create")

	meta = frappe.get_meta("Employee")
	candidates = (
		"company",
		"department",
		"designation",
		"branch",
		"grade",
		"reports_to",
		"employment_type",
		"gender",
		"marital_status",
		"status",
		# the form exposes this one, so its options have to come back too
		"custom_id_type",
	)
	options = {}
	for field in candidates:
		if not meta.has_field(field):
			continue
		df = meta.get_field(field)

		# a Link is resolved against its target doctype, not against .options,
		# which for a Link holds the target name rather than a list
		if df.fieldtype == "Link":
			target = df.options
			if not target or not frappe.db.table_exists(target):
				continue
			target_meta = frappe.get_meta(target)
			rows = frappe.get_all(
				target,
				pluck="name",
				filters={"disabled": 0} if target_meta.has_field("disabled") else None,
				order_by="name asc",
				limit_page_length=0,
			)
			options[field] = rows
		elif df.fieldtype in ("Select", "Link Title"):
			options[field] = [row for row in (df.options or "").split("\n") if row]

	return {"options": options, "writable_fields": list(EMPLOYEE_WRITABLE_FIELDS)}


@frappe.whitelist(methods=["POST"])
def create_employee(payload_json):
	"""Create an employee under their employee number rather than HR-EMP-000xx.

	``Employee`` is still configured with ``set_name_by_naming_series``, so the
	insert produces a series name and the number is applied by renaming
	immediately after.  The rename reuses the logic the migrate patch relies
	on, which keeps a newly created employee consistent with the renamed ones.
	"""
	assert_portal_access()

	try:
		payload = json.loads(cstr(payload_json or "{}"))
	except (TypeError, ValueError):
		frappe.throw(_("Invalid employee data."), frappe.ValidationError)
	if not isinstance(payload, dict):
		frappe.throw(_("Invalid employee data."), frappe.ValidationError)

	doc = frappe.get_doc({"doctype": "Employee"})
	# read back only the allowed fields, so a crafted payload cannot write
	# salary, bank or review data that Desk owns
	doc.update(
		{
			key: value
			for key, value in payload.items()
			if key in EMPLOYEE_WRITABLE_FIELDS and value not in (None, "")
		}
	)

	employee_number = cstr(doc.get("employee_number") or "").strip()
	_validate_employee_number(employee_number)
	_validate_employee_fields(doc)
	_validate_id_number(doc)

	assert_doctype_permissions("Employee", "create", doc=doc)

	doc.insert()

	# mirror the migrate patch: rename, then repoint the self-referential
	# `employee` link, then follow any doc named after the employee
	old = doc.name
	rename_doc("Employee", old, employee_number, force=True, ignore_permissions=True, rebuild_search=False)
	frappe.db.set_value("Employee", employee_number, "employee", employee_number, update_modified=False)
	rename_named_after_employee(old, employee_number)
	# fix_manual_references() is deliberately not called: it rewrites
	# User Permission / Comment / Version rows that point at the old name, and
	# a document inserted seconds ago cannot have any.  It also prints to stdout,
	# which would put rename chatter in the web request log.

	return {"name": employee_number, "created": True, "desk_url": desk_route("Employee", employee_number)}


def _validate_employee_number(employee_number):
	if not employee_number:
		frappe.throw(
			_("Employee Number is required.<br>رقم الموظف مطلوب."), title=_("Missing Employee Number")
		)
	if not is_valid_name(employee_number):
		frappe.throw(
			_("Employee Number contains characters that are not allowed.<br>رقم الموظف يحتوي على رموز غير مسموحة."),
			title=_("Invalid Employee Number"),
		)
	# the number becomes the document name, so a name collision is fatal
	if frappe.db.exists("Employee", employee_number):
		frappe.throw(
			_("Employee Number {0} is already in use.<br>رقم الموظف {0} مستخدم بالفعل.").format(
				frappe.bold(employee_number)
			),
			title=_("Duplicate Employee Number"),
		)
	# and a different employee may already hold the same number in the field
	duplicate = frappe.db.get_value("Employee", {"employee_number": employee_number}, "name")
	if duplicate:
		frappe.throw(
			_("Employee Number {0} is already used by {1}.<br>رقم الموظف {0} مستخدم من قبل {1}.").format(
				frappe.bold(employee_number), frappe.bold(duplicate)
			),
			title=_("Duplicate Employee Number"),
		)


def _validate_employee_fields(doc):
	missing = [
		field
		for field in REQUIRED_EMPLOYEE_FIELDS
		if not cstr(doc.get(field) or "").strip()
	]
	if missing:
		frappe.throw(
			_("Please complete the required fields.")
			+ "<br>"
			+ ", ".join(_(field) for field in missing),
			title=_("Missing Information"),
		)

	for field in ("date_of_birth", "date_of_joining", "date_of_leaving"):
		value = doc.get(field)
		if not value:
			continue
		parsed = getdate(value)
		if parsed > getdate(now()):
			frappe.throw(
				_("{0} cannot be in the future.<br>لا يمكن أن يكون {0} في المستقبل.").format(
					_(frappe.unscrub(field))
				),
				title=_("Invalid Date"),
			)

	joining = doc.get("date_of_joining")
	if joining and doc.get("date_of_birth"):
		if getdate(joining) < getdate(doc.get("date_of_birth")):
			frappe.throw(
				_("Joining date cannot be earlier than the date of birth.<br>لا يمكن أن يكون تاريخ الالتحاق أسبق من تاريخ الميلاد."),
				title=_("Invalid Dates"),
			)


def _validate_id_number(doc):
	id_number = cstr(doc.get("custom_id_number") or "").strip()
	if not id_number:
		return
	duplicate = frappe.db.get_value(
		"Employee", {"custom_id_number": id_number, "name": ["!=", cstr(doc.get("name") or "")]}, "name"
	)
	if duplicate:
		frappe.throw(
			_("Identity number {0} is already used by {1}.<br>رقم الهوية {0} مستخدم من قبل {1}.").format(
				frappe.bold(id_number), frappe.bold(duplicate)
			),
			title=_("Duplicate Identity Number"),
		)


@frappe.whitelist(methods=["GET"])
def list_leave_requests(state=None, doctype=None, limit=None):
	"""Normalised inbox across the five Saudi leave doctypes.

	Rows from every doctype are merged into one shape, sorted newest first, and
	tagged with the actions the current user could take, so the portal renders
	one table instead of five.
	"""
	assert_portal_access()
	limit = _clean_limit(limit)
	wanted_state = cstr(state or "").strip().lower()

	rows = []
	for entry in LEAVE_REGISTRY:
		leave_doctype = entry[0]
		if doctype and leave_doctype != doctype:
			continue
		if not frappe.db.table_exists(leave_doctype):
			continue
		# a role may hold read on one leave doctype and not another; get_list
		# raises in that case rather than returning nothing
		if not frappe.has_permission(leave_doctype, "read", throw=False):
			continue

		fields = _existing_fields(
			leave_doctype, ["name", "employee", "creation", "modified", "workflow_state", "status", "docstatus"]
		)
		for field in (entry[2], entry[3], entry[4], entry[5]):
			fields += _existing_fields(leave_doctype, [field])

		states = _actionable_states(leave_doctype) if get_workflow_name(leave_doctype) else {}

		# get_list, not get_all: the app's permission_query_conditions already
		# scope most roles, and bypassing it here would widen every approver's
		# inbox to the whole site.
		for record in frappe.get_list(
			leave_doctype,
			fields=list(dict.fromkeys(fields)),
			order_by="creation desc",
			limit_page_length=limit,
		):
			record_state = _row_state(record)
			if wanted_state and record_state != wanted_state:
				continue

			# The document load is only worth it for rows that could carry an
			# action.  can_read is then True, False, or None when unchecked, and
			# the UI treats None as "open it and let the API decide".
			can_read = None
			if _maybe_actionable(leave_doctype, record, states):
				_doc, can_read = _load_row(leave_doctype, record)

			actions = _row_actions(leave_doctype, record, states, bool(can_read))
			rows.append(
				{
					"doctype": leave_doctype,
					"label": entry[1],
					"name": record.get("name"),
					"employee": record.get("employee"),
					"kind": record.get(entry[5]) if entry[5] else None,
					"from_date": record.get(entry[2]) if entry[2] else None,
					"to_date": record.get(entry[3]) if entry[3] else None,
					"days": flt(record.get(entry[4])) if entry[4] else 0.0,
					"state": record_state,
					"raw_state": record.get("workflow_state") or record.get("status"),
					"docstatus": cint(record.get("docstatus")),
					"actions": actions,
					"actionable": bool(actions),
					# the app's list query can surface a request the document
					# level check still refuses; the UI greys these out
					"can_read": can_read,
					"created_at": str(record.get("creation")) if record.get("creation") else None,
					"desk_url": desk_route(leave_doctype, record.get("name")),
				}
			)

	rows.sort(key=lambda row: row.get("created_at") or "", reverse=True)
	return {"rows": rows[:limit], "limit": limit, "total": len(rows)}


def _load_row(doctype, record):
	"""Load one row as a document and report whether the caller may read it.

	The document level check needs a real Document because Frappe reads the
	link fields to evaluate User Permissions, so a plain dict is not enough.
	"""
	doc = frappe.get_doc(doctype, record.get("name"))
	return doc, bool(frappe.has_permission(doctype, "read", doc=doc, throw=False))


def _maybe_actionable(doctype, record, states):
	"""Cheap pre-filter so only plausible rows pay for a document load.

	Most rows in a long leave history sit in a closed state, and their actions
	are empty regardless of permissions, so the expensive check is skipped.
	"""
	if get_workflow_name(doctype):
		return bool(states.get(record.get("workflow_state")))
	return cint(record.get("docstatus")) == 0


def _row_actions(doctype, record, states, can_read):
	"""Actions the current user may take on one row, already permission filtered.

	The doc-level read check is not optional.  The app's
	``permission_query_conditions`` hook returns an empty condition for elevated
	roles, which lets a User Permission slip past the list query while
	``has_permission(doc=...)`` still refuses the document.  Without this check
	the portal would offer an approve button that fails on click.
	"""
	if not can_read:
		return []

	if get_workflow_name(doctype):
		actions = list(states.get(record.get("workflow_state")) or [])
		if record.get("owner") == frappe.session.user:
			# mirrors frappe.model.workflow.has_approval_access: a self-created
			# request only moves if the transition opts into self approval
			actions = [item for item in actions if item.get("allow_self_approval")]
		return actions

	# no workflow: a draft the caller may submit is the only action
	if cint(record.get("docstatus")) == 0 and frappe.has_permission(
		doctype, "submit", doc=record.get("name"), throw=False
	):
		return [{"action": "submit", "next_state": None, "allow_self_approval": 0}]
	return []


@frappe.whitelist(methods=["GET"])
def get_leave_request(doctype, name):
	"""One request with the server's own view of the permitted transitions.

	The action list here is what the caller may actually do, computed by the
	framework, so the UI never offers a button the API would refuse.
	"""
	assert_portal_access()
	leave_doctype = cstr(doctype or "").strip()
	if not any(entry[0] == leave_doctype for entry in LEAVE_REGISTRY):
		frappe.throw(_("Unsupported leave document type."), frappe.ValidationError)

	# get_transitions() raises a bare PermissionError on denial, which surfaces
	# as a traceback rather than a 403, so refuse first with a readable message
	if not frappe.has_permission(leave_doctype, "read", doc=cstr(name), throw=False):
		frappe.throw(
			_("You do not have access to this leave request."),
			frappe.PermissionError,
		)

	doc = frappe.get_doc(leave_doctype, cstr(name))
	# get_transitions re-checks read and filters to this user's permitted moves
	transitions = get_transitions(doc)

	return {
		"doctype": leave_doctype,
		"name": doc.name,
		"docstatus": cint(doc.docstatus),
		"state": _row_state(doc.as_dict()),
		"raw_state": doc.get("workflow_state") or doc.get("status"),
		"has_workflow": bool(get_workflow_name(leave_doctype)),
		"actions": _dedupe_actions(transitions),
		# the detail panel's "open in Desk" button reads this; without it the
		# link renders as "#" and the click goes nowhere
		"desk_url": desk_route(leave_doctype, doc.name),
		"fields": {
			key: _jsonable(value)
			for key, value in doc.as_dict().items()
			if not key.startswith("_") and key not in ("doctype", "name")
		},
	}


def _dedupe_actions(transitions):
	"""Collapse transitions that share an action and destination.

	A workflow commonly declares one transition per role, so a user holding two
	of those roles sees the same action twice and would render duplicate buttons.
	"""
	seen = set()
	actions = []
	for transition in transitions or []:
		key = (transition.get("action"), transition.get("next_state"))
		if key in seen:
			continue
		seen.add(key)
		actions.append({"action": key[0], "next_state": key[1]})
	return actions


def _jsonable(value):
	if hasattr(value, "strftime"):
		return str(value)
	if isinstance(value, (int, float, str, bool)) or value is None:
		return value
	return str(value)


@frappe.whitelist(methods=["POST"])
def apply_leave_action(doctype, name, action):
	"""Apply a workflow transition after re-deriving that it is permitted.

	The client supplies only the action name.  Whether it is allowed is decided
	here from the workflow and the caller's roles, which is the whole point of
	routing through this function rather than letting the client patch a
	workflow_state.
	"""
	assert_portal_access()
	leave_doctype = cstr(doctype or "").strip()
	if not any(entry[0] == leave_doctype for entry in LEAVE_REGISTRY):
		frappe.throw(_("Unsupported leave document type."), frappe.ValidationError)

	doc = frappe.get_doc(leave_doctype, cstr(name))
	requested = cstr(action or "").strip()
	if not requested:
		frappe.throw(_("An action is required."), frappe.ValidationError)

	permitted = get_transitions(doc, raise_exception=False)
	match = next((t for t in permitted if t.get("action") == requested), None)
	if not match:
		frappe.throw(
			_("You are not allowed to perform '{0}' on this request.<br>غير مسموح لك بتنفيذ '{0}' على هذا الطلب.").format(
				frappe.bold(requested)
			),
			frappe.PermissionError,
		)

	if not has_approval_access(frappe.session.user, doc, match):
		frappe.throw(
			_("You cannot approve a request you created yourself.<br>لا يمكنك الموافقة على طلب أنشأته بنفسك."),
			frappe.PermissionError,
		)

	apply_workflow(doc, requested)

	return {
		"doctype": leave_doctype,
		"name": doc.name,
		"action": requested,
		"state": _row_state(doc.as_dict()),
		"raw_state": doc.get("workflow_state") or doc.get("status"),
		"next_state": match.get("next_state"),
	}


@frappe.whitelist(methods=["POST"])
def submit_leave_request(doctype, name):
	"""Submit a request that has no workflow.

	Special Leave and Maternity Paternity Leave have no workflow, so a draft is
	the only thing an approver can act on.  Submitting runs each doctype's own
	validation, which is what sets Special Leave status to approved and rejects
	a Maternity request with no medical certificate.
	"""
	assert_portal_access()
	leave_doctype = cstr(doctype or "").strip()
	if not any(entry[0] == leave_doctype for entry in LEAVE_REGISTRY):
		frappe.throw(_("Unsupported leave document type."), frappe.ValidationError)

	if get_workflow_name(leave_doctype):
		frappe.throw(
			_("This request follows an approval workflow. Use the approval actions instead of submitting it.<br>هذا الطلب يمر بسير موافقات. استخدم إجراءات الموافقة بدلاً من إرساله."),
			frappe.ValidationError,
		)

	doc = frappe.get_doc(leave_doctype, cstr(name))
	if cint(doc.docstatus) == 1:
		frappe.throw(_("This request has already been submitted."), frappe.ValidationError)

	assert_doctype_permissions(leave_doctype, "submit", doc=doc)
	doc.submit()

	return {
		"doctype": leave_doctype,
		"name": doc.name,
		"action": "submit",
		"state": _row_state(doc.as_dict()),
		"raw_state": doc.get("workflow_state") or doc.get("status"),
	}
