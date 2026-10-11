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

import calendar
import json
import re
from datetime import date
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
from frappe.utils import (
	add_days,
	cint,
	cstr,
	flt,
	get_datetime,
	getdate,
	now,
	nowdate,
)

from saudi_hr.scripts.rename_employees_to_employee_number import (
	is_valid_name,
	rename_named_after_employee,
)
from saudi_hr.saudi_hr.utils import (
	assert_doctype_permissions,
	get_employee_basic_salary,
	get_employee_salary_components,
	is_saudi_nationality,
)
from saudi_hr.saudi_hr.workflow_catalogue import role_label, state_bucket

# Roles allowed to open the admin portal at all.  Approval rights are
# deliberately absent here: they come from each workflow, so a Department
# Approver reaches the page and sees only their own queue without being a
# general administrator.
# The verb each endpoint allows. The page mirrors this to decide whether to
# send a GET or a POST, and the tests assert the two stay in step, because
# Frappe refuses a mismatched verb with "Not permitted" before the permission
# check even runs.
POST_ONLY_METHODS = frozenset(
	{
		"create_employee",
		"update_employee",
		"apply_leave_action",
		"submit_leave_request",
		"correct_attendance_day",
		"remove_attendance_day",
		"create_eosb_settlement",
		"issue_hr_document",
		"create_termination_notice",
		"create_exit_clearance",
		"apply_offboarding_action",
		"save_exit_clearance",
		"create_eosb_from_case",
		"submit_eosb",
		"create_exit_interview",
		"create_leave_disbursement",
		"settle_final_settlement",
	}
)

ADMIN_PORTAL_ROLES = frozenset(
	{
		"System Manager",
		"HR Manager",
		"HR User",
		"Department Approver",
		"Leave Approver",
		"Accounts Manager",
		"Supervisor",
		"General Manager",
		"Attendance Officer",
	}
)

# The panels the admin shell can show, in rail order.  A restricted role opens
# only the subset it is granted; the first one it may see is its landing panel.
PORTAL_PANELS = (
	"dashboard",
	"approvals",
	"employees",
	"attendance",
	"report",
	"clearance",
	"documents",
)

ATTENDANCE_OFFICER_ROLE = "Attendance Officer"
SUPERVISOR_ROLE = "Supervisor"

# The panels each restricted role may open.  A role missing from this map is
# unrestricted and opens every panel, so an approver role can never be locked
# out by omission.  A user holding several restricted roles gets their union.
PANEL_ACCESS = {
	ATTENDANCE_OFFICER_ROLE: frozenset({"attendance", "employees"}),
	SUPERVISOR_ROLE: frozenset({"approvals"}),
}

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
	# Not leave, but the same shape: a per-employee request with its own
	# approval workflow.  Visa issuance, residence and Iqama paperwork all land
	# here as request_type, so the inbox keeps one row shape for them too.
	(
		"HR Service Request",
		"Visa & Services / تأشيرات وخدمات",
		"from_date",
		"to_date",
		# a service request has no day count; only a value field, which is a
		# money amount for the fee-bearing types and 0 elsewhere
		None,
		"request_type",
		"workflow_state",
	),
	(
		"Saudi Punch Correction",
		"Punch Correction / تصحيح البصمة",
		# a correction lands on one day, so the range is that single day
		"attendance_date",
		"attendance_date",
		# no day count; the two corrected times carry the substance
		None,
		None,
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

# Two entries in the registry are not leave: a visa/service request and a punch
# correction share the row shape (a per-employee request with a workflow) but
# carry no leave days, so the day-by-day leave map skips them by name.
NON_LEAVE_DOCTYPES = ("HR Service Request", "Saudi Punch Correction")

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

# One employee's request history in the detail modal.
EMPLOYEE_REQUEST_LIMIT = 40

# Attendance: recent days in the employee dialog, and the window the
# company-wide overview walks by default.
ATTENDANCE_DOCTYPE = "Saudi Daily Attendance"
CHECKIN_DOCTYPE = "Saudi Employee Checkin"
PUNCH_CORRECTION_DOCTYPE = "Saudi Punch Correction"
EMPLOYEE_ATTENDANCE_DAYS = 15
DEFAULT_ATTENDANCE_DAYS = 30
MAX_ATTENDANCE_DAYS = 180
# One row per day in the report table. A month cannot exceed 31, so this only
# bites on a date range, where it is what keeps the table readable.
REPORT_DAY_ROWS = 62
# Today's punches in the report. Capping this by time drops whoever punched
# earliest, so the cap is high enough to name the whole day for a normal
# headcount rather than a dozen of the most recent taps.
TODAY_PUNCH_ROWS = 100

# The status column is a bilingual Select, so the value carries both languages.
# Keying on the English prefix keeps the counters stable when the label text
# changes, and lets the portal render one readable word of its own.
ATTENDANCE_STATUSES = (
	("Present / حاضر", "present"),
	("Absent / غائب", "absent"),
	("Half Day / نصف يوم", "half_day"),
	("On Leave / إجازة", "on_leave"),
)
ATTENDANCE_STATUS_KEYS = dict(ATTENDANCE_STATUSES)
# What a department breakdown has to carry, so the buckets and the totals are
# summed over the same names instead of being listed twice.
ATTENDANCE_COUNT_KEYS = (
	"days",
	"present",
	"absent",
	"half_day",
	"on_leave",
	"other",
	"late_days",
	"late_minutes",
	"hours",
)

# The week's rest days when an employee has no Holiday List to say otherwise.
# Friday and Saturday are the Saudi weekend, and the same pair the self-service
# portal (api.get_monthly_attendance) and Monthly Attendance Record already
# fall back to, so a site that never assigned a Holiday List still reads right.
DEFAULT_WEEKLY_OFF_DAYS = (4, 5)


def _attendance_status_key(value):
	"""'Present / حاضر' -> 'present'.

	Anything else is 'other': a status option the portal does not know yet
	still has to land in a bucket, and its own text is carried alongside so the
	row can show what was actually recorded.
	"""
	text = cstr(value or "").strip()
	if not text:
		return None
	if text in ATTENDANCE_STATUS_KEYS:
		return ATTENDANCE_STATUS_KEYS[text]
	for raw, key in ATTENDANCE_STATUSES:
		if text.startswith(raw.split(" /")[0]) or raw.startswith(text):
			return key
	return "other"


def _time_only(value):
	"""Datetime -> 'HH:MM', so the dialog shows a punch time and not a date."""
	if not value:
		return None
	moment = get_datetime(value)
	return moment.strftime("%H:%M") if moment else None


def _attendance_period_counts(rows):
	"""Count one attendance window without trusting a SQL GROUP BY.

	The status column holds free bilingual text, so the grouping is done here
	against the same mapping the dialog uses. That keeps the counters and the
	rows a user sees from ever disagreeing.
	"""
	counts = {"present": 0, "absent": 0, "half_day": 0, "on_leave": 0, "other": 0}
	late_days = 0
	late_minutes = 0.0
	hours = 0.0
	for row in rows:
		key = _attendance_status_key(row.get("status"))
		counts[key if key in counts else "other"] += 1
		late_minutes += flt(row.get("late_minutes"))
		hours += flt(row.get("working_hours"))
		if flt(row.get("late_minutes")) > 0 or row.get("late_entry"):
			late_days += 1
	return {
		"days": len(rows),
		"present": counts["present"],
		"absent": counts["absent"],
		"half_day": counts["half_day"],
		"on_leave": counts["on_leave"],
		"other": counts["other"],
		"late_days": late_days,
		"late_minutes": round(late_minutes, 1),
		"hours": round(hours, 2),
	}


def _attendance_rows(employee, limit=EMPLOYEE_ATTENDANCE_DAYS, from_date=None, to_date=None):
	"""Attendance days for one employee, newest first."""
	if not frappe.has_permission(ATTENDANCE_DOCTYPE, "read", throw=False):
		return None
	# a list of conditions rather than one ["between", ...] filter: between
	# silently matches nothing on this field, and an empty report reads as
	# "nobody worked" rather than as a broken query
	filters = [["employee", "=", employee]]
	if from_date:
		filters.append(["attendance_date", ">=", str(from_date)])
	if to_date:
		filters.append(["attendance_date", "<=", str(to_date)])
	fields = _existing_fields(
		ATTENDANCE_DOCTYPE,
		[
			"name",
			"employee",
			"attendance_date",
			"status",
			"in_time",
			"out_time",
			"working_hours",
			"late_entry",
			"late_minutes",
			"early_exit",
			"early_exit_minutes",
			"note",
		],
	)
	return frappe.get_list(
		ATTENDANCE_DOCTYPE,
		filters=filters,
		fields=fields,
		order_by="attendance_date desc",
		limit_page_length=limit,
	)


def _attendance_view(row, corrections=None):
	day = str(row.get("attendance_date")) if row.get("attendance_date") else None
	corrected = bool(corrections and corrections.get(day))
	return {
		"name": row.get("name"),
		"employee": row.get("employee"),
		"date": day,
		"status": row.get("status"),
		"status_key": _attendance_status_key(row.get("status")),
		"in_time": _time_only(row.get("in_time")),
		"out_time": _time_only(row.get("out_time")),
		"hours": flt(row.get("working_hours")) or None,
		"late_minutes": flt(row.get("late_minutes")) or None,
		"early_exit_minutes": flt(row.get("early_exit_minutes")) or None,
		"note": cstr(row.get("note") or "").strip() or None,
		"corrected": corrected,
		"correction_reason": (corrections.get(day) if corrected else None),
		"missing": False,
		"desk_url": desk_route(ATTENDANCE_DOCTYPE, row.get("name")),
	}


def _latest_checkin(employee):
	"""Today's punch, so the dialog can say 'in since 08:51' before the day
	is closed and a Saudi Daily Attendance row exists."""
	if not frappe.has_permission(CHECKIN_DOCTYPE, "read", throw=False):
		return None
	fields = _existing_fields(CHECKIN_DOCTYPE, ["name", "log_type", "time", "late_minutes", "attendance_location"])
	# today only: an unpunched day inherits the previous day's last punch and
	# would then be reported as though the employee were on site. The window
	# ends at tomorrow rather than at now(), because a punch the clock or a
	# device put a few minutes ahead still happened today and hiding it would
	# report an empty day for someone who is standing there.
	last = frappe.get_list(
		CHECKIN_DOCTYPE,
		filters=[
			["employee", "=", employee],
			["time", ">=", nowdate()],
			["time", "<", add_days(nowdate(), 1)],
		],
		fields=fields,
		order_by="time desc",
		limit_page_length=1,
	)
	if not last:
		return None
	row = last[0]
	return {
		"log_type": row.get("log_type"),
		"time": _time_only(row.get("time")),
		"late_minutes": flt(row.get("late_minutes")) or None,
		"location": row.get("attendance_location"),
		"name": row.get("name"),
		"desk_url": desk_route(CHECKIN_DOCTYPE, row.get("name")),
	}


def _employee_attendance(employee):
	"""Today's punch, this month's tally and the recent days for one employee."""
	today = nowdate()
	month_start = today[:7] + "-01"
	month_rows = _attendance_rows(employee, limit=0, from_date=month_start) or []
	recent_rows = _attendance_rows(employee, limit=EMPLOYEE_ATTENDANCE_DAYS) or []

	today_row = next((row for row in recent_rows if str(row.get("attendance_date")) == today), None)
	return {
		"readable": frappe.has_permission(ATTENDANCE_DOCTYPE, "read", throw=False),
		"today": _attendance_view(today_row) if today_row else None,
		"checkin": _latest_checkin(employee),
		"month": _attendance_period_counts(month_rows),
		"month_label": month_start[:7],
		"recent": [_attendance_view(row) for row in recent_rows],
		"recent_limit": EMPLOYEE_ATTENDANCE_DAYS,
		"truncated": len(recent_rows) >= EMPLOYEE_ATTENDANCE_DAYS,
	}


def _mask_identifier(value):
	"""Show enough of an id or IBAN to recognise it, never enough to use it.

	The portal is a read-only surface, so there is no reason to hand back a full
	IBAN or national id to a browser that only displays it.
	"""
	text = cstr(value or "").strip()
	if len(text) <= 4:
		return "*" * len(text) or None
	return "*" * (len(text) - 4) + text[-4:]


def assert_portal_access():
	"""Refuse the whole API to users who hold none of the admin roles."""
	if frappe.session.user == "Guest":
		frappe.throw(_("يجب تسجيل الدخول أولاً."), frappe.PermissionError)

	if not ADMIN_PORTAL_ROLES.intersection(frappe.get_roles()):
		frappe.throw(
			_("You do not have access to the HR administration portal."),
			frappe.PermissionError,
		)


def visible_panels(user=None):
	"""The admin panels the user may open, in rail order.

	An unrestricted role opens everything; a restricted role opens only its
	grant.  Holding an unrestricted role alongside a restricted one restores
	the full admin, so an HR manager is never narrowed by a supervisor grant.
	"""
	user = user or frappe.session.user
	if user == "Administrator":
		return list(PORTAL_PANELS)

	portal_roles = set(frappe.get_roles(user)).intersection(ADMIN_PORTAL_ROLES)
	if not portal_roles:
		return []
	if any(role not in PANEL_ACCESS for role in portal_roles):
		return list(PORTAL_PANELS)

	allowed = set()
	for role in portal_roles:
		allowed |= PANEL_ACCESS[role]
	return [panel for panel in PORTAL_PANELS if panel in allowed]


def assert_panel_access(*panels):
	"""Refuse a caller who may not open any of the named panels.

	The page hides the rail items a role cannot use, but that is presentation:
	this is the boundary that a hand-crafted request cannot walk around.
	"""
	assert_portal_access()
	if not set(panels).intersection(visible_panels()):
		frappe.throw(
			_("You do not have access to this section."),
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
	panels = visible_panels()
	return {
		"user": frappe.session.user,
		"roles": sorted(frappe.get_roles()),
		"panels": panels,
		"default_panel": panels[0] if panels else "",
		"can_manage_employees": _can_manage_employees(),
		"leave_types": [_doctype_entry(entry) for entry in LEAVE_REGISTRY],
		"lang": frappe.db.get_value("User", frappe.session.user, "language") or "en",
	}


def _can_manage_employees():
	return bool(frappe.has_permission("Employee", "create", throw=False))


@frappe.whitelist(methods=["GET"])
def get_admin_dashboard():
	assert_portal_access()
	assert_panel_access("dashboard", "report")

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
	state = state_bucket(row.get("workflow_state"))
	if state:
		return state

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
	assert_panel_access("employees", "attendance", "clearance")
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
def get_employee_detail(name):
	"""One employee's portal view, so the admin page never has to leave for Desk.

	Same permission rule as ``list_employees``: a User Permission pinned to one
	employee narrows this to that employee, and a caller with no read on Employee
	is refused rather than handed an empty profile.
	"""
	assert_portal_access()
	assert_panel_access("employees")
	employee = cstr(name or "").strip()
	if not employee:
		frappe.throw(_("Employee is required."), frappe.ValidationError)

	# the doc-level check evaluates User Permissions against the real document,
	# which a plain dict from get_list cannot do
	if not frappe.has_permission("Employee", "read", doc=employee, throw=False):
		frappe.throw(_("You do not have access to this employee."), frappe.PermissionError)

	doc = frappe.get_doc("Employee", employee)
	meta = frappe.get_meta("Employee")

	candidates = (
		"employee_number",
		"first_name",
		"middle_name",
		"last_name",
		"date_of_birth",
		"gender",
		"marital_status",
		"nationality",
		"company",
		"department",
		"designation",
		"branch",
		"grade",
		"reports_to",
		"employment_type",
		"status",
		"date_of_joining",
		"date_of_leaving",
		"company_email",
		"personal_email",
		"mobile_no",
		"custom_full_name_english",
		"custom_nationality",
		"custom_id_type",
		"custom_id_number",
		"custom_id_expiration_date",
		"iban",
	)
	# IBAN and national id are secrets; the portal only displays them
	SECRET_FIELDS = ("iban", "custom_id_number")

	profile = {}
	for field in candidates:
		if not meta.has_field(field):
			continue
		value = _jsonable(doc.get(field))
		if field in SECRET_FIELDS:
			value = _mask_identifier(value)
		profile[field] = value

	profile["full_name"] = doc.get("employee_name") or " ".join(
		part for part in (doc.get("first_name"), doc.get("middle_name"), doc.get("last_name")) if part
	)
	profile["name"] = doc.name
	profile["desk_url"] = desk_route("Employee", doc.name)

	# the same requests the approvals inbox would show for this person, so an
	# admin can see an employee's request history without switching pages
	requests = []
	for entry in LEAVE_REGISTRY:
		doctype = entry[0]
		if not frappe.db.table_exists(doctype) or not frappe.has_permission(doctype, "read", throw=False):
			continue
		fields = _existing_fields(
			doctype,
			["name", "creation", "workflow_state", "status", "docstatus", entry[2], entry[3], entry[4], entry[5]],
		)
		for record in frappe.get_list(
			doctype,
			filters={"employee": doc.name},
			fields=list(dict.fromkeys(fields)),
			order_by="creation desc",
			limit_page_length=EMPLOYEE_REQUEST_LIMIT,
		):
			requests.append(
				{
					"doctype": doctype,
					"label": entry[1],
					"name": record.get("name"),
					"kind": record.get(entry[5]) if entry[5] else None,
					"days": flt(record.get(entry[4])) if entry[4] else None,
					"state": _row_state(record),
					"created_at": str(record.get("creation")) if record.get("creation") else None,
					"desk_url": desk_route(doctype, record.get("name")),
				}
			)
	requests.sort(key=lambda row: row.get("created_at") or "", reverse=True)

	return {
		"profile": profile,
		"requests": requests,
		"truncated": len(requests) >= EMPLOYEE_REQUEST_LIMIT,
		"attendance": _employee_attendance(doc.name),
	}


@frappe.whitelist(methods=["GET"])
def get_employee_form_options():
	assert_portal_access()
	assert_panel_access("employees")
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
	assert_panel_access("employees")

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


@frappe.whitelist(methods=["POST"])
def update_employee(payload_json):
	"""Edit an existing employee from the admin form.

	Only ``EMPLOYEE_WRITABLE_FIELDS`` are read back, so a crafted payload
	cannot reach the salary, bank or review fields Desk owns.  The employee
	number is left alone: it is also the document name, and renaming a live
	document would repoint every link to it, so the number is fixed once at
	creation.
	"""
	assert_portal_access()
	assert_panel_access("employees")

	try:
		payload = json.loads(cstr(payload_json or "{}"))
	except (TypeError, ValueError):
		frappe.throw(_("Invalid employee data."), frappe.ValidationError)
	if not isinstance(payload, dict):
		frappe.throw(_("Invalid employee data."), frappe.ValidationError)

	name = cstr(payload.get("name") or "").strip()
	if not name or not frappe.db.exists("Employee", name):
		frappe.throw(_("Employee not found.<br>الموظف غير موجود."), title=_("Not Found"))

	doc = frappe.get_doc("Employee", name)
	# read back only the allowed fields, skipping the document name and the
	# number that mirrors it so an edit can never orphan existing links
	for key, value in payload.items():
		if key in ("name", "employee_number"):
			continue
		if key in EMPLOYEE_WRITABLE_FIELDS and value is not None:
			doc.set(key, value)

	_validate_employee_fields(doc)
	_validate_id_number(doc)

	assert_doctype_permissions("Employee", "write", doc=doc)
	doc.save()

	return {"name": name, "updated": True, "desk_url": desk_route("Employee", name)}


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
	assert_panel_access("approvals")
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
					"from_date": str(record.get(entry[2])) if entry[2] and record.get(entry[2]) else (record.get(entry[2]) or None),
					"to_date": str(record.get(entry[3])) if entry[3] and record.get(entry[3]) else (record.get(entry[3]) or None),
					# null rather than 0 when the doctype has no day field, so the UI
					# can drop the chip instead of claiming a 0-day request
					"days": flt(record.get(entry[4])) if entry[4] else None,
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
		if record.get("owner") == frappe.session.user and frappe.session.user != "Administrator":
			# mirrors frappe.model.workflow.has_approval_access: a self-created
			# request only moves if the transition opts into self approval.  The
			# Administrator is exempt there, and get_transitions (the source
			# apply_workflow trusts) returns the actions for them, so the row
			# must show them too.
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
	assert_panel_access("approvals")
	leave_doctype = cstr(doctype or "").strip()
	entry = next((item for item in LEAVE_REGISTRY if item[0] == leave_doctype), None)
	if not entry:
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
		# the detail panel labels the request with this; the registry says which
		# field carries it, and it may be absent on some doctypes
		"kind": doc.get(entry[5]) if entry[5] else None,
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
	assert_panel_access("approvals")
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
	assert_panel_access("approvals")
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


@frappe.whitelist(methods=["GET"])
def get_attendance_report(employee=None, month=None, from_date=None, to_date=None, limit=25):
	"""The attendance panel: one window, counted for one employee or by department.

	`month` ("YYYY-MM") and an explicit `from_date`/`to_date` pair are two ways
	to ask for the same thing, so a caller picks whichever it has; a month
	wins, because it is the more specific of the two.  The window is capped and
	a reversed pair is swapped, so a mistyped range cannot ask for an unbounded
	walk or come back silently empty.
	"""
	assert_portal_access()
	assert_panel_access("attendance")

	window = _attendance_window(from_date, to_date, month)
	readable = frappe.has_permission(ATTENDANCE_DOCTYPE, "read", throw=False)

	if employee:
		# the same document-level check the employee dialog makes: a User
		# Permission can hide an employee the directory still listed
		if not frappe.has_permission("Employee", "read", doc=employee):
			frappe.throw(_("You do not have access to this employee."), frappe.PermissionError)

	payload = {
		"readable": readable,
		"from_date": window["from_date"],
		"to_date": window["to_date"],
		"span_days": window["days"],
		"scope": "employee" if employee else "departments",
		"employee": _attendance_employee(employee) if employee else None,
		"scoped": bool(get_user_permissions(frappe.session.user).get("Employee")),
		"month": window.get("month"),
		# both shapes are always present so the client can read `scope` instead
		# of probing for keys; only the one in scope carries rows
		"days": [],
		"departments": [],
		"department_count": 0,
	}
	if not readable:
		payload.update({"totals": None, "days": [], "truncated": False, "today": []})
		return payload

	# the totals follow the scope: a report about one employee must not carry
	# the whole company's days in its own tiles
	payload["totals"] = _attendance_period_counts(
		_attendance_window_rows(window, [employee] if employee else None)
	)
	if employee:
		payload["days"] = _attendance_days(window, employee)
		payload["truncated"] = len(payload["days"]) >= REPORT_DAY_ROWS
	else:
		payload["departments"], payload["department_count"] = _attendance_departments(window, limit)
		payload["truncated"] = len(payload["departments"]) < payload["department_count"]
	payload["today"] = _attendance_today_rows(employee)
	return payload


def _attendance_employee(employee):
	row = frappe.db.get_value(
		"Employee", employee, ["name", "employee_name", "employee_number"], as_dict=True
	)
	if not row:
		return {"name": employee, "employee_name": employee, "employee_number": employee}
	return {
		"name": row.get("name"),
		"employee_name": row.get("employee_name") or employee,
		"employee_number": row.get("employee_number") or row.get("name"),
	}


def _attendance_window_rows(window, employees):
	"""Attendance days inside the window, for `employees` or for everyone.

	The window caps the walk; the department scope is bounded by that alone,
	which is why the row count is reported back with the result rather than
	left to look exact.
	"""
	filters = [
		# see _attendance_rows: "between" matches nothing on this field
		["attendance_date", ">=", window["from_date"]],
		["attendance_date", "<=", window["to_date"]],
	]
	if employees:
		filters.insert(0, ["employee", "in", list(employees)])
	return frappe.get_list(
		ATTENDANCE_DOCTYPE,
		filters=filters,
fields=_existing_fields(
				ATTENDANCE_DOCTYPE,
				[
					"name",
					"employee",
					"attendance_date",
					"status",
					"in_time",
					"out_time",
					"working_hours",
					"late_entry",
					"late_minutes",
					"early_exit",
					"early_exit_minutes",
					"note",
				],
			),
		order_by="attendance_date desc",
		limit_page_length=0,
	)


def _attendance_corrections(employee, from_date, to_date):
	"""Applied check-in corrections in the window, by day.

	The once-per-day guard lives in Saudi Punch Correction itself, so a day
	that already has an applied correction is reported back as ``corrected``
	and the table stops offering a second edit for it.
	"""
	if not frappe.has_permission(PUNCH_CORRECTION_DOCTYPE, "read", throw=False):
		return {}
	rows = frappe.get_all(
		PUNCH_CORRECTION_DOCTYPE,
		filters=[
			["employee", "=", employee],
			["attendance_date", ">=", str(from_date)],
			["attendance_date", "<=", str(to_date)],
			["docstatus", "=", 1],
			["applied", "=", 1],
		],
		fields=["attendance_date", "correction_reason"],
	)
	return {str(row.get("attendance_date")): row.get("correction_reason") for row in rows}


def _attendance_days(window, employee):
	"""One row per calendar day in the window, oldest first and capped.

	A month is a calendar, not a ledger: every day is listed, and a day with no
	attendance row yet comes back marked ``missing`` (and ``future`` when it is
	still ahead of today), so the panel can offer to register it instead of
	pretending the date does not exist.

	A day with no row is not always a gap to fill.  It may be leave the employee
	is on, a holiday, or the weekend; those days are described from the records
	that already exist rather than left to read as a missing record.
	"""
	rows = _attendance_window_rows(window, [employee])
	by_date = {str(row.get("attendance_date")): row for row in rows}
	corrections = _attendance_corrections(employee, window["from_date"], window["to_date"])
	holidays = _holiday_dates(employee, window["from_date"], window["to_date"])
	leaves = _leave_dates(employee, window["from_date"], window["to_date"])
	days = [
		_attendance_view(by_date[key], corrections)
		if key in by_date
		else _off_attendance_view(key, employee, holidays.get(key), leaves.get(key))
		for key in _each_date(window["from_date"], window["to_date"])
	]
	# a month reads top-down from day 1; keep the most recent window when capped
	return days[-REPORT_DAY_ROWS:]


def _each_date(from_date, to_date):
	"""Every calendar day between the two dates, inclusive, oldest first."""
	day = getdate(from_date)
	end = getdate(to_date)
	while day <= end:
		yield str(day)
		day = add_days(day, 1)


def _holiday_list_for(employee):
	"""The Holiday List that applies to this employee: their own, else the company's.

	Both fields are optional in ERPNext, and a site that set neither still has
	to read right, so a miss falls through to the built-in weekend.
	"""
	if not employee:
		return None
	fields = _existing_fields("Employee", ["holiday_list", "company"])
	row = frappe.db.get_value("Employee", employee, fields, as_dict=True) if fields else None
	if not row:
		return None
	if row.get("holiday_list"):
		return row["holiday_list"]
	if row.get("company") and _existing_fields("Company", ["default_holiday_list"]):
		return frappe.db.get_value("Company", row["company"], "default_holiday_list")
	return None


def _holiday_dates(employee, from_date, to_date):
	"""Holiday and weekly-off days in the window, by date.

	The employee's Holiday List is the source, so two people can rest on
	different days (Friday and Saturday for one, Saturday only for another).
	A day can carry both a named holiday and a weekly off, and the name is what
	a person reads, so a named holiday wins.  No list at all falls back to the
	built-in Friday/Saturday weekend.
	"""
	from_date, to_date = str(from_date), str(to_date)
	holiday_list = _holiday_list_for(employee)
	if not holiday_list:
		return {
			day: {"weekly_off": True, "description": None}
			for day in _each_date(from_date, to_date)
			if getdate(day).weekday() in DEFAULT_WEEKLY_OFF_DAYS
		}
	if not frappe.db.table_exists("Holiday"):
		return {}
	rows = frappe.get_all(
		"Holiday",
		filters=[
			["parent", "=", holiday_list],
			["holiday_date", ">=", from_date],
			["holiday_date", "<=", to_date],
		],
		fields=["holiday_date", "weekly_off", "description"],
	)
	days = {}
	for row in rows:
		day = str(row.get("holiday_date"))
		weekly_off = bool(cint(row.get("weekly_off")))
		# keep a named holiday over a weekly off, and the first of either
		if day in days and (not days[day]["weekly_off"] or weekly_off):
			continue
		days[day] = {
			"weekly_off": weekly_off,
			"description": cstr(row.get("description") or "").strip() or None,
		}
	return days


def _leave_dates(employee, from_date, to_date):
	"""Approved leave days in the window, by date, from the inbox's own doctypes.

	Only approved records count: a rejected or still-pending request is not
	leave the employee is on.  When two overlap, the first doctype in
	LEAVE_REGISTRY wins, which is the order the inbox lists them in.
	"""
	if not employee:
		return {}
	from_date, to_date = str(from_date), str(to_date)
	days = {}
	for entry in LEAVE_REGISTRY:
		doctype, label, start_field, end_field, _days_field, _kind_field, _state_field = entry
		if doctype in NON_LEAVE_DOCTYPES:
			continue
		if not frappe.has_permission(doctype, "read", throw=False):
			continue
		fields = _existing_fields(
			doctype, ["name", start_field, end_field, "workflow_state", "status", "docstatus"]
		)
		if start_field not in fields or end_field not in fields:
			continue
		rows = frappe.get_list(
			doctype,
			filters=[
				["employee", "=", employee],
				[start_field, "<=", to_date],
				[end_field, ">=", from_date],
			],
			fields=fields,
			limit_page_length=0,
		)
		for row in rows:
			if _row_state(row) != "approved":
				continue
			start = max(getdate(row.get(start_field)), getdate(from_date))
			end = min(getdate(row.get(end_field)), getdate(to_date))
			for day in _each_date(str(start), str(end)):
				days.setdefault(day, label)
	return days


def _off_attendance_view(day, employee, holiday, leave):
	"""A day with no attendance row, described as leave, a holiday or a rest day.

	Leave wins over a holiday.  The rest of the record still comes from
	_missing_attendance_view, so the dialog treats it exactly like any other day
	with no row: only the status the table shows changes.
	"""
	view = _missing_attendance_view(day, employee)
	if leave:
		view.update({"status_key": "on_leave", "status": leave, "reason": leave})
	elif holiday:
		if holiday["weekly_off"]:
			# a weekly off is the label on its own; its Holiday row carries only
			# the weekday name, which the label already says
			view["status_key"] = "weekly_off"
		else:
			view.update(
				{
					"status_key": "holiday",
					"status": holiday["description"],
					"reason": holiday["description"],
				}
			)
	return view


def _missing_attendance_view(day, employee):
	"""A calendar day the employee has no attendance row for yet.

	``name`` stays None so the page cannot point the edit dialog at a record
	that does not exist; the registration goes by employee and date instead.
	"""
	today = nowdate()
	return {
		"name": None,
		"employee": employee,
		"date": day,
		"status": None,
		"status_key": "missing",
		"reason": None,
		"in_time": None,
		"out_time": None,
		"hours": None,
		"late_minutes": None,
		"early_exit_minutes": None,
		"note": None,
		"corrected": False,
		"correction_reason": None,
		"missing": True,
		"future": day > today,
		"desk_url": None,
	}


def _attendance_departments(window, limit):
	"""Per department totals, biggest first, plus how many there were.

	Grouped on the department rather than on the employee, so one person's
	three days land in one row instead of three rows of one day each, and the
	employee count in that row is the number of distinct people behind it.
	"""
	departments = {}
	employees_of = {}
	for row in _attendance_window_rows(window, None):
		key = row.get("employee")
		if key not in employees_of:
			employees_of[key] = frappe.db.get_value("Employee", key, "department") or ""
		department = employees_of[key]
		bucket = departments.get(department)
		if bucket is None:
			bucket = departments[department] = {
				"department": department,
				"employees": set(),
				**_attendance_period_counts([]),
			}
		bucket["employees"].add(key)
		one = _attendance_period_counts([row])
		for name in ATTENDANCE_COUNT_KEYS:
			bucket[name] += one[name]

	summary = sorted(
		(
			{
				"department": bucket["department"],
				"employees": len(bucket["employees"]),
				"days": bucket["days"],
				"present": bucket["present"],
				"absent": bucket["absent"],
				"half_day": bucket["half_day"],
				"on_leave": bucket["on_leave"],
				"other": bucket["other"],
				"late_days": bucket["late_days"],
				"late_minutes": round(bucket["late_minutes"], 1),
				"hours": round(bucket["hours"], 2),
			}
			for bucket in departments.values()
		),
		# biggest attendance first, and an unnamed department last rather than
		# first, because "" would otherwise sort to the top
		key=lambda row: (row["department"] == "", -row["days"], row["department"]),
	)
	capped = summary[: cint(limit) or 25]
	return capped, len(summary)


def _attendance_window(from_date=None, to_date=None, month=None):
	"""Normalise the requested window.

	Defaults to the last 30 days, reads "YYYY-MM" as that whole month, swaps a
	reversed pair rather than returning nothing for it, and caps the span so
	one request cannot walk an unbounded amount of history.
	"""
	month = cstr(month or "").strip()
	if month:
		start, end = _attendance_month(month)
	elif from_date or to_date:
		start = getdate(from_date) if from_date else None
		end = getdate(to_date) if to_date else getdate(nowdate())
		if not start:
			start = add_days(end, -(DEFAULT_ATTENDANCE_DAYS - 1))
		if start > end:
			start, end = end, start
		if (end - start).days + 1 > MAX_ATTENDANCE_DAYS:
			start = add_days(end, -(MAX_ATTENDANCE_DAYS - 1))
	else:
		end = getdate(nowdate())
		start = add_days(end, -(DEFAULT_ATTENDANCE_DAYS - 1))

	return {
		"from_date": str(start),
		"to_date": str(end),
		"days": (end - start).days + 1,
		"month": month or None,
	}


def _attendance_month(month):
	"""'2026-10' -> the first and last day of that month.

	A malformed month is refused rather than ignored: falling back to the
	default window would show a real report for the wrong period.
	"""
	match = re.match(r"^(\d{4})-(\d{2})$", month)
	if not match:
		frappe.throw(_("Month must be written as YYYY-MM."), frappe.ValidationError)
	year, mon = int(match.group(1)), int(match.group(2))
	if not 1 <= mon <= 12:
		frappe.throw(_("Month must be written as YYYY-MM."), frappe.ValidationError)
	last = calendar.monthrange(year, mon)[1]
	return date(year, mon, 1), date(year, mon, last)


def _attendance_today_rows(employee=None, limit=TODAY_PUNCH_ROWS):
	"""Today's punches, so the report answers "who is in?" without a filter.

	Scoped to `employee` when the report is, so an employee's own card shows
	their own punches instead of the rest of the company's.  The window ends
	at tomorrow, not at now(): a punch logged a minute ahead by a device with
	a fast clock is still today's punch.
	"""
	if not frappe.has_permission(CHECKIN_DOCTYPE, "read", throw=False):
		return []
	fields = _existing_fields(CHECKIN_DOCTYPE, ["name", "employee", "log_type", "time", "late_minutes"])
	# two conditions, not ["between", ...]: between matches nothing on this field
	# here, which would leave the table permanently empty rather than wrong.
	filters = [["time", ">=", nowdate()], ["time", "<", add_days(nowdate(), 1)]]
	if employee:
		filters.append(["employee", "=", employee])
	rows = frappe.get_list(
		CHECKIN_DOCTYPE,
		filters=filters,
		fields=fields,
		order_by="time desc",
		limit_page_length=limit,
	)
	names = {}
	for row in rows:
		employee = row.get("employee")
		if employee and employee not in names:
			names[employee] = frappe.db.get_value("Employee", employee, "employee_name") or employee
	return [
		{
			"name": row.get("name"),
			"employee": row.get("employee"),
			"employee_name": names.get(row.get("employee")) or row.get("employee"),
			"log_type": row.get("log_type"),
			"time": _time_only(row.get("time")),
			"late_minutes": flt(row.get("late_minutes")) or None,
			"desk_url": desk_route(CHECKIN_DOCTYPE, row.get("name")),
		}
		for row in rows
	]


@frappe.whitelist(methods=["POST"])
def correct_attendance_day(attendance=None, employee=None, date=None, time=None, out_time=None, note=None):
	"""An admin corrects one attendance day's check-in and/or check-out.

	Any of ``time`` (the new check-in) and ``out_time`` (the new check-out) can
	be given on their own or together; a note on its own touches only the
	attendance row and needs no punch. The edits are written through a Saudi
	Punch Correction already in its approved state, so the audit trail
	(original vs applied times) and the once-per-day guard still hold. When the
	employee has no punch for the corrected side on the date, the correction
	registers one, so a forgotten check-in or check-out can be entered here.

	A day the report lists as ``missing`` has no attendance row, so it is
	addressed by ``employee`` and ``date`` instead of ``attendance``: a correction
	with a time on it registers the whole day (punch or punches plus the daily
	attendance row). A note alone still needs an existing row to attach to.

	The response is the corrected ``_attendance_view`` row so the page can
	swap it into the table in place of the stale one.
	"""
	assert_portal_access()
	assert_panel_access("attendance")
	attendance = cstr(attendance or "").strip()
	date_value = cstr(date or "").strip()

	doc = _attendance_doc_for(attendance, employee, date_value)
	if doc:
		if not frappe.has_permission(ATTENDANCE_DOCTYPE, "write", doc=doc):
			frappe.throw(
				_("You do not have permission to correct this attendance record.<br>"
				  "ليس لديك صلاحية لتصحيح سجل الحضور."),
				frappe.PermissionError,
			)
		if not doc.employee or not doc.attendance_date:
			frappe.throw(
				_("The attendance record has no employee or date.<br>"
				  "سجل الحضور بدون موظف أو تاريخ."),
				title=_("Incomplete Attendance / سجل حضور ناقص"),
			)
		employee = doc.employee
		date_value = str(doc.attendance_date)
	else:
		# registering a day the report lists as missing: no record exists, so the
		# day is addressed by employee and date, and the doctype-level write right
		# stands in for the document-level one there is no document for yet
		employee = cstr(employee or "").strip()
		if not employee or not date_value:
			frappe.throw(
				_("Attendance record is required.<br>سجل الحضور مطلوب."),
				title=_("Attendance Required / سجل الحضور مطلوب"),
			)
		if not frappe.has_permission(ATTENDANCE_DOCTYPE, "write", throw=False):
			frappe.throw(
				_("You do not have permission to correct this attendance record.<br>"
				  "ليس لديك صلاحية لتصحيح سجل الحضور."),
				frappe.PermissionError,
			)
		try:
			date_value = str(getdate(date_value))
		except ValueError:
			frappe.throw(
				_("Date must be written as YYYY-MM-DD.<br>التاريخ يجب أن يكون بالصيغة YYYY-MM-DD."),
				frappe.ValidationError,
			)
		if date_value > nowdate():
			frappe.throw(
				_("A day that is still in the future cannot be registered.<br>"
				  "لا يمكن تسجيل يوم في المستقبل."),
				frappe.ValidationError,
			)
		if not frappe.db.exists("Employee", employee):
			frappe.throw(
				_("The employee does not exist.<br>الموظف غير موجود."),
				frappe.ValidationError,
			)

	time = cstr(time or "").strip()
	out_time = cstr(out_time or "").strip()
	note = cstr(note or "").strip()
	if not time and not out_time and not note:
		frappe.throw(
			_("Choose the corrected check-in or check-out time, or add a note.<br>"
			  "حدد وقت الحضور أو الخروج الصحيح، أو أضف ملاحظة."),
			title=_("Nothing To Save / لا يوجد ما يتم حفظه"),
		)
	if not doc and not (time or out_time):
		frappe.throw(
			_("A note needs an attendance record to attach to.<br>"
			  "الملاحظة تحتاج إلى سجل حضور."),
			title=_("Nothing To Save / لا يوجد ما يتم حفظه"),
		)

	if time or out_time:
		# Frappe pre-fills every unsent Time field with "now", so even a day with
		# no punch on one side would otherwise look like it was corrected to
		# "now". The doctype ignores a corrected time that carries fractional
		# seconds, so the invented punch never sticks: only an explicit time is
		# applied. Frappe only lets a workflow document be *created* in its
		# first state, so the record is inserted as a Draft and then driven
		# straight through the same methods submit() would call: validate()
		# re-derives the punches and enforces the once-per-day guard, then
		# on_submit() applies the correction (creating the punch when the date
		# has none).
		#
		# A day that was already corrected is corrected again by updating the
		# same request, not by refusing: the once-per-day guard only blocks a
		# *second* request, and the original times this one captured stay the
		# audit trail. Re-applying it moves the punches to the new times.
		existing = frappe.db.get_value(
			PUNCH_CORRECTION_DOCTYPE,
			{"employee": employee, "attendance_date": date_value, "applied": 1, "docstatus": 1},
			"name",
		)
		if existing:
			correction = frappe.get_doc(PUNCH_CORRECTION_DOCTYPE, existing)
			if time:
				correction.corrected_in_time = time
			if out_time:
				correction.corrected_out_time = out_time
			if note:
				correction.correction_reason = note
			# un-apply so validate() runs the update path again; the originals
			# are already on the request and are left untouched
			correction.applied = 0
			correction.flags.ignore_permissions = True
			correction.flags.ignore_validate_update_after_submit = True
			correction.validate()
			frappe.db.set_value(
				PUNCH_CORRECTION_DOCTYPE,
				correction.name,
				{"workflow_state": "Completed", "docstatus": 1},
			)
		else:
			correction_fields = {
				"doctype": PUNCH_CORRECTION_DOCTYPE,
				"employee": employee,
				"attendance_date": date_value,
				"correction_reason": note
				or _("Corrected from the admin attendance panel / تصحيح من لوحة الحضور الإدارية"),
			}
			if time:
				correction_fields["corrected_in_time"] = time
			if out_time:
				correction_fields["corrected_out_time"] = out_time
			correction = frappe.get_doc(correction_fields)
			correction.flags.ignore_permissions = True
			correction.insert()
			correction.docstatus = 1
			correction.workflow_state = "Completed"
			try:
				correction.validate()
				correction.on_submit()
			except Exception:
				frappe.delete_doc(
					PUNCH_CORRECTION_DOCTYPE, correction.name, force=True, ignore_permissions=True
				)
				raise
			frappe.db.set_value(
				PUNCH_CORRECTION_DOCTYPE, correction.name, {"workflow_state": "Completed", "docstatus": 1}
			)

	if note:
		target = _attendance_doc_for("", employee, date_value)
		if target:
			frappe.db.set_value(ATTENDANCE_DOCTYPE, target.name, "note", note)

	updated = _attendance_doc_for("", employee, date_value)
	corrections = {}
	if time or out_time:
		corrections[date_value] = correction.correction_reason or None
	return _attendance_view(updated, corrections)


@frappe.whitelist(methods=["POST"])
def remove_attendance_day(attendance=None, employee=None, date=None):
	"""Remove a day's attendance entirely: its punches, any punch correction
	that produced them, and the daily attendance row itself, so the day reads
	as missing again.

	The punches go with the row, rather than being left for the next
	consolidation to rebuild the day from, because "remove" must mean the day
	is gone. A day addressed by ``employee`` and ``date`` works whether or not
	a row exists yet, so the same control serves both.
	"""
	assert_portal_access()
	assert_panel_access("attendance")
	attendance = cstr(attendance or "").strip()
	date_value = cstr(date or "").strip()

	doc = _attendance_doc_for(attendance, employee, date_value)
	if doc:
		if not frappe.has_permission(ATTENDANCE_DOCTYPE, "write", doc=doc):
			frappe.throw(
				_("You do not have permission to remove this attendance record.<br>"
				  "ليس لديك صلاحية لحذف سجل الحضور."),
				frappe.PermissionError,
			)
		employee = doc.employee
		date_value = str(doc.attendance_date)
	else:
		employee = cstr(employee or "").strip()
		if not employee or not date_value:
			frappe.throw(
				_("Attendance record is required.<br>سجل الحضور مطلوب."),
				title=_("Attendance Required / سجل الحضور مطلوب"),
			)
		if not frappe.has_permission(ATTENDANCE_DOCTYPE, "write", throw=False):
			frappe.throw(
				_("You do not have permission to remove this attendance record.<br>"
				  "ليس لديك صلاحية لحذف سجل الحضور."),
				frappe.PermissionError,
			)
		try:
			date_value = str(getdate(date_value))
		except ValueError:
			frappe.throw(
				_("Date must be written as YYYY-MM-DD.<br>التاريخ يجب أن يكون بالصيغة YYYY-MM-DD."),
				frappe.ValidationError,
			)

	# corrections first: cancel so the punches they moved go back, then drop the
	# request so nothing still points at the day that is about to disappear
	for name in frappe.get_all(
		PUNCH_CORRECTION_DOCTYPE,
		filters={"employee": employee, "attendance_date": date_value},
		pluck="name",
	):
		correction = frappe.get_doc(PUNCH_CORRECTION_DOCTYPE, name)
		correction.flags.ignore_permissions = True
		try:
			if correction.docstatus == 1:
				correction.cancel()
		except Exception:
			pass
		frappe.delete_doc(PUNCH_CORRECTION_DOCTYPE, name, force=True, ignore_permissions=True)

	# the punches themselves, so a later consolidation cannot rebuild the day
	for name in frappe.get_all(
		CHECKIN_DOCTYPE,
		filters={
			"employee": employee,
			"time": ["between", [f"{date_value} 00:00:00", f"{date_value} 23:59:59"]],
		},
		pluck="name",
	):
		frappe.delete_doc(CHECKIN_DOCTYPE, name, force=True, ignore_permissions=True)

	# the daily attendance row, cancelled first because it is submitted
	target = _attendance_doc_for("", employee, date_value)
	if target:
		target.flags.ignore_permissions = True
		if target.docstatus == 1:
			target.cancel()
		frappe.delete_doc(ATTENDANCE_DOCTYPE, target.name, force=True, ignore_permissions=True)

	return {"employee": employee, "date": date_value, "removed": True}


def _attendance_doc_for(attendance, employee, date_value):
	"""The day's Saudi Daily Attendance row, or None when it does not exist yet.

	Read by name when the caller has it, otherwise by employee and date, so the
	same lookup serves the day that already exists and the one the report says
	is missing.
	"""
	attendance = cstr(attendance or "").strip()
	if attendance:
		return frappe.get_doc(ATTENDANCE_DOCTYPE, attendance)
	if not employee or not date_value:
		return None
	name = frappe.db.get_value(
		ATTENDANCE_DOCTYPE,
		{"employee": cstr(employee).strip(), "attendance_date": cstr(date_value or "").strip()},
		"name",
		order_by="creation desc",
	)
	return frappe.get_doc(ATTENDANCE_DOCTYPE, name) if name else None


@frappe.whitelist(methods=["GET"])
def get_eosb_settlement(employee=None, termination_reason=None, termination_date=None, eosb_deductions=0):
	"""Calculate financial clearance / end of service settlement details for admin UI."""
	assert_portal_access()
	assert_panel_access("clearance")
	return _eosb_settlement_preview(employee, termination_reason, termination_date, eosb_deductions)


def _eosb_settlement_preview(employee=None, termination_reason=None, termination_date=None, eosb_deductions=0):
	if not employee:
		emp_list = frappe.get_list("Employee", filters={"status": "Active"}, pluck="name", limit_page_length=1)
		if emp_list:
			employee = emp_list[0]

	if not employee:
		return {"employee": None}

	if not frappe.has_permission("Employee", "read", doc=employee, throw=False):
		frappe.throw(_("You do not have access to this employee."), frappe.PermissionError)

	emp = frappe.get_doc("Employee", employee)
	joining_date = emp.date_of_joining or "2019-03-10"
	term_date = getdate(termination_date) if termination_date else getdate(nowdate())
	reason = termination_reason or "End of Fixed Term / انتهاء عقد محدد"
	deductions = flt(eosb_deductions)

	basic_salary = flt(get_employee_basic_salary(employee) or 9000.0)
	components = get_employee_salary_components(employee) or {}
	total_salary = flt(components.get("total_salary") or (basic_salary * 1.35))
	housing_allowance = flt(components.get("housing_allowance") or (basic_salary * 0.25))
	transport_allowance = flt(components.get("transport_allowance") or (basic_salary * 0.10))

	from saudi_hr.saudi_hr.utils import calculate_eosb_components
	eosb_res = calculate_eosb_components(joining_date, term_date, basic_salary, reason, deductions)

	d1 = getdate(joining_date)
	d2 = getdate(term_date)
	total_days = max(0, (d2 - d1).days)
	y = total_days // 365
	rem_days = total_days % 365
	m = rem_days // 30
	days = rem_days % 30
	service_period_str = f"{y} سنوات • {m} أشهر • {days} يوم"

	leave_balance = 18.0
	daily_rate = total_salary / 30.0 if total_salary else (basic_salary / 30.0)
	leave_payout = round(leave_balance * daily_rate, 2)
	net_eosb_amount = flt(eosb_res.get("net_eosb", 0))

	earnings = [
		{"item": f"الراتب الأساسي — {term_date.strftime('%B %Y')}", "amount": basic_salary},
		{"item": "بدل سكن", "amount": housing_allowance},
		{"item": "بدل نقل", "amount": transport_allowance},
		{"item": f"تعويض رصيد الإجازات ({int(leave_balance)} يوم × {round(daily_rate, 2):,.2f})", "amount": leave_payout},
		{"item": "مكافأة نهاية الخدمة (م.84)", "amount": net_eosb_amount},
	]
	total_earnings = sum(e["amount"] for e in earnings)

	gosi_deduction = round((basic_salary + housing_allowance) * 0.0975, 2)
	deduction_items = [
		{"item": "سلفة متبقية", "amount": deductions},
		{"item": "التأمينات الاجتماعية (9.75% من الأساسي + السكن)", "amount": gosi_deduction},
		{"item": "غياب / تأخير من سجل الحضور", "amount": 0.0},
		{"item": "عهد غير مسلمة", "amount": 0.0},
	]
	total_deductions = sum(d["amount"] for d in deduction_items)
	net_settlement = round(total_earnings - total_deductions, 2)

	try:
		from frappe.utils import money_in_words
		words_ar = money_in_words(net_settlement, "SAR")
	except Exception:
		words_ar = f"{net_settlement:,.2f} ريال سعودي"

	existing_name = frappe.db.get_value("End of Service Benefit", {"employee": employee}, "name")

	return {
		"employee": {
			"name": emp.name,
			"employee_number": emp.employee_number or emp.name,
			"employee_name": emp.employee_name or emp.first_name,
			"designation": emp.designation or "—",
			"department": emp.department or "—",
			"company": emp.company or "—",
			"joining_date": str(joining_date),
			"termination_date": str(term_date),
			"basic_salary": basic_salary,
			"total_salary": total_salary,
			"leave_balance": leave_balance,
		},
		"service_period_str": service_period_str,
		"service_years": eosb_res.get("years_of_service", 0),
		"earnings": earnings,
		"total_earnings": round(total_earnings, 2),
		"deductions": deduction_items,
		"total_deductions": round(total_deductions, 2),
		"net_settlement": net_settlement,
		"words_ar": words_ar,
		"existing_name": existing_name,
		"ref_no": f"CL-{term_date.year}-" + (existing_name or "0147")[-4:],
		"issue_date": nowdate(),
		"status_label": "بانتظار الاعتماد" if not existing_name else "مختومة ومعتمدة",
	}


@frappe.whitelist(methods=["POST"])
def create_eosb_settlement(employee, termination_date, termination_reason, last_basic_salary, eosb_deductions=0, notes=None):
	"""Create or submit End of Service Benefit record."""
	assert_portal_access()
	assert_panel_access("clearance")
	if not frappe.db.table_exists("End of Service Benefit"):
		frappe.throw(_("End of Service Benefit doctype does not exist."), frappe.ValidationError)
	assert_doctype_permissions("End of Service Benefit", "create")

	emp = cstr(employee).strip()
	doc = frappe.get_doc({
		"doctype": "End of Service Benefit",
		"employee": emp,
		"termination_date": termination_date,
		"termination_reason": termination_reason or "End of Fixed Term / انتهاء عقد محدد",
		"last_basic_salary": flt(last_basic_salary),
		"eosb_deductions": flt(eosb_deductions),
		"calculation_notes": cstr(notes or ""),
	})
	doc.insert()
	if cstr(notes or "").strip():
		# The doctype's validate() rebuilds calculation_notes from the EOSB
		# breakdown, so the caller's note would be discarded unless kept here.
		frappe.db.set_value(
			"End of Service Benefit",
			doc.name,
			"calculation_notes",
			f"{doc.calculation_notes}\n{notes}" if doc.calculation_notes else notes,
		)
	return {
		"name": doc.name,
		"created": True,
		"desk_url": desk_route("End of Service Benefit", doc.name),
	}


@frappe.whitelist(methods=["GET"])
def get_documents_and_letters(employee=None, document_type=None, status=None, limit=50):
	"""Fetch documents & letters dashboard metrics and request history."""
	assert_portal_access()
	assert_panel_access("documents")
	limit = _clean_limit(limit)

	filters = {}
	if employee:
		filters["employee"] = employee
	if document_type:
		filters["request_type"] = document_type

	rows = []
	if frappe.db.table_exists("HR Service Request") and frappe.has_permission("HR Service Request", "read", throw=False):
		fields = _existing_fields("HR Service Request", ["name", "employee", "employee_name", "request_type", "creation", "workflow_state", "status", "docstatus", "description"])
		sr_rows = frappe.get_list("HR Service Request", filters=filters, fields=fields, order_by="creation desc", limit_page_length=limit)
		for r in sr_rows:
			state = _row_state(r)
			if status and state != status:
				continue
			rows.append({
				"name": r.get("name"),
				"employee": r.get("employee"),
				"employee_name": r.get("employee_name") or r.get("employee"),
				"document_type": r.get("request_type") or "salary_certificate",
				"addressed_to": r.get("description") or "—",
				"creation": str(r.get("creation"))[:10] if r.get("creation") else "",
				"state": state,
				"raw_state": r.get("workflow_state") or r.get("status"),
				"desk_url": desk_route("HR Service Request", r.get("name")),
			})

	stats = {
		"pending": sum(1 for r in rows if r["state"] in ("pending", "draft")),
		"in_progress": sum(1 for r in rows if r["state"] in ("pending", "draft")),
		"issued_month": sum(1 for r in rows if r["state"] == "approved"),
		"rejected": sum(1 for r in rows if r["state"] == "rejected"),
		"total": len(rows),
	}

	return {
		"stats": stats,
		"rows": rows,
	}


@frappe.whitelist(methods=["POST"])
def issue_hr_document(employee, document_type, addressed_to=None, notes=None):
	"""Issue or request a new HR document/letter."""
	assert_portal_access()
	assert_panel_access("documents")
	if not frappe.db.table_exists("HR Service Request"):
		frappe.throw(_("HR Service Request doctype is missing."), frappe.ValidationError)
	assert_doctype_permissions("HR Service Request", "create")

	AUTO_ISSUE_TYPES = {"salary_certificate", "job_confirmation", "contract_copy", "payslip", "salary_benefits_statement"}

	doc = frappe.get_doc({
		"doctype": "HR Service Request",
		"employee": employee,
		"request_type": document_type,
		"description": cstr(addressed_to or notes or ""),
	})
	doc.insert()

	if document_type in AUTO_ISSUE_TYPES:
		# auto-issued documents skip the approval chain.  Stepping the state via
		# the business object would make validate_workflow refuse "Draft ->
		# Approved" (no such transition exists), so the value is written straight
		# to the row, the same way the doctype's own workflow_state Select treats
		# "Approved" as a settled outcome.  The in-memory doc is nudged too so the
		# returned state matches what a re-read of the row reports.
		frappe.db.set_value("HR Service Request", doc.name, "workflow_state", "Approved")
		doc.workflow_state = "Approved"

	return {
		"name": doc.name,
		"created": True,
		"document_type": document_type,
		"state": _row_state(doc.as_dict()),
		"desk_url": desk_route("HR Service Request", doc.name),
	}


# ─── Offboarding / Exit Clearance orchestrator ──────────────────────────────
#
# One case drives the whole exit.  The desk doctypes keep their own controllers
# and approvals; this layer only starts them, links them together and lets HR
# approve the Termination Notice from the same panel.  Every write is guarded
# by the caller's own doctype permissions, and every action name is re-derived
# from the workflow rather than trusted from the client.

EXIT_CLEARANCE_CHECKLIST_FIELDS = (
	"access_revoked",
	"assets_returned",
	"final_attendance_verified",
	"payroll_closed",
	"eosb_completed",
	"annual_leave_disbursement_completed",
	"exit_interview_completed",
	"handover_completed",
)

EXIT_CLEARANCE_STATUSES = (
	"Draft / مسودة",
	"In Progress / قيد التنفيذ",
	"Cleared / مخلى طرفه",
	"On Hold / موقوف",
)

# Doctypes whose workflow this panel is allowed to advance.  Anything outside
# this set is refused even if the caller could normally apply the workflow.
OFFBOARDING_ACTION_DOCTYPES = ("Termination Notice",)

# Termination Notice and End of Service Benefit keep separate reason lists; map
# the notice's finer-grained reason onto the settlement's coarser one.
EOSB_REASON_BY_TERMINATION_REASON = {
	"Resignation by Employee / استقالة الموظف (م.75)": "Resignation / استقالة",
	"Termination by Employer / إنهاء من صاحب العمل (م.76)": "Termination by Employer / إنهاء من صاحب العمل",
	"End of Fixed Term / انتهاء عقد محدد المدة": "End of Fixed Term / انتهاء عقد محدد",
	"Mutual Agreement / اتفاق مشترك": "Resignation / استقالة",
	"Dismissal Without Notice / فصل فوري (م.80)": "Dismissal / فصل تأديبي (م.80)",
}
DEFAULT_EOSB_TERMINATION_REASON = "Termination by Employer / إنهاء من صاحب العمل"


def _as_dict(value):
	"""Accept a dict or a JSON string, since nested POST args arrive encoded."""
	if isinstance(value, dict):
		return value
	if isinstance(value, str) and value.strip():
		try:
			parsed = json.loads(value)
		except (ValueError, TypeError):
			return {}
		return parsed if isinstance(parsed, dict) else {}
	return {}


def _clearance_state(status):
	value = cstr(status or "").lower()
	if "cleared" in value or "مخلى" in value:
		return "approved"
	if "hold" in value or "موقوف" in value:
		return "other"
	if "progress" in value or "تنفيذ" in value:
		return "pending"
	return "draft"


def _employee_company(employee):
	return cstr(frappe.db.get_value("Employee", employee, "company") or "").strip()


def _eosb_reason_for(termination_notice):
	if termination_notice and frappe.db.exists("Termination Notice", termination_notice):
		reason = frappe.db.get_value("Termination Notice", termination_notice, "termination_reason")
		return EOSB_REASON_BY_TERMINATION_REASON.get(reason, DEFAULT_EOSB_TERMINATION_REASON)
	return DEFAULT_EOSB_TERMINATION_REASON


def _linked_summary(doctype, name, fields):
	if not name or not frappe.db.exists(doctype, name):
		return None
	present = _existing_fields(doctype, fields)
	values = frappe.db.get_value(doctype, name, present, as_dict=True) or {}
	dates = {key: value for key, value in values.items() if hasattr(value, "isoformat")}
	for key, value in dates.items():
		values[key] = str(value)
	values["name"] = name
	values["desk_url"] = desk_route(doctype, name)
	return values


def _link_final_settlement(termination_notice=None, exit_clearance=None, eosb_document=None):
	if not termination_notice:
		return
	name = frappe.db.get_value("Final Settlement SLA", {"termination_notice": termination_notice}, "name")
	if not name:
		return
	updates = {}
	if exit_clearance:
		updates["exit_clearance"] = exit_clearance
	if eosb_document:
		updates["eosb_document"] = eosb_document
	for fieldname, value in updates.items():
		frappe.db.set_value("Final Settlement SLA", name, fieldname, value, update_modified=False)


def _update_clearance_checklist(clearance_name, values):
	if not clearance_name or not frappe.db.exists("Exit Clearance", clearance_name):
		return
	doc = frappe.get_doc("Exit Clearance", clearance_name)
	changed = False
	for fieldname in EXIT_CLEARANCE_CHECKLIST_FIELDS:
		if fieldname in values and cint(doc.get(fieldname)) != cint(values[fieldname]):
			doc.set(fieldname, cint(values[fieldname]))
			changed = True
	if changed:
		doc.save(ignore_permissions=False)


@frappe.whitelist(methods=["GET"])
def get_offboarding_form_options():
	"""Select options for the offboarding start form, read live from meta."""
	assert_portal_access()
	assert_panel_access("clearance")

	def _options(doctype, fieldname):
		meta = frappe.get_meta(doctype)
		field = meta.get_field(fieldname)
		return [line for line in cstr(field.options if field else "").split("\n") if line]

	return {
		"termination_reasons": _options("Termination Notice", "termination_reason"),
		"salary_payment_types": _options("Termination Notice", "salary_payment_type"),
		"clearance_statuses": list(EXIT_CLEARANCE_STATUSES),
	}


@frappe.whitelist(methods=["GET"])
def list_exit_clearances(employee=None, status=None, limit=50):
	"""Exit clearance cases the caller may read, newest first."""
	assert_portal_access()
	assert_panel_access("clearance")
	if not frappe.db.table_exists("Exit Clearance"):
		return {"rows": [], "statuses": list(EXIT_CLEARANCE_STATUSES)}
	if not frappe.has_permission("Exit Clearance", "read", throw=False):
		return {"rows": [], "statuses": list(EXIT_CLEARANCE_STATUSES)}

	limit = _clean_limit(limit)
	filters = {}
	if employee:
		filters["employee"] = cstr(employee).strip()
	if status:
		filters["status"] = cstr(status).strip()

	fields = _existing_fields(
		"Exit Clearance",
		[
			"name",
			"employee",
			"employee_name",
			"department",
			"last_working_day",
			"status",
			"clearance_percentage",
			"termination_notice",
			"end_of_service_benefit",
		],
	)
	rows = frappe.get_list(
		"Exit Clearance",
		filters=filters,
		fields=fields,
		order_by="modified desc",
		limit_page_length=limit,
	)
	out = []
	for row in rows:
		out.append(
			{
				"name": row.get("name"),
				"employee": row.get("employee"),
				"employee_name": row.get("employee_name") or row.get("employee"),
				"department": row.get("department") or "",
				"last_working_day": str(row.get("last_working_day")) if row.get("last_working_day") else "",
				"status": row.get("status") or EXIT_CLEARANCE_STATUSES[0],
				"state": _clearance_state(row.get("status")),
				"clearance_percentage": flt(row.get("clearance_percentage")),
				"termination_notice": row.get("termination_notice"),
				"has_eosb": bool(row.get("end_of_service_benefit")),
				"desk_url": desk_route("Exit Clearance", row.get("name")),
			}
		)
	return {"rows": out, "statuses": list(EXIT_CLEARANCE_STATUSES)}


def _termination_notice_summary(name):
	if not name or not frappe.db.exists("Termination Notice", name):
		return None
	doc = frappe.get_doc("Termination Notice", name)
	transitions = []
	for transition in get_transitions(doc, raise_exception=False):
		if has_approval_access(frappe.session.user, doc, transition):
			transitions.append({"action": transition.get("action"), "next_state": transition.get("next_state")})
	return {
		"name": doc.name,
		"state": _row_state(doc.as_dict()),
		"raw_state": doc.get("workflow_state") or doc.get("status"),
		"docstatus": cint(doc.docstatus),
		"termination_reason": doc.termination_reason,
		"salary_payment_type": doc.salary_payment_type,
		"notice_start_date": str(doc.notice_start_date) if doc.notice_start_date else "",
		"notice_end_date": str(doc.notice_end_date) if doc.notice_end_date else "",
		"transitions": transitions,
		"desk_url": desk_route("Termination Notice", doc.name),
	}


def _final_settlement_summary(termination_notice, exit_clearance):
	filters = {}
	if termination_notice:
		filters["termination_notice"] = termination_notice
	elif exit_clearance:
		filters["exit_clearance"] = exit_clearance
	else:
		return None
	name = frappe.db.get_value("Final Settlement SLA", filters, "name")
	return _linked_summary(
		"Final Settlement SLA",
		name,
		[
			"name",
			"status",
			"settlement_due_date",
			"last_working_day",
			"payment_status",
			"risk_level",
			"termination_initiated_by",
		],
	)


@frappe.whitelist(methods=["GET"])
def get_offboarding_case(name):
	"""Full picture of one exit case: notice, SLA, settlement, checks, interviews."""
	assert_portal_access()
	assert_panel_access("clearance")
	clearance_name = cstr(name or "").strip()
	if not clearance_name or not frappe.db.exists("Exit Clearance", clearance_name):
		frappe.throw(_("Exit clearance not found."), frappe.DoesNotExistError)
	if not frappe.has_permission("Exit Clearance", "read", doc=clearance_name, throw=False):
		frappe.throw(_("You do not have access to this case."), frappe.PermissionError)

	doc = frappe.get_doc("Exit Clearance", clearance_name)
	case = {
		"name": doc.name,
		"employee": doc.employee,
		"employee_name": doc.employee_name or doc.employee,
		"company": doc.company,
		"department": doc.department,
		"last_working_day": str(doc.last_working_day) if doc.last_working_day else "",
		"status": doc.status,
		"state": _clearance_state(doc.status),
		"clearance_percentage": flt(doc.clearance_percentage),
		"notes": doc.notes or "",
		"termination_notice": doc.termination_notice,
		"end_of_service_benefit": doc.end_of_service_benefit,
		"annual_leave_disbursement": doc.annual_leave_disbursement,
		"exit_interview": doc.exit_interview,
		"checklist": {fieldname: cint(doc.get(fieldname)) for fieldname in EXIT_CLEARANCE_CHECKLIST_FIELDS},
		"desk_url": desk_route("Exit Clearance", doc.name),
	}
	case["eosb_preview"] = _eosb_settlement_preview(
		employee=doc.employee,
		termination_reason=_eosb_reason_for(doc.termination_notice),
		termination_date=doc.last_working_day,
	)
	case["termination_notice_doc"] = _termination_notice_summary(doc.termination_notice)
	case["final_settlement"] = _final_settlement_summary(doc.termination_notice, doc.name)
	case["end_of_service_benefit_doc"] = _linked_summary(
		"End of Service Benefit",
		doc.end_of_service_benefit,
		[
			"name",
			"employee",
			"net_eosb",
			"docstatus",
			"termination_date",
			"last_basic_salary",
			"payment_status",
		],
	)
	if case["end_of_service_benefit_doc"]:
		case["end_of_service_benefit_doc"]["state"] = (
			"approved" if cint(case["end_of_service_benefit_doc"].get("docstatus")) == 1 else "draft"
		)
	case["exit_interview_doc"] = _linked_summary(
		"Exit Interview",
		doc.exit_interview,
		["name", "interview_date", "status", "interview_mode", "conducted_by"],
	)
	case["leave_disbursement_doc"] = _linked_summary(
		"Annual Leave Disbursement",
		doc.annual_leave_disbursement,
		["name", "leave_year", "leave_days_to_pay", "status", "docstatus", "total_leave_pay"],
	)
	return case


@frappe.whitelist(methods=["POST"])
def create_termination_notice(
	employee,
	termination_reason,
	salary_payment_type,
	notice_start_date,
	during_probation=0,
	notes=None,
):
	"""Start an exit: HR records the termination notice for the employee."""
	assert_portal_access()
	assert_panel_access("clearance")
	if not frappe.db.table_exists("Termination Notice"):
		frappe.throw(_("Termination Notice doctype does not exist."), frappe.ValidationError)
	assert_doctype_permissions("Termination Notice", "create")

	emp = cstr(employee or "").strip()
	if not emp or not frappe.db.exists("Employee", emp):
		frappe.throw(_("Employee not found."), frappe.DoesNotExistError)

	doc = frappe.get_doc(
		{
			"doctype": "Termination Notice",
			"employee": emp,
			"company": _employee_company(emp),
			"termination_reason": termination_reason,
			"salary_payment_type": salary_payment_type,
			"notice_start_date": getdate(notice_start_date),
			"during_probation": cint(during_probation),
			"termination_notes": cstr(notes or ""),
		}
	)
	doc.insert()
	return {
		"name": doc.name,
		"created": True,
		"employee": emp,
		"state": _row_state(doc.as_dict()),
		"raw_state": doc.get("workflow_state") or doc.get("status"),
		"desk_url": desk_route("Termination Notice", doc.name),
	}


@frappe.whitelist(methods=["POST"])
def create_exit_clearance(employee, termination_notice=None, last_working_day=None):
	"""Create (or return) the exit clearance for an employee and wire up links."""
	assert_portal_access()
	assert_panel_access("clearance")
	if not frappe.db.table_exists("Exit Clearance"):
		frappe.throw(_("Exit Clearance doctype does not exist."), frappe.ValidationError)
	assert_doctype_permissions("Exit Clearance", "create")

	emp = cstr(employee or "").strip()
	if not emp or not frappe.db.exists("Employee", emp):
		frappe.throw(_("Employee not found."), frappe.DoesNotExistError)

	notice = cstr(termination_notice or "").strip()
	if notice:
		existing = frappe.db.get_value("Exit Clearance", {"termination_notice": notice}, "name")
		if existing:
			return {
				"name": existing,
				"created": False,
				"state": _clearance_state(frappe.db.get_value("Exit Clearance", existing, "status")),
				"desk_url": desk_route("Exit Clearance", existing),
			}

	last_day = last_working_day
	if notice and not last_day and frappe.db.exists("Termination Notice", notice):
		last_day = frappe.db.get_value("Termination Notice", notice, "notice_end_date")

	doc = frappe.get_doc(
		{
			"doctype": "Exit Clearance",
			"employee": emp,
			"company": _employee_company(emp),
			"termination_notice": notice or None,
			"last_working_day": getdate(last_day) if last_day else None,
		}
	)
	doc.insert()
	_link_final_settlement(termination_notice=notice, exit_clearance=doc.name)
	return {
		"name": doc.name,
		"created": True,
		"employee": emp,
		"state": _clearance_state(doc.status),
		"desk_url": desk_route("Exit Clearance", doc.name),
	}


@frappe.whitelist(methods=["POST"])
def apply_offboarding_action(doctype, name, action):
	"""Advance a Termination Notice workflow transition on HR's behalf."""
	assert_portal_access()
	assert_panel_access("clearance")
	off_doctype = cstr(doctype or "").strip()
	if off_doctype not in OFFBOARDING_ACTION_DOCTYPES:
		frappe.throw(_("Unsupported offboarding document type."), frappe.ValidationError)
	if not frappe.db.exists(off_doctype, cstr(name or "").strip()):
		frappe.throw(_("Request not found."), frappe.DoesNotExistError)

	doc = frappe.get_doc(off_doctype, cstr(name).strip())
	requested = cstr(action or "").strip()
	if not requested:
		frappe.throw(_("An action is required."), frappe.ValidationError)

	permitted = get_transitions(doc, raise_exception=False)
	match = next((transition for transition in permitted if transition.get("action") == requested), None)
	if not match:
		frappe.throw(
			_("You are not allowed to perform '{0}' on this request.").format(frappe.bold(requested)),
			frappe.PermissionError,
		)
	if not has_approval_access(frappe.session.user, doc, match):
		frappe.throw(
			_("You cannot approve a request you created yourself."),
			frappe.PermissionError,
		)

	apply_workflow(doc, requested)
	return {
		"doctype": off_doctype,
		"name": doc.name,
		"action": requested,
		"state": _row_state(doc.as_dict()),
		"raw_state": doc.get("workflow_state") or doc.get("status"),
		"next_state": match.get("next_state"),
		"desk_url": desk_route(off_doctype, doc.name),
	}


@frappe.whitelist(methods=["POST"])
def save_exit_clearance(name, checklist=None, notes=None):
	"""Save the clearance checklist; the controller recomputes percent and status."""
	assert_portal_access()
	assert_panel_access("clearance")
	clearance_name = cstr(name or "").strip()
	if not clearance_name or not frappe.db.exists("Exit Clearance", clearance_name):
		frappe.throw(_("Exit clearance not found."), frappe.DoesNotExistError)

	doc = frappe.get_doc("Exit Clearance", clearance_name)
	assert_doctype_permissions("Exit Clearance", "write", doc=doc)

	values = _as_dict(checklist)
	for fieldname in EXIT_CLEARANCE_CHECKLIST_FIELDS:
		if fieldname in values:
			doc.set(fieldname, cint(values[fieldname]))
	if notes is not None:
		doc.set("notes", cstr(notes))
	doc.save()

	return {
		"name": doc.name,
		"status": doc.status,
		"state": _clearance_state(doc.status),
		"clearance_percentage": flt(doc.clearance_percentage),
		"checklist": {fieldname: cint(doc.get(fieldname)) for fieldname in EXIT_CLEARANCE_CHECKLIST_FIELDS},
		"desk_url": desk_route("Exit Clearance", doc.name),
	}


@frappe.whitelist(methods=["POST"])
def create_eosb_from_case(exit_clearance, last_basic_salary=None, eosb_deductions=0):
	"""Create the end of service settlement for a case and link it both ways."""
	assert_portal_access()
	assert_panel_access("clearance")
	if not frappe.db.table_exists("End of Service Benefit"):
		frappe.throw(_("End of Service Benefit doctype does not exist."), frappe.ValidationError)
	clearance_name = cstr(exit_clearance or "").strip()
	if not frappe.db.exists("Exit Clearance", clearance_name):
		frappe.throw(_("Exit clearance not found."), frappe.DoesNotExistError)
	assert_doctype_permissions("End of Service Benefit", "create")

	clearance = frappe.get_doc("Exit Clearance", clearance_name)
	if clearance.end_of_service_benefit and frappe.db.exists(
		"End of Service Benefit", clearance.end_of_service_benefit
	):
		return {
			"name": clearance.end_of_service_benefit,
			"created": False,
			"desk_url": desk_route("End of Service Benefit", clearance.end_of_service_benefit),
		}

	termination_date = clearance.last_working_day
	if clearance.termination_notice and frappe.db.exists("Termination Notice", clearance.termination_notice):
		termination_date = termination_date or frappe.db.get_value(
			"Termination Notice", clearance.termination_notice, "notice_end_date"
		)
	if not termination_date:
		termination_date = nowdate()

	basic = flt(last_basic_salary or get_employee_basic_salary(clearance.employee) or 0)
	eosb = frappe.get_doc(
		{
			"doctype": "End of Service Benefit",
			"employee": clearance.employee,
			"company": clearance.company or _employee_company(clearance.employee),
			"termination_date": getdate(termination_date),
			"termination_reason": _eosb_reason_for(clearance.termination_notice),
			"last_basic_salary": basic,
			"eosb_deductions": flt(eosb_deductions),
		}
	)
	eosb.insert()
	frappe.db.set_value("Exit Clearance", clearance.name, "end_of_service_benefit", eosb.name)
	_link_final_settlement(
		termination_notice=clearance.termination_notice,
		exit_clearance=clearance.name,
		eosb_document=eosb.name,
	)
	return {
		"name": eosb.name,
		"created": True,
		"employee": clearance.employee,
		"net_eosb": flt(eosb.net_eosb),
		"desk_url": desk_route("End of Service Benefit", eosb.name),
	}


@frappe.whitelist(methods=["POST"])
def submit_eosb(name):
	"""Submit the settlement and tick the linked clearance's EOSB box."""
	assert_portal_access()
	assert_panel_access("clearance")
	eosb_name = cstr(name or "").strip()
	if not eosb_name or not frappe.db.exists("End of Service Benefit", eosb_name):
		frappe.throw(_("End of Service Benefit not found."), frappe.DoesNotExistError)

	eosb = frappe.get_doc("End of Service Benefit", eosb_name)
	if cint(eosb.docstatus) == 1:
		frappe.throw(_("This settlement has already been submitted."), frappe.ValidationError)
	assert_doctype_permissions("End of Service Benefit", "submit", doc=eosb)
	eosb.submit()

	clearance = frappe.db.get_value("Exit Clearance", {"end_of_service_benefit": eosb.name}, "name")
	_update_clearance_checklist(clearance, {"eosb_completed": 1})

	return {
		"name": eosb.name,
		"state": "approved",
		"docstatus": cint(eosb.docstatus),
		"employee_status": frappe.db.get_value("Employee", eosb.employee, "status"),
		"desk_url": desk_route("End of Service Benefit", eosb.name),
	}


@frappe.whitelist(methods=["POST"])
def create_exit_interview(exit_clearance, interview_date=None, interviewer=None, interview_mode=None):
	"""Schedule the exit interview for a case and link it back."""
	assert_portal_access()
	assert_panel_access("clearance")
	clearance_name = cstr(exit_clearance or "").strip()
	if not frappe.db.exists("Exit Clearance", clearance_name):
		frappe.throw(_("Exit clearance not found."), frappe.DoesNotExistError)
	assert_doctype_permissions("Exit Interview", "create")

	clearance = frappe.get_doc("Exit Clearance", clearance_name)
	if clearance.exit_interview and frappe.db.exists("Exit Interview", clearance.exit_interview):
		return {
			"name": clearance.exit_interview,
			"created": False,
			"desk_url": desk_route("Exit Interview", clearance.exit_interview),
		}

	payload = {
		"doctype": "Exit Interview",
		"employee": clearance.employee,
		"company": clearance.company or _employee_company(clearance.employee),
		"exit_clearance": clearance.name,
		"interview_date": getdate(interview_date) if interview_date else getdate(nowdate()),
	}
	if clearance.termination_notice:
		payload["termination_notice"] = clearance.termination_notice
	if interviewer:
		payload["conducted_by"] = interviewer
	if interview_mode:
		payload["interview_mode"] = interview_mode

	interview = frappe.get_doc(payload)
	interview.insert()
	frappe.db.set_value("Exit Clearance", clearance.name, "exit_interview", interview.name)
	return {
		"name": interview.name,
		"created": True,
		"desk_url": desk_route("Exit Interview", interview.name),
	}


@frappe.whitelist(methods=["POST"])
def create_leave_disbursement(
	exit_clearance,
	leave_year=None,
	leave_from_date=None,
	leave_to_date=None,
	leave_days_to_pay=0,
	disbursement_type=None,
):
	"""Create the annual leave disbursement for a case and link it back."""
	assert_portal_access()
	assert_panel_access("clearance")
	if not frappe.db.table_exists("Annual Leave Disbursement"):
		frappe.throw(_("Annual Leave Disbursement doctype does not exist."), frappe.ValidationError)
	clearance_name = cstr(exit_clearance or "").strip()
	if not frappe.db.exists("Exit Clearance", clearance_name):
		frappe.throw(_("Exit clearance not found."), frappe.DoesNotExistError)
	assert_doctype_permissions("Annual Leave Disbursement", "create")

	clearance = frappe.get_doc("Exit Clearance", clearance_name)
	if clearance.annual_leave_disbursement and frappe.db.exists(
		"Annual Leave Disbursement", clearance.annual_leave_disbursement
	):
		return {
			"name": clearance.annual_leave_disbursement,
			"created": False,
			"desk_url": desk_route("Annual Leave Disbursement", clearance.annual_leave_disbursement),
		}

	last_day = getdate(clearance.last_working_day) if clearance.last_working_day else getdate(nowdate())
	year = cint(leave_year or last_day.year)
	doc = frappe.get_doc(
		{
			"doctype": "Annual Leave Disbursement",
			"employee": clearance.employee,
			"leave_year": year,
			"leave_from_date": getdate(leave_from_date) if leave_from_date else date(year, 1, 1),
			"leave_to_date": getdate(leave_to_date) if leave_to_date else last_day,
			"leave_days_to_pay": flt(leave_days_to_pay),
			"disbursement_type": disbursement_type or "Basic Salary Only / الراتب الأساسي فقط",
		}
	)
	doc.insert()
	frappe.db.set_value("Exit Clearance", clearance.name, "annual_leave_disbursement", doc.name)
	_update_clearance_checklist(clearance.name, {"annual_leave_disbursement_completed": 1})
	return {
		"name": doc.name,
		"created": True,
		"leave_year": year,
		"desk_url": desk_route("Annual Leave Disbursement", doc.name),
	}


@frappe.whitelist(methods=["POST"])
def settle_final_settlement(name=None, exit_clearance=None):
	"""Close out the final settlement SLA for a case."""
	assert_portal_access()
	assert_panel_access("clearance")
	sla_name = cstr(name or "").strip()
	if not sla_name and exit_clearance:
		sla_name = (
			frappe.db.get_value(
				"Final Settlement SLA", {"exit_clearance": cstr(exit_clearance).strip()}, "name"
			)
			or ""
		)
	if not sla_name or not frappe.db.exists("Final Settlement SLA", sla_name):
		frappe.throw(_("Final settlement record not found."), frappe.DoesNotExistError)

	sla = frappe.get_doc("Final Settlement SLA", sla_name)
	assert_doctype_permissions("Final Settlement SLA", "write", doc=sla)
	sla.status = "Settled / تمت التسوية"
	sla.payment_status = "Paid / مدفوع"
	sla.settlement_paid_on = getdate(nowdate())
	sla.save()
	return {
		"name": sla.name,
		"status": sla.status,
		"payment_status": sla.payment_status,
		"desk_url": desk_route("Final Settlement SLA", sla.name),
	}

