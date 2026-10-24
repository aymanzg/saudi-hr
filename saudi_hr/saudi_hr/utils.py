"""
utils.py — Helper functions for Saudi HR calculations.
"""
import re

import frappe
from frappe import _
from frappe.utils import add_days, add_months, add_years, cint, cstr, date_diff, flt, get_last_day, getdate, nowdate, today


def has_admin_portal_role(user=None):
	"""Return True if the user can access the Saudi HR admin portal."""
	user = user or getattr(frappe.session, "user", None)
	if not user or user == "Guest":
		return False
	if user == "Administrator":
		return True
	try:
		from saudi_hr.saudi_hr.admin_api import ADMIN_PORTAL_ROLES

		return bool(ADMIN_PORTAL_ROLES.intersection(frappe.get_roles(user)))
	except Exception:
		roles = set(frappe.get_roles(user))
		return bool(
			roles.intersection(
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
		)


LEAVE_SCOPE_EMPLOYEE = "Employee / موظف"
LEAVE_SCOPE_DEPARTMENT = "Department / قسم"
LEAVE_SOURCE_SETTINGS = "Saudi HR Settings / إعدادات الموارد البشرية"
STATUTORY_ANNUAL_THRESHOLD_YEARS = 5
STATUTORY_ANNUAL_BEFORE_DAYS = 21
STATUTORY_ANNUAL_AFTER_DAYS = 30
MONTHLY_ACCRUAL_BEFORE_THRESHOLD = STATUTORY_ANNUAL_BEFORE_DAYS / 12
MONTHLY_ACCRUAL_AFTER_THRESHOLD = STATUTORY_ANNUAL_AFTER_DAYS / 12
STATUTORY_SICK_FULL_PAY_DAYS = 30
STATUTORY_SICK_PAID_TIER_DAYS = 90
STATUTORY_SICK_PARTIAL_PAY_PERCENTAGE = 75
STATUTORY_SICK_MAX_DAYS = 120


def assert_doctype_permissions(doctype: str, permission_types, doc=None):
	if isinstance(permission_types, str):
		permission_types = (permission_types,)

	for permission_type in permission_types:
		frappe.has_permission(doctype, permission_type, doc=doc, throw=True)


def text_matches_tokens(value, *tokens: str) -> bool:
	normalized = cstr(value or "").strip().lower()
	if not normalized:
		return False
	return any(cstr(token).strip().lower() in normalized for token in tokens if cstr(token).strip())


def assert_positive_basic_salary(employee_label: str, basic_salary: float, context_label: str):
	if flt(basic_salary) > 0:
		return
	frappe.throw(
		_(
			"Basic salary for {0} must be greater than zero before {1}.<br>"
			"يجب أن يكون الراتب الأساسي للموظف {0} أكبر من صفر قبل {1}."
		).format(employee_label, context_label),
		title=_("Missing Basic Salary / راتب أساسي غير متوفر"),
	)


def get_overlap_days(start_date, end_date, range_start, range_end) -> int:
	period_start = max(getdate(start_date), getdate(range_start))
	period_end = min(getdate(end_date), getdate(range_end))
	if period_end < period_start:
		return 0
	return date_diff(period_end, period_start) + 1


def calculate_prorated_sick_leave_deduction(leave_rows: list, month_start, month_end, fallback_daily_salary: float = 0.0) -> float:
	deduction = 0.0
	for row in leave_rows or []:
		overlap_days = get_overlap_days(row.get("from_date"), row.get("to_date"), month_start, month_end)
		if overlap_days <= 0:
			continue

		total_days = flt(row.get("total_days") or overlap_days)
		daily_salary = flt(row.get("daily_salary") or fallback_daily_salary)
		full_pay = flt(overlap_days) * daily_salary
		actual_pay = flt(row.get("leave_pay_amount")) * (flt(overlap_days) / total_days if total_days else 0)
		if full_pay > actual_pay:
			deduction += round(full_pay - actual_pay, 2)

	return round(deduction, 2)


# The disciplinary catalogue stores penalties as free text ("Written warning",
# "50% daily wage", "One day / يوم"), not as a number.  Payroll needs a number
# of days' wage to multiply by the daily wage, so these phrases are mapped here
# against the same catalogue the Disciplinary Procedure reads from.
PENALTY_DAY_PHRASES = (
	("half", 0.5),
	("one", 1.0),
	("two", 2.0),
	("three", 3.0),
	("four", 4.0),
	("five", 5.0),
	("six", 6.0),
	("seven", 7.0),
	("eight", 8.0),
	("nine", 9.0),
	("ten", 10.0),
)


def parse_penalty_to_days(penalty_text) -> float:
	"""Number of days' wage a catalogue penalty text stands for.

	Warnings and non-fine outcomes (termination, promotion delay) cost nothing,
	so they return ``0.0``.  Percentages ("50% daily wage") are returned as a
	fraction of a day (``0.5``); explicit day counts ("One day", "Two days",
	"يوم") are returned as whole days.  The caller clamps the monthly total to
	the five-days'-wage ceiling the labour law sets for fines.
	"""
	text = cstr(penalty_text or "").strip().lower()
	if not text:
		return 0.0

	percent_match = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
	if percent_match:
		return round(flt(percent_match.group(1)) / 100.0, 4)

	digit_match = re.search(r"(\d+(?:\.\d+)?)\s*days?", text)
	if digit_match:
		return flt(digit_match.group(1))

	for phrase, days in PENALTY_DAY_PHRASES:
		if re.search(r"\b" + re.escape(phrase) + r"\b", text):
			return days

	if "نصف" in text:
		return 0.5
	if "يوم" in text:
		return 1.0

	return 0.0



def get_active_contract(employee: str, fields=None, as_dict=True, reference_date=None):
	"""Return the submitted contract that is active on the requested date."""
	reference_date = getdate(reference_date or today())
	field_list = fields or [
		"name",
		"basic_salary",
		"housing_allowance",
		"transport_allowance",
		"other_allowances",
		"total_salary",
	]
	rows = frappe.get_all(
		"Saudi Employment Contract",
		filters={
			"employee": employee,
			"docstatus": 1,
			"contract_status": "Active / نشط",
			"start_date": ["<=", reference_date],
		},
		or_filters=[
			["Saudi Employment Contract", "end_date", "is", "not set"],
			["Saudi Employment Contract", "end_date", ">=", reference_date],
		],
		fields=field_list,
		order_by="start_date desc",
		limit=1,
	)
	if not rows:
		return None
	row = rows[0]
	if as_dict:
		return row
	values = tuple(row.get(field) for field in field_list)
	return values[0] if len(values) == 1 else values


def assert_employee_record_access(employee: str, related_doctype: str | None = None) -> bool:
	"""Allow access to employee-scoped data for the employee or an authorized reader."""
	employee_doc = frappe.get_doc("Employee", employee)
	if employee_doc.user_id and employee_doc.user_id == frappe.session.user:
		return True

	frappe.has_permission("Employee", "read", doc=employee_doc, throw=True)
	if related_doctype:
		frappe.has_permission(related_doctype, "read", throw=True)
	return True


def assert_employee_salary_access(employee: str) -> bool:
	"""Allow salary lookup only for the employee themself or an authorized reader."""
	assert_employee_record_access(employee)
	if frappe.db.get_value("Employee", employee, "user_id") == frappe.session.user:
		return True
	contract = get_active_contract(employee, ["name"], as_dict=True)
	if contract:
		contract_doc = frappe.get_doc("Saudi Employment Contract", contract.name)
		frappe.has_permission("Saudi Employment Contract", "read", doc=contract_doc, throw=True)
	else:
		frappe.has_permission("Saudi Employment Contract", "read", throw=True)
	return True


def can_access_complete_employee_file(employee: str) -> bool:
	"""Return whether the current user may print the full, salary-bearing HR file."""
	if frappe.session.user == "Guest":
		return False
	roles = set(frappe.get_roles(frappe.session.user))
	if frappe.session.user != "Administrator" and not roles.intersection({"HR Manager", "System Manager"}):
		return False
	try:
		employee_doc = frappe.get_doc("Employee", employee)
		return bool(frappe.has_permission("Employee", "print", doc=employee_doc))
	except (frappe.DoesNotExistError, frappe.PermissionError):
		return False


def assert_complete_employee_file_access(employee: str) -> bool:
	"""Jinja security gate for the comprehensive employee print format."""
	if not can_access_complete_employee_file(employee):
		frappe.throw(
			_("Only HR Managers may print the complete employee file.<br>طباعة ملف الموظف الشامل متاحة لمدير الموارد البشرية فقط."),
			frappe.PermissionError,
		)
	return True


def get_employee_basic_salary(employee: str) -> float:
	contract = get_active_contract(employee, ["basic_salary"], as_dict=True) or {}
	basic_salary = flt(contract.get("basic_salary"))
	if basic_salary:
		return basic_salary
	return flt(frappe.db.get_value("Employee", employee, "ctc") or 0)


def get_employee_salary_components(employee: str) -> dict:
	contract = get_active_contract(
		employee,
		["basic_salary", "housing_allowance", "transport_allowance", "other_allowances", "total_salary"],
		as_dict=True,
	) or {}
	basic = flt(contract.get("basic_salary") or frappe.db.get_value("Employee", employee, "ctc") or 0)
	housing = flt(contract.get("housing_allowance") or 0)
	transport = flt(contract.get("transport_allowance") or 0)
	other = flt(contract.get("other_allowances") or 0)
	total = flt(contract.get("total_salary") or (basic + housing + transport + other))
	return {
		"basic_salary": basic,
		"housing_allowance": housing,
		"transport_allowance": transport,
		"other_allowances": other,
		"total_salary": total,
	}


def get_annual_leave_days_taken(employee: str, leave_year: int, exclude_name: str | None = None) -> float:
	filters = {
		"employee": employee,
		"docstatus": 1,
	}
	if exclude_name:
		filters["name"] = ["!=", exclude_name]

	rows = frappe.get_all(
		"Saudi Annual Leave",
		filters=filters,
		fields=["leave_start_date", "leave_end_date", "total_leave_days", "half_day"],
		ignore_permissions=True,
	)
	year_start = f"{leave_year}-01-01"
	year_end = f"{leave_year}-12-31"
	total = 0.0
	for row in rows:
		overlap_days = get_overlap_days(row.leave_start_date, row.leave_end_date, year_start, year_end)
		if overlap_days <= 0:
			continue
		if getattr(row, "half_day", 0):
			total += 0.5
			continue
		document_days = max(flt(row.total_leave_days), flt(date_diff(row.leave_end_date, row.leave_start_date) + 1))
		total += flt(row.total_leave_days or overlap_days) * (flt(overlap_days) / document_days if document_days else 0)
	return round(total, 2)


def validate_leave_policy_values(
	annual_threshold,
	annual_before,
	annual_after,
	sick_full_days,
	sick_partial_days,
	sick_partial_percentage,
	monthly_hour_leave_hours=0,
):
	"""Keep configurable benefits at or above the Saudi statutory minimums."""
	threshold = flt(annual_threshold)
	before_days = flt(annual_before)
	after_days = flt(annual_after)
	full_days = flt(sick_full_days)
	partial_days = flt(sick_partial_days)
	partial_percentage = flt(sick_partial_percentage)
	hour_hours = flt(monthly_hour_leave_hours)

	if hour_hours < 0:
		frappe.throw(
			_("Monthly hourly leave hours cannot be negative.<br>لا يمكن أن يكون رصيد الساعات الشهري سالبًا."),
			title=_("Invalid Hourly Leave / رصيد ساعات غير صالح"),
		)
	if threshold < 1 or threshold > STATUTORY_ANNUAL_THRESHOLD_YEARS:
		frappe.throw(
			_(
				"Annual leave threshold must be between 1 and 5 years.<br>"
				"يجب أن تكون عتبة الإجازة السنوية بين سنة وخمس سنوات."
			),
			title=_("Invalid Leave Threshold / عتبة إجازة غير صالحة"),
		)
	if before_days < STATUTORY_ANNUAL_BEFORE_DAYS:
		frappe.throw(
			_("Annual leave before the threshold cannot be less than 21 days.<br>لا يجوز أن يقل الاستحقاق قبل العتبة عن 21 يومًا."),
			title=_("Statutory Minimum / الحد النظامي"),
		)
	if after_days < STATUTORY_ANNUAL_AFTER_DAYS:
		frappe.throw(
			_("Annual leave after the threshold cannot be less than 30 days.<br>لا يجوز أن يقل الاستحقاق بعد العتبة عن 30 يومًا."),
			title=_("Statutory Minimum / الحد النظامي"),
		)
	if after_days < before_days:
		frappe.throw(
			_("Entitlement after the threshold cannot be lower than the earlier entitlement.<br>لا يجوز أن ينخفض الاستحقاق بعد بلوغ العتبة."),
			title=_("Invalid Entitlement / استحقاق غير صالح"),
		)
	if full_days < STATUTORY_SICK_FULL_PAY_DAYS:
		frappe.throw(
			_("Full-pay sick leave cannot be less than 30 days.<br>لا يجوز أن تقل الإجازة المرضية بأجر كامل عن 30 يومًا."),
			title=_("Statutory Minimum / الحد النظامي"),
		)
	if full_days + partial_days < STATUTORY_SICK_PAID_TIER_DAYS:
		frappe.throw(
			_("Full and partial paid sick-leave tiers must cover at least 90 days.<br>يجب أن تغطي شرائح المرضية المدفوعة 90 يومًا على الأقل."),
			title=_("Statutory Minimum / الحد النظامي"),
		)
	if full_days + partial_days > STATUTORY_SICK_MAX_DAYS:
		frappe.throw(
			_("Paid sick-leave tiers cannot exceed the 120-day benefit cycle.<br>لا يجوز أن تتجاوز شرائح المرضية المدفوعة دورة الاستحقاق البالغة 120 يومًا."),
			title=_("Invalid Sick Leave Tiers / شرائح مرضية غير صالحة"),
		)
	if partial_days and partial_percentage < STATUTORY_SICK_PARTIAL_PAY_PERCENTAGE:
		frappe.throw(
			_("Partial sick-leave pay cannot be less than 75%.<br>لا يجوز أن تقل نسبة أجر المرضية الجزئي عن 75٪."),
			title=_("Statutory Minimum / الحد النظامي"),
		)


def _normalize_leave_policy_values(values):
	threshold = min(
		STATUTORY_ANNUAL_THRESHOLD_YEARS,
		max(1, flt(values.get("annual_leave_years_threshold") or STATUTORY_ANNUAL_THRESHOLD_YEARS)),
	)
	before_days = max(
		STATUTORY_ANNUAL_BEFORE_DAYS,
		int(flt(values.get("annual_leave_before_threshold") or STATUTORY_ANNUAL_BEFORE_DAYS)),
	)
	after_days = max(
		STATUTORY_ANNUAL_AFTER_DAYS,
		before_days,
		int(flt(values.get("annual_leave_after_threshold") or STATUTORY_ANNUAL_AFTER_DAYS)),
	)
	full_days = min(
		STATUTORY_SICK_MAX_DAYS,
		max(
			STATUTORY_SICK_FULL_PAY_DAYS,
			int(flt(values.get("sick_leave_full_pay_days") or STATUTORY_SICK_FULL_PAY_DAYS)),
		),
	)
	partial_days = max(0, int(flt(values.get("sick_leave_partial_pay_days") or 0)))
	if full_days + partial_days < STATUTORY_SICK_PAID_TIER_DAYS:
		partial_days = STATUTORY_SICK_PAID_TIER_DAYS - full_days
	if full_days + partial_days > STATUTORY_SICK_MAX_DAYS:
		partial_days = max(0, STATUTORY_SICK_MAX_DAYS - full_days)
	partial_percentage = max(
		STATUTORY_SICK_PARTIAL_PAY_PERCENTAGE,
		flt(values.get("sick_leave_partial_pay_percentage") or STATUTORY_SICK_PARTIAL_PAY_PERCENTAGE),
	)
	return {
		"annual_leave_years_threshold": threshold,
		"annual_leave_before_threshold": before_days,
		"annual_leave_after_threshold": after_days,
			"sick_leave_full_pay_days": full_days,
		"sick_leave_partial_pay_days": partial_days,
		"sick_leave_partial_pay_percentage": partial_percentage,
		"monthly_hour_leave_hours": max(0, flt(values.get("monthly_hour_leave_hours") or 0)),
	}


def _get_employee_leave_context(employee):
	context = frappe.db.get_value(
		"Employee",
		employee,
		["name", "company", "department", "date_of_joining"],
		as_dict=True,
	)
	if not context:
		frappe.throw(_("Employee {0} was not found. / لم يتم العثور على الموظف {0}.").format(employee))
	if not context.date_of_joining:
		frappe.throw(
			_("Employee joining date is required to calculate leave entitlement.<br>تاريخ مباشرة الموظف مطلوب لحساب استحقاق الإجازة."),
			title=_("Missing Joining Date / تاريخ المباشرة غير موجود"),
		)
	return context


def _find_leave_policy_assignment(context, reference_date):
	if not frappe.db.exists("DocType", "Saudi Leave Policy Assignment"):
		return None

	targets = [
		(LEAVE_SCOPE_EMPLOYEE, "employee", context.name),
		(LEAVE_SCOPE_DEPARTMENT, "department", context.department),
	]
	for scope, target_field, target in targets:
		if not target:
			continue
		assignments = frappe.get_all(
			"Saudi Leave Policy Assignment",
			filters=[
				["enabled", "=", 1],
				["company", "=", context.company],
				["applies_to", "=", scope],
				[target_field, "=", target],
				["effective_from", "<=", reference_date],
			],
			or_filters=[
				["effective_to", "is", "not set"],
				["effective_to", ">=", reference_date],
			],
			fields=["name", "policy", "applies_to", "effective_from"],
			order_by="effective_from desc, modified desc",
			limit_page_length=20,
		)
		for assignment in assignments:
			policy = frappe.db.get_value(
				"Saudi Leave Policy",
				assignment.policy,
			[
				"name",
				"policy_name",
				"company",
				"enabled",
				"annual_leave_years_threshold",
				"annual_leave_before_threshold",
				"annual_leave_after_threshold",
				"sick_leave_full_pay_days",
				"sick_leave_partial_pay_days",
				"sick_leave_partial_pay_percentage",
				"monthly_hour_leave_hours",
			],
				as_dict=True,
			)
			if policy and policy.enabled and policy.company == context.company:
				return assignment, policy
	return None


def resolve_leave_policy(employee: str, reference_date: str | None = None) -> dict:
	"""Resolve employee > department > global settings using the employee master record."""
	reference = getdate(reference_date) if reference_date else getdate()
	context = _get_employee_leave_context(employee)
	resolved = _find_leave_policy_assignment(context, reference)

	if resolved:
		assignment, policy = resolved
		values = _normalize_leave_policy_values(policy)
		return {
			**values,
			"policy": policy.name,
			"policy_name": policy.policy_name,
			"assignment": assignment.name,
			"source_type": assignment.applies_to,
			"company": context.company,
			"department": context.department,
			"reference_date": reference,
		}

	settings = frappe.get_cached_doc("Saudi HR Settings")
	values = _normalize_leave_policy_values(settings)
	return {
		**values,
		"policy": None,
		"policy_name": _("Saudi HR Settings / إعدادات الموارد البشرية"),
		"assignment": None,
		"source_type": LEAVE_SOURCE_SETTINGS,
		"company": context.company,
		"department": context.department,
		"reference_date": reference,
	}


def get_annual_leave_entitlement_details(employee: str, date: str | None = None) -> dict:
	"""Return the auditable annual entitlement and its resolved policy source."""
	reference = getdate(date) if date else getdate()
	context = _get_employee_leave_context(employee)
	policy = resolve_leave_policy(employee, reference)
	threshold = flt(policy["annual_leave_years_threshold"])
	policy_threshold_date = add_years(context.date_of_joining, int(threshold))
	statutory_threshold_date = add_years(context.date_of_joining, STATUTORY_ANNUAL_THRESHOLD_YEARS)
	policy_entitlement = (
		policy["annual_leave_after_threshold"]
		if reference >= getdate(policy_threshold_date)
		else policy["annual_leave_before_threshold"]
	)
	statutory_minimum = (
		STATUTORY_ANNUAL_AFTER_DAYS
		if reference >= getdate(statutory_threshold_date)
		else STATUTORY_ANNUAL_BEFORE_DAYS
	)
	return {
		**policy,
		"entitled": int(max(flt(policy_entitlement), statutory_minimum)),
		"statutory_minimum": statutory_minimum,
		"joining_date": getdate(context.date_of_joining),
		"years_of_service": round(date_diff(reference, context.date_of_joining) / 365.25, 2),
	}


def get_leave_balance_adjustment(employee: str, leave_year: int) -> float:
	"""Sum of submitted Leave Balance Adjustment days for the employee and leave year.

	Opening balances are excluded: they anchor the accrual instead of being a
	plain adjustment (see get_annual_leave_balance).
	"""
	rows = frappe.get_all(
		"Leave Balance Adjustment",
		filters={"employee": employee, "leave_year": leave_year, "docstatus": 1},
		fields=["adjustment_days", "is_opening_balance"],
		ignore_permissions=True,
	)
	return round(
		sum(flt(r.adjustment_days or 0) for r in rows if not cint(r.get("is_opening_balance"))),
		2,
	)


def get_leave_balance_opening(employee: str, leave_year: int) -> dict | None:
	"""Return the employee's opening balance for a leave year, if one is recorded.

	When several are present the latest as-of date wins (the doctype also blocks
	duplicates on submit, this keeps reads safe).
	"""
	rows = frappe.get_all(
		"Leave Balance Adjustment",
		filters={
			"employee": employee,
			"leave_year": leave_year,
			"docstatus": 1,
			"is_opening_balance": 1,
		},
		fields=["adjustment_days", "balance_as_of_date"],
		ignore_permissions=True,
	)
	rows = [r for r in rows if r.get("balance_as_of_date")]
	if not rows:
		return None
	latest = max(rows, key=lambda r: getdate(r["balance_as_of_date"]))
	return {
		"days": round(flt(latest.adjustment_days or 0), 2),
		"as_of": getdate(latest.balance_as_of_date),
	}


def monthly_accrual_rate(details: dict, month_end_date) -> float:
	"""Accrual for one month: 1.75 days before the service threshold, 2.5 after.

	The rate is chosen per month so crossing the 5-year threshold mid-year is
	accounted for rather than applying one rate to the whole year.
	"""
	threshold_years = flt(details.get("annual_leave_years_threshold") or STATUTORY_ANNUAL_THRESHOLD_YEARS)
	statutory_threshold_years = STATUTORY_ANNUAL_THRESHOLD_YEARS
	joining_date = details.get("joining_date")
	if not joining_date:
		return MONTHLY_ACCRUAL_BEFORE_THRESHOLD
	effective_threshold_years = min(int(threshold_years), statutory_threshold_years)
	threshold_date = add_years(getdate(joining_date), effective_threshold_years)
	if getdate(month_end_date) >= getdate(threshold_date):
		return MONTHLY_ACCRUAL_AFTER_THRESHOLD
	return MONTHLY_ACCRUAL_BEFORE_THRESHOLD


def get_accrued_annual_leave(details: dict, period_start, period_end) -> float:
	"""Completed service months between two dates, credited at the monthly rate.

	Each whole month between period_start and period_end earns 1.75 or 2.5 days
	depending on the employee's service at that month's end. The total is capped
	at the annual entitlement so accrual can never exceed 21/30 days.
	"""
	start = getdate(period_start)
	end = getdate(period_end)
	if end <= start:
		return 0.0

	accrued = 0.0
	cursor = start
	while True:
		month_end = get_last_day(cursor)
		if month_end > end:
			break
		accrued += monthly_accrual_rate(details, month_end)
		next_month = getdate(add_months(cursor, 1))
		if next_month <= cursor:
			break
		cursor = next_month

	cap = flt(details.get("entitled") or STATUTORY_ANNUAL_AFTER_DAYS)
	return round(min(accrued, cap), 2)


def get_annual_leave_balance(employee: str, reference_date: str | None = None, exclude_name: str | None = None) -> dict:
	reference = getdate(reference_date) if reference_date else getdate()
	details = get_annual_leave_entitlement_details(employee, reference)
	taken = get_annual_leave_days_taken(employee, reference.year, exclude_name=exclude_name)
	adjustment = get_leave_balance_adjustment(employee, reference.year)
	opening = get_leave_balance_opening(employee, reference.year)

	if opening:
		# Opening balance anchors the total; only months after the as-of date accrue.
		accrual_start = add_days(opening["as_of"], 1)
		accrued = get_accrued_annual_leave(details, accrual_start, reference)
		entitled = round(flt(opening["days"]) + accrued, 2)
		balance = entitled - flt(taken) + flt(adjustment)
	else:
		accrued = get_accrued_annual_leave(details, f"{reference.year}-01-01", reference)
		entitled = accrued
		balance = flt(accrued) - flt(taken) + flt(adjustment)

	return {
		**details,
		"entitled": entitled,
		"annual_entitlement": flt(details["entitled"]),
		"accrued": accrued,
		"opening_balance": flt(opening["days"]) if opening else 0.0,
		"opening_as_of": opening["as_of"] if opening else None,
		"taken": taken,
		"adjustment": adjustment,
		"balance": balance,
		"year": reference.year,
	}


def get_annual_leave_entitlement(employee: str, date: str = None) -> int:
	return get_annual_leave_entitlement_details(employee, date)["entitled"]


EMERGENCY_LEAVE_ANNUAL_DAYS = 3


def get_emergency_leave_days_taken(
	employee: str, leave_year: int, exclude_name: str | None = None
) -> float:
	"""Emergency days already taken this calendar year, counting each overlapping day once."""
	filters = {"employee": employee, "docstatus": 1}
	if exclude_name:
		filters["name"] = ["!=", exclude_name]

	rows = frappe.get_all(
		"Saudi Emergency Leave",
		filters=filters,
		fields=["from_date", "to_date"],
		ignore_permissions=True,
	)
	year_start = f"{leave_year}-01-01"
	year_end = f"{leave_year}-12-31"
	total = 0.0
	for row in rows:
		total += max(0, get_overlap_days(row.from_date, row.to_date, year_start, year_end))
	return round(total, 2)


def get_emergency_leave_balance(
	employee: str, reference_date: str | None = None, exclude_name: str | None = None
) -> dict:
	"""Three emergency days per calendar year, minus what this employee already used.

	Unlike annual and sick leave there is no policy document behind this quota: the
	three days are a fixed company allowance, so the number lives here rather than
	in a policy doctype.
	"""
	reference = getdate(reference_date) if reference_date else getdate()
	entitled = float(EMERGENCY_LEAVE_ANNUAL_DAYS)
	taken = get_emergency_leave_days_taken(employee, reference.year, exclude_name=exclude_name)
	return {
		"entitled": entitled,
		"taken": taken,
		"available": round(max(0.0, entitled - taken), 2),
		"year": reference.year,
	}


def get_eosb_amount(employee: str, termination_reason: str, termination_date: str = None) -> dict:
	"""
	حساب مكافأة نهاية الخدمة وفق المادة 84 من نظام العمل السعودي.

	Returns dict with:
		- years_of_service
		- eosb_gross        (قبل معامل الاستقالة)
		- resignation_factor
		- eosb_net          (المستحق الفعلي)
	"""
	emp = frappe.get_doc("Employee", employee)
	details = calculate_eosb_components(
		emp.date_of_joining,
		termination_date or getdate(),
		get_employee_basic_salary(employee),
		termination_reason,
	)

	return {
		"years_of_service": details["years_of_service"],
		"monthly_basic": details["monthly_basic"],
		"eosb_gross": details["eosb_gross"],
		"resignation_factor": details["resignation_factor"],
		"eosb_net": details["net_eosb"],
	}


def _get_resignation_factor(years: float, termination_reason: str) -> float:
	"""
	معامل الاستقالة وفق المادة (الخامسة والثمانين) من نظام العمل:
	- استقالة < 2 سنة  → 0
	- استقالة 2–5 سنوات → 1/3
	- استقالة > 5 وأقل من 10 سنوات → 2/3
	- استقالة 10 سنوات فأكثر → 1.0 (المكافأة كاملة)
	- إنهاء من صاحب العمل / انتهاء عقد / وفاة → 1.0
	- فصل تأديبي (م.80) → 0
	"""
	return get_eosb_factor_and_label(termination_reason, years)[0]


def get_eosb_factor_and_label(termination_reason: str, years: float) -> tuple[float, str]:
	reason = termination_reason or ""
	if text_matches_tokens(reason, "dismissal", "فصل"):
		return 0.0, "فصل تأديبي (م.80) — لا مكافأة / Disciplinary Dismissal — No EOSB"

	if text_matches_tokens(reason, "resignation", "استقالة"):
		if years < 2:
			return 0.0, "استقالة < سنتان — لا مكافأة / Resignation < 2 yrs — No EOSB"
		if years <= 5:
			return round(1 / 3, 4), "استقالة 2–5 سنوات — ثلث المكافأة / Resignation 2–5 yrs — 1/3 EOSB"
		if years < 10:
			return round(2 / 3, 4), "استقالة 5–10 سنوات — ثلثا المكافأة / Resignation 5–10 yrs — 2/3 EOSB"
		return 1.0, "استقالة 10 سنوات فأكثر — المكافأة كاملة / Resignation 10+ yrs — Full EOSB"

	return 1.0, "مكافأة كاملة / Full EOSB"


def build_eosb_notes(years, monthly_basic, eosb_years_1_5, eosb_years_above_5, eosb_gross, factor, label, net_eosb):
	return (
		f"سنوات الخدمة: {years:.2f} سنة\n"
		f"الراتب الأساسي: {monthly_basic:,.2f}\n"
		f"مكافأة السنوات 1-5: {eosb_years_1_5:,.2f}\n"
		f"مكافأة السنوات >5: {eosb_years_above_5:,.2f}\n"
		f"المكافأة الإجمالية: {eosb_gross:,.2f}\n"
		f"معامل الاستقالة: {factor} ({label})\n"
		f"صافي المكافأة: {net_eosb:,.2f}"
	)


def calculate_eosb_components(joining_date, termination_date, last_basic_salary, termination_reason, eosb_deductions=0) -> dict:
	joining = getdate(joining_date)
	termination = getdate(termination_date)
	if termination <= joining:
		frappe.throw(
			_(
				"Termination date must be after the joining date.<br>"
				"تاريخ إنهاء الخدمة يجب أن يكون بعد تاريخ الالتحاق بالعمل."
			),
			title=_("Invalid Date / تاريخ غير صحيح"),
		)

	monthly_basic = flt(last_basic_salary)
	if monthly_basic <= 0:
		frappe.throw(
			_("Last basic salary must be greater than zero.<br>يجب أن يكون الراتب الأساسي الأخير أكبر من صفر."),
			title=_("Missing Basic Salary / راتب أساسي غير متوفر"),
		)

	deductions = flt(eosb_deductions)
	if deductions < 0:
		frappe.throw(
			_("EOSB deductions cannot be negative.<br>خصومات مكافأة نهاية الخدمة لا يمكن أن تكون سالبة."),
			title=_("Invalid Deduction / خصم غير صالح"),
		)

	total_days = date_diff(termination, joining)
	years = total_days / 365.0
	# المادة (84): يستحق العامل مكافأة عن أجزاء السنة بنسبة ما قضاه منها في العمل،
	# فلا يوجد حد أدنى قدره سنة. أما شرط السنتين فهو خاص بالاستقالة (المادة 85)
	# ويُطبَّق عبر معامل الاستقالة أدناه.
	if years <= 5:
		eosb_years_1_5 = round((monthly_basic / 2) * years, 2)
		eosb_years_above_5 = 0.0
	else:
		eosb_years_1_5 = round((monthly_basic / 2) * 5, 2)
		eosb_years_above_5 = round(monthly_basic * (years - 5), 2)

	eosb_gross = round(eosb_years_1_5 + eosb_years_above_5, 2)
	factor, label = get_eosb_factor_and_label(termination_reason, years)
	net_eosb = round(eosb_gross * factor - deductions, 2)
	if net_eosb < 0:
		frappe.throw(
			_("EOSB deductions exceed the payable amount.<br>خصومات مكافأة نهاية الخدمة تتجاوز المبلغ المستحق."),
			title=_("Invalid Deduction / خصم غير صالح"),
		)

	return {
		"years_of_service": round(years, 2),
		"monthly_basic": monthly_basic,
		"eosb_years_1_5": eosb_years_1_5,
		"eosb_years_above_5": eosb_years_above_5,
		"eosb_gross": eosb_gross,
		"resignation_factor": factor,
		"resignation_factor_label": label,
		"net_eosb": net_eosb,
		"calculation_notes": build_eosb_notes(
			years,
			monthly_basic,
			eosb_years_1_5,
			eosb_years_above_5,
			eosb_gross,
			factor,
			label,
			net_eosb,
		),
	}


# ---------------------------------------------------------------------------
# اشتراكات التأمينات الاجتماعية (GOSI)
#
# النظام السابق — لمن بدأ اشتراكه قبل 3 يوليو 2024:
#   المعاشات 9% على كل طرف + ساند 0.75% على كل طرف + الأخطار المهنية 2% على صاحب العمل
#   => العامل 9.75% وصاحب العمل 11.75%
#
# نظام التأمينات الاجتماعية الجديد (مرسوم ملكي م/273) — لمن لا توجد له مدد اشتراك
# سابقة قبل 3 يوليو 2024: ترتفع نسبة المعاشات من 9% إلى 11% على كل طرف بواقع
# 0.5% سنوياً اعتباراً من يوليو 2025 وحتى يوليو 2028.
#
# غير السعوديين: فرع الأخطار المهنية فقط 2% على صاحب العمل.
# وعاء الاشتراك = الأجر الأساسي + بدل السكن بحد أقصى 45,000 ريال شهرياً.
# ---------------------------------------------------------------------------
# الحد الأقصى لوعاء اشتراك التأمينات
GOSI_MAX_BASE = 45000.0

GOSI_NEW_SYSTEM_START_DATE = "2024-07-03"
GOSI_OLD_SYSTEM_PENSION_RATE = 9.0
GOSI_DEFAULT_SANED_RATE = 0.75
GOSI_DEFAULT_OCCUPATIONAL_HAZARDS_RATE = 2.0

# تُطبَّق الزيادة على شهر الاشتراك كاملاً، والذكرى النظامية للقانون هي 3 يوليو.
GOSI_NEW_SYSTEM_PENSION_SCHEDULE = [
	("2028-07-01", 11.0),
	("2027-07-01", 10.5),
	("2026-07-01", 10.0),
	("2025-07-01", 9.5),
]


def get_gosi_pension_rate(is_new_system: bool, as_on_date=None) -> float:
	"""نسبة فرع المعاشات على كل طرف في التاريخ المطلوب."""
	if not is_new_system:
		return GOSI_OLD_SYSTEM_PENSION_RATE

	reference = getdate(as_on_date or today())
	for start_date, rate in GOSI_NEW_SYSTEM_PENSION_SCHEDULE:
		if reference >= getdate(start_date):
			return rate
	return GOSI_OLD_SYSTEM_PENSION_RATE


def is_gosi_new_system_subscriber(employee: str) -> bool:
	"""هل يخضع العامل لنظام التأمينات الجديد (لا توجد له مدد اشتراك قبل 3 يوليو 2024)."""
	if not employee:
		return False

	first_contribution_date = None
	if frappe.get_meta("Employee").has_field("gosi_first_contribution_date"):
		first_contribution_date = frappe.db.get_value("Employee", employee, "gosi_first_contribution_date")
	# عند غياب تاريخ أول اشتراك يُستخدم تاريخ الالتحاق كتقدير، وقد يخالف الواقع
	# إذا كانت للعامل مدد اشتراك سابقة لدى صاحب عمل آخر.
	if not first_contribution_date:
		first_contribution_date = frappe.db.get_value("Employee", employee, "date_of_joining")
	if not first_contribution_date:
		return False

	return getdate(first_contribution_date) >= getdate(GOSI_NEW_SYSTEM_START_DATE)


GOSI_SOURCE_ASSUMED = "Assumed from Joining Date / مُقدَّر من تاريخ الالتحاق"
GOSI_SOURCE_CONFIRMED = "Confirmed from GOSI / مؤكد من التأمينات"


@frappe.whitelist(methods=["POST"])
def backfill_gosi_first_contribution_dates(dry_run=1, company=None):
	"""
	تعبئة تاريخ أول اشتراك من تاريخ الالتحاق لمن التحق في 3 يوليو 2024 أو بعده.

	التاريخ المُعبَّأ تقدير وليس واقعة مؤكدة: من التحق بعد هذا التاريخ وله مدد
	اشتراك سابقة لدى صاحب عمل آخر يبقى على النظام السابق، ولا سبيل لمعرفة ذلك
	إلا من سجل التأمينات. لذلك تُوسم كل قيمة تُكتب هنا بأنها مُقدَّرة.

	لا يُمسّ أي موظف لديه تاريخ مسجّل مسبقاً.
	"""
	assert_doctype_permissions("Employee", ("read", "write"))
	dry_run = cint(dry_run)

	meta = frappe.get_meta("Employee")
	if not meta.has_field("gosi_first_contribution_date"):
		frappe.throw(_("Employee is missing the GOSI first contribution date field."))

	filters = {
		"date_of_joining": (">=", GOSI_NEW_SYSTEM_START_DATE),
		"gosi_first_contribution_date": ("is", "not set"),
	}
	if company:
		filters["company"] = company

	candidates = frappe.get_all(
		"Employee",
		filters=filters,
		fields=["name", "employee_name", "date_of_joining"],
		order_by="date_of_joining",
	)

	updated = []
	has_source_field = meta.has_field("gosi_subscription_date_source")
	for row in candidates:
		if not dry_run:
			frappe.db.set_value(
				"Employee",
				row.name,
				{
					"gosi_first_contribution_date": row.date_of_joining,
					**({"gosi_subscription_date_source": GOSI_SOURCE_ASSUMED} if has_source_field else {}),
				},
				update_modified=False,
			)
		updated.append(
			{
				"employee": row.name,
				"employee_name": row.employee_name,
				"assumed_date": str(row.date_of_joining),
			}
		)

	# لا يُستدعى commit هنا: طلبات الويب تُثبِّت تلقائياً، ويبقى الاستدعاء من
	# السكربتات والاختبارات ضمن معاملة واحدة يتحكم بها المستدعي.
	return {
		"dry_run": bool(dry_run),
		"cutover_date": GOSI_NEW_SYSTEM_START_DATE,
		"count": len(updated),
		"employees": updated,
	}


def round_gosi_amount(value) -> float:
	"""تقريب اشتراك التأمينات إلى ريال كامل (تقريب تجاري: النصف لأعلى).

	المبالغ تُطابق بها العميل على ريال كامل (406.28 → 406، 595.82 → 596)،
	والتقريب المدمج في بايثون يقرّب النصف للزوج، لذا يُستخدم هنا تقريب تجاري.
	"""
	from decimal import ROUND_HALF_UP, Decimal

	return float(Decimal(str(flt(value))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def get_gosi_base(basic, housing, include_total_salary: bool = False, extra_allowances=0.0) -> float:
	"""وعاء اشتراك التأمينات: الراتب الأساسي + بدل السكن (مع تقييد 45,000).

	ضريبة اشتراك التأمينات تُحتسب على الأجر الخاضع للاشتراك (الأساسي + السكن)،
	وليس على الأساسي وحده. خيار الإعدادات يوسّع الوعاء لكل البدلات عند تفعيله.
	"""
	base = flt(basic) + flt(housing)
	if include_total_salary:
		base += flt(extra_allowances)
	return min(base, GOSI_MAX_BASE)


def get_gosi_rates(nationality: str, employee: str = None, as_on_date=None) -> dict:
	"""
	إرجاع معدلات GOSI حسب الجنسية ونظام الاشتراك المطبَّق على العامل.

	أولوية النسب: النسبة المخصّصة على سجل الموظف تتقدّم على الإعدادات العامة،
	ثم تُطبَّق نسب السعودي/غير السعودي وفق نظام الاشتراك.
	"""
	settings = frappe.get_single("Saudi HR Settings")

	if not is_saudi_nationality(nationality):
		employee_rate = flt(settings.gosi_non_saudi_employee_rate)
		employer_rate = flt(settings.gosi_non_saudi_employer_rate) or GOSI_DEFAULT_OCCUPATIONAL_HAZARDS_RATE
		override = _get_gosi_rate_overrides(employee)
		if override.get("employee_rate") is not None:
			employee_rate = override["employee_rate"]
		if override.get("employer_rate") is not None:
			employer_rate = override["employer_rate"]
		return {
			"employee_rate": employee_rate,
			"employer_rate": employer_rate,
			"pension_rate": 0.0,
			"system": "Non-Saudi / غير سعودي",
		}

	# القيمة غير المضبوطة تُعامل كمفعّلة، لأن الجدول الجديد هو الوضع النظامي القائم.
	new_system_flag = getattr(settings, "gosi_apply_new_system_schedule", None)
	apply_new_system = 1 if new_system_flag is None else cint(new_system_flag)
	if apply_new_system and is_gosi_new_system_subscriber(employee):
		saned = flt(getattr(settings, "gosi_saned_rate", None) or GOSI_DEFAULT_SANED_RATE)
		hazards = flt(
			getattr(settings, "gosi_occupational_hazards_rate", None) or GOSI_DEFAULT_OCCUPATIONAL_HAZARDS_RATE
		)
		pension = get_gosi_pension_rate(True, as_on_date)
		rates = {
			"employee_rate": round(pension + saned, 4),
			"employer_rate": round(pension + saned + hazards, 4),
			"pension_rate": pension,
			"system": "New System / نظام التأمينات الجديد",
		}
	else:
		rates = {
			"employee_rate": flt(settings.gosi_saudi_employee_rate) or 9.75,
			"employer_rate": flt(settings.gosi_saudi_employer_rate) or 11.75,
			"pension_rate": GOSI_OLD_SYSTEM_PENSION_RATE,
			"system": "Previous System / النظام السابق",
		}

	override = _get_gosi_rate_overrides(employee)
	if override.get("employee_rate") is not None:
		rates["employee_rate"] = override["employee_rate"]
	if override.get("employer_rate") is not None:
		rates["employer_rate"] = override["employer_rate"]
	return rates


def _get_gosi_rate_overrides(employee: str = None) -> dict:
	"""النسب المخصّصة على سجل الموظف (إن وُجدت) لتجاوز الإعدادات العامة."""
	if not employee:
		return {}
	meta = frappe.get_meta("Employee")
	fields = [
		fieldname
		for fieldname in ("custom_gosi_employee_rate", "custom_gosi_employer_rate")
		if meta.has_field(fieldname)
	]
	if not fields:
		return {}
	row = frappe.db.get_value("Employee", employee, fields, as_dict=True) or {}
	employee_rate = flt(row.get("custom_gosi_employee_rate"))
	employer_rate = flt(row.get("custom_gosi_employer_rate"))
	return {
		"employee_rate": employee_rate if employee_rate > 0 else None,
		"employer_rate": employer_rate if employer_rate > 0 else None,
	}


def is_saudi_nationality(nationality: str) -> bool:
	text = (nationality or "").strip().lower()
	if not text:
		return False
	return text == "sa" or "saudi" in text or "سعودي" in text


def get_employee_nationality(employee: str) -> str:
	"""جنسية الموظف بصيغة قابلة للربط بحقل Country.

	تُستخدم هذه الدالة حيث تُربط الجنسية بدولة (مثل سجل التدريب)، فلا تصلح
	التسمية العربية في custom_nationality. لتحديد اشتراك التأمينات استخدم
	get_employee_gosi_nationality التي تعطي الأولوية لسجل الموظف.
	"""
	if not employee:
		return ""

	if frappe.get_meta("Employee").has_field("nationality"):
		return frappe.db.get_value("Employee", employee, "nationality") or ""

	return get_contract_nationality_lookup([employee]).get(employee) or ""


def get_employee_gosi_nationality(employee: str, fallback: str = "") -> str:
	"""جنسية الموظف لتحديد نسبة التأمينات — الأولوية لسجل الموظف.

	يُفضّل custom_nationality (التسمية العربية المعتمدة في ملف الموظف) ثم
	حقل nationality القياسي ثم عقد العمل، وأخيراً القيمة الاحتياطية المُمرّرة.
	"""
	if not employee:
		return fallback or ""

	candidates = []
	if frappe.get_meta("Employee").has_field("nationality"):
		candidates.append(frappe.db.get_value("Employee", employee, "nationality"))
	if frappe.get_meta("Employee").has_field("custom_nationality"):
		candidates.append(frappe.db.get_value("Employee", employee, "custom_nationality"))
	candidates.append(get_contract_nationality_lookup([employee]).get(employee))
	candidates.append(fallback)
	for value in candidates:
		if (value or "").strip():
			return value
	return ""


def is_gosi_company_paid(employee: str = None) -> bool:
	"""هل تتحمّل الشركة اشتراك الموظف بدلاً منه (فيُصرف راتبه دون اقتطاع)."""
	if not employee:
		return False
	if not frappe.get_meta("Employee").has_field("custom_gosi_company_pays"):
		return False
	return bool(cint(frappe.db.get_value("Employee", employee, "custom_gosi_company_pays")))


def get_contract_nationality_lookup(employees: list[str]) -> dict[str, str]:
	if not employees:
		return {}

	lookup = {}
	for row in frappe.get_all(
		"Saudi Employment Contract",
		filters={"employee": ["in", employees], "docstatus": ["<", 2]},
		fields=["employee", "nationality"],
		order_by="start_date desc, modified desc",
		limit_page_length=0,
	):
		employee = row.get("employee")
		if row.get("nationality") and employee and employee not in lookup:
			lookup[employee] = row.get("nationality")
	return lookup


def get_sick_leave_pay(employee: str, sick_days_this_year: int) -> dict:
	"""
	حساب أجر الإجازة المرضية بحسب م.117:
	  الأيام 1–30   → 100%
	  الأيام 31–90  → 75%
	  الأيام 91–120 → 0%
	"""
	settings = frappe.get_single("Saudi HR Settings")
	full_days = int(settings.sick_leave_full_pay_days or 30)
	partial_days = int(settings.sick_leave_partial_pay_days or 60)
	partial_pct = flt(settings.sick_leave_partial_pay_percentage or 75) / 100

	used = sick_days_this_year
	if used <= full_days:
		return {"rate": 1.0, "label": "Full Pay / أجر كامل"}
	elif used <= full_days + partial_days:
		return {"rate": partial_pct, "label": f"Partial Pay {partial_pct*100:.0f}% / أجر جزئي"}
	else:
		return {"rate": 0.0, "label": "No Pay / بدون أجر"}


def get_hourly_leave_balance(employee: str, reference_date: str | None = None, exclude_name: str | None = None) -> dict:
	"""Monthly hourly leave balance from policy allowance."""
	from frappe.utils import get_last_day, getdate

	from saudi_hr.saudi_hr.workflow_catalogue import state_bucket

	reference = getdate(reference_date) if reference_date else getdate()
	details = get_annual_leave_entitlement_details(employee, reference)
	allowance = flt(details.get("monthly_hour_leave_hours") or 0)
	month_start = reference.replace(day=1)
	month_end = get_last_day(reference)

	filters = {
		"employee": employee,
		"leave_date": ["between", [month_start, month_end]],
		"docstatus": ["!=", 2],
	}
	rows = frappe.get_all(
		"Saudi Hourly Leave Request",
		filters=filters,
		fields=["name", "total_hours", "docstatus", "workflow_state"],
		ignore_permissions=True,
	)

	approved = 0.0
	pending = 0.0
	for row in rows:
		if row.name == exclude_name:
			continue
		hours = flt(row.total_hours or 0)
		if cint(row.docstatus) == 1:
			approved += hours
			continue
		bucket = state_bucket(row.get("workflow_state"))
		if bucket == "pending":
			pending += hours
		elif bucket == "approved":
			approved += hours

	balance = allowance - approved
	available = allowance - approved - pending
	return {
		"allowance": round(allowance, 2),
		"approved": round(approved, 2),
		"pending": round(pending, 2),
		"balance": round(balance, 2),
		"available": round(available, 2),
		"month": reference.month,
		"year": reference.year,
		"reference_date": str(reference),
		"policy_name": details.get("policy_name"),
		"assignment": details.get("assignment"),
	}
