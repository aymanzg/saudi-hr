import frappe
from frappe.utils import add_to_date, cstr, get_datetime, get_time, getdate


VOICE_POLICY_DISABLED = "Disabled / معطل"
VOICE_POLICY_OPTIONAL = "Optional / اختياري"
VOICE_POLICY_REQUIRED = "Required / إلزامي"


def _get_shift_assignment(employee, attendance_date):
	assignment = frappe.db.get_value(
		"Saudi Shift Assignment",
		{
			"employee": employee,
			"status": "Active",
			"docstatus": 1,
			"start_date": ["<=", attendance_date],
			"end_date": ["in", ["", None]],
		},
		["name", "shift_type", "start_date", "end_date"],
		as_dict=True,
	)
	if assignment or not frappe.db.exists("DocType", "Saudi Shift Assignment"):
		return assignment

	rows = frappe.db.sql(
		"""
		SELECT name, shift_type, start_date, end_date
		FROM `tabSaudi Shift Assignment`
		WHERE employee = %s
		  AND status = 'Active'
		  AND docstatus = 1
		  AND start_date <= %s
		  AND (end_date IS NULL OR end_date = '' OR end_date >= %s)
		ORDER BY start_date DESC, modified DESC
		LIMIT 1
		""",
		(employee, attendance_date, attendance_date),
		as_dict=True,
	)
	return rows[0] if rows else None


def _get_shift_type(shift_type):
	if not shift_type:
		return None
	# flexible_start_minutes arrives with a migrate; until then read without it
	optional = [field for field in ("flexible_start_minutes",) if frappe.db.has_column("Saudi Shift Type", field)]
	return frappe.db.get_value(
		"Saudi Shift Type",
		shift_type,
		optional + [
			"name",
			"start_time",
			"end_time",
			"begin_check_in_before_shift_start_time",
			"allow_check_out_after_shift_end_time",
			"enable_late_entry_marking",
			"late_entry_grace_period",
			"enable_early_exit_marking",
			"early_exit_grace_period",
		],
		as_dict=True,
	)


def _combine_shift_datetime(attendance_date, time_value):
	if not time_value:
		return None
	attendance_date = getdate(attendance_date)
	time_value = get_time(time_value)
	return get_datetime(f"{attendance_date} {time_value}")


def _is_whole_day_window(start_dt, end_dt):
	"""A blank or full-day window is an open shift: nobody is late or early.

	A shift stored as 00:00-23:59 looks scheduled but really means "any time",
	so measuring punches against it would flag every normal check-in as late
	(minutes since midnight) and every check-out as early (minutes until 23:59).
	"""
	if not start_dt and not end_dt:
		return True
	if start_dt and end_dt and (end_dt - start_dt).total_seconds() >= 23 * 3600:
		return True
	return False


def _build_schedule_window(attendance_date, shift_type_doc):
	if not shift_type_doc:
		return {}

	start_dt = _combine_shift_datetime(attendance_date, shift_type_doc.start_time)
	end_dt = _combine_shift_datetime(attendance_date, shift_type_doc.end_time)
	if start_dt and end_dt and end_dt <= start_dt:
		end_dt = add_to_date(end_dt, days=1)

	if _is_whole_day_window(start_dt, end_dt):
		return {}

	checkin_window_start = add_to_date(
		start_dt,
		minutes=-(shift_type_doc.begin_check_in_before_shift_start_time or 0),
	) if start_dt else None
	checkout_window_end = add_to_date(
		end_dt,
		minutes=(shift_type_doc.allow_check_out_after_shift_end_time or 0),
	) if end_dt else None
	# A flexible start lets the employee arrive any time up to latest_start and
	# then owe the full shift length from arrival; lateness counts from there.
	flexible_minutes = max(0, int(getattr(shift_type_doc, "flexible_start_minutes", 0) or 0)) if start_dt else 0
	latest_start = add_to_date(start_dt, minutes=flexible_minutes) if start_dt else None
	late_after = add_to_date(latest_start, minutes=(shift_type_doc.late_entry_grace_period or 0)) if start_dt else None
	early_before = add_to_date(end_dt, minutes=-(shift_type_doc.early_exit_grace_period or 0)) if end_dt else None

	return {
		"expected_start": start_dt,
		"expected_end": end_dt,
		"flexible_start_minutes": flexible_minutes,
		"latest_start": latest_start,
		"early_exit_grace_period": shift_type_doc.early_exit_grace_period or 0,
		"checkin_window_start": checkin_window_start,
		"checkout_window_end": checkout_window_end,
		"late_after": late_after,
		"early_before": early_before,
		"enable_late_entry_marking": shift_type_doc.enable_late_entry_marking,
		"enable_early_exit_marking": shift_type_doc.enable_early_exit_marking,
	}


def summarize_schedule_status(policy, reference_time=None, last_log_type=None):
	reference_time = get_datetime(reference_time) if reference_time else get_datetime()
	expected_start = policy.get("expected_start")
	expected_end = policy.get("expected_end")
	checkin_window_start = policy.get("checkin_window_start") or expected_start
	checkout_window_end = policy.get("checkout_window_end") or expected_end

	if not expected_start or not expected_end:
		return {
			"code": "unscheduled",
			"label": "No scheduled shift / لا توجد وردية مجدولة",
			"minutes_until_start": None,
			"minutes_until_end": None,
		}

	minutes_until_start = max(0, int((expected_start - reference_time).total_seconds() // 60))
	minutes_until_end = max(0, int((expected_end - reference_time).total_seconds() // 60))

	if checkin_window_start and reference_time < checkin_window_start:
		code = "before_checkin_window"
		label = "Before check-in window / قبل نافذة الحضور"
	elif reference_time < expected_start:
		code = "checkin_window_open"
		label = "Check-in window open / نافذة الحضور مفتوحة"
	elif reference_time < expected_end:
		code = "shift_in_progress"
		if last_log_type == "OUT":
			label = "Checked out before shift end / تم الانصراف قبل نهاية الوردية"
		else:
			label = "Shift in progress / الوردية جارية"
	elif checkout_window_end and reference_time <= checkout_window_end:
		code = "checkout_window_open"
		label = "Checkout window open / نافذة الانصراف مفتوحة"
	else:
		code = "shift_closed"
		label = "Shift closed / الوردية مغلقة"

	return {
		"code": code,
		"label": label,
		"minutes_until_start": minutes_until_start,
		"minutes_until_end": minutes_until_end,
	}


def resolve_mobile_attendance_policy(employee, attendance_date, location=None):
	attendance_date = getdate(attendance_date)
	assignment = _get_shift_assignment(employee, attendance_date)
	shift_type_name = assignment.shift_type if assignment else None
	policy_source = "Saudi Shift Assignment"

	if not shift_type_name and location:
		shift_type_name = location.get("default_shift_type")
		policy_source = "Attendance Location"

	shift_type_doc = _get_shift_type(shift_type_name)
	window = _build_schedule_window(attendance_date, shift_type_doc)

	voice_policy = (location or {}).get("voice_verification_policy") or VOICE_POLICY_DISABLED
	voice_ttl = int((location or {}).get("voice_challenge_ttl_seconds") or 300)
	voice_max_duration = int((location or {}).get("voice_max_duration_seconds") or 15)

	return {
		"policy_source": policy_source if shift_type_doc else "Contract Hours",
		"shift_assignment": assignment.name if assignment else None,
		"shift_type": shift_type_doc.name if shift_type_doc else None,
		"expected_start": window.get("expected_start"),
		"expected_end": window.get("expected_end"),
		"flexible_start_minutes": window.get("flexible_start_minutes") or 0,
		"latest_start": window.get("latest_start"),
		"early_exit_grace_period": window.get("early_exit_grace_period") or 0,
		"checkin_window_start": window.get("checkin_window_start"),
		"checkout_window_end": window.get("checkout_window_end"),
		"late_after": window.get("late_after"),
		"early_before": window.get("early_before"),
		"enable_late_entry_marking": window.get("enable_late_entry_marking"),
		"enable_early_exit_marking": window.get("enable_early_exit_marking"),
		"enforce_schedule": int((location or {}).get("enforce_schedule") or 0),
		"voice_policy": voice_policy,
		"voice_challenge_ttl_seconds": max(30, voice_ttl),
		"voice_max_duration_seconds": max(5, voice_max_duration),
	}


def flexible_expected_end(policy, in_time=None):
	"""When the day's shift ends for someone who came in at ``in_time``.

	A fixed shift always ends at its end time.  A flexible one ends a full
	shift length after arrival, counted from no earlier than the start time and
	no later than the latest start, so coming at 09:00 on an 8-4 shift with an
	hour of flexibility means leaving at 17:00.  Without the arrival time the
	plain end time is used, which never marks anyone early wrongly.
	"""
	expected_start = policy.get("expected_start")
	expected_end = policy.get("expected_end")
	latest_start = policy.get("latest_start")
	if not (in_time and expected_start and expected_end and latest_start and latest_start > expected_start):
		return expected_end
	in_time = get_datetime(in_time)
	anchor = min(max(in_time, expected_start), latest_start)
	return expected_end + (anchor - expected_start)


def calculate_attendance_variance(log_type, event_time, policy, in_time=None):
	"""Late or early-leave minutes for one punch against the shift.

	``in_time`` is the day's check-in, used on a check-out to find where a
	flexible shift ends; a fixed shift does not need it.
	"""
	late_minutes = 0
	early_exit_minutes = 0
	event_time = get_datetime(event_time) if event_time else event_time
	late_base = policy.get("latest_start") or policy.get("expected_start")

	if log_type == "IN" and late_base and event_time > late_base:
		late_minutes = max(0, int((event_time - late_base).total_seconds() // 60))
		if policy.get("late_after") and event_time <= policy["late_after"]:
			late_minutes = 0

	if not policy.get("enable_late_entry_marking", 1):
		late_minutes = 0

	expected_end = flexible_expected_end(policy, in_time)
	early_before = policy.get("early_before")
	if expected_end and expected_end != policy.get("expected_end"):
		early_before = add_to_date(expected_end, minutes=-int(policy.get("early_exit_grace_period") or 0))
	if log_type == "OUT" and expected_end and event_time < expected_end:
		early_exit_minutes = max(0, int((expected_end - event_time).total_seconds() // 60))
		if early_before and event_time >= early_before:
			early_exit_minutes = 0

	if not policy.get("enable_early_exit_marking", 1):
		early_exit_minutes = 0

	return {
		"late_minutes": late_minutes,
		"early_exit_minutes": early_exit_minutes,
		"late_entry": 1 if late_minutes > 0 else 0,
		"early_exit": 1 if early_exit_minutes > 0 else 0,
	}


def _attendance_location_for_policy(name):
	"""The fields of an Attendance Location that shape the day's shift."""
	if not name or not frappe.db.exists("DocType", "Attendance Location"):
		return None
	return frappe.db.get_value("Attendance Location", name, ["name", "default_shift_type"], as_dict=True)


def recompute_attendance_variance(employee, from_date, to_date):
	"""Measure each recorded day again against the shift that applies now.

	Lateness is stamped on a day when it is punched, against the shift in
	force then.  After HR corrects a shift (an open shift replaced by a timed
	or flexible one), this brings the recorded days in the window up to date.
	Only submitted days with a check-in are touched; returns how many changed.
	"""
	if not employee:
		return 0
	rows = frappe.get_all(
		"Saudi Daily Attendance",
		filters={
			"employee": employee,
			"docstatus": 1,
			"attendance_date": ["between", [getdate(from_date), getdate(to_date)]],
			"in_time": ["is", "set"],
		},
		fields=[
			"name",
			"attendance_date",
			"in_time",
			"out_time",
			"attendance_location",
			"shift_type",
			"expected_start_time",
			"expected_end_time",
			"late_minutes",
			"early_exit_minutes",
		],
		limit_page_length=0,
	)
	locations = {}
	changed = 0
	for row in rows:
		if row.attendance_location not in locations:
			locations[row.attendance_location] = _attendance_location_for_policy(row.attendance_location)
		policy = resolve_mobile_attendance_policy(employee, row.attendance_date, locations[row.attendance_location])
		in_time = get_datetime(row.in_time)
		in_variance = calculate_attendance_variance("IN", in_time, policy)
		updates = {
			"shift_type": policy.get("shift_type"),
			"expected_start_time": policy.get("expected_start"),
			"expected_end_time": flexible_expected_end(policy, in_time),
			"late_entry": in_variance["late_entry"],
			"late_minutes": in_variance["late_minutes"],
		}
		if row.out_time:
			out_variance = calculate_attendance_variance("OUT", get_datetime(row.out_time), policy, in_time=in_time)
			updates.update(
				{"early_exit": out_variance["early_exit"], "early_exit_minutes": out_variance["early_exit_minutes"]}
			)
		same = (
			cstr(row.shift_type) == cstr(updates["shift_type"])
			and _same_moment(row.expected_start_time, updates["expected_start_time"])
			and _same_moment(row.expected_end_time, updates["expected_end_time"])
			and int(row.late_minutes or 0) == int(updates["late_minutes"] or 0)
			and int(row.early_exit_minutes or 0) == int(updates.get("early_exit_minutes", row.early_exit_minutes) or 0)
		)
		if same:
			continue
		frappe.db.set_value("Saudi Daily Attendance", row.name, updates, update_modified=False)
		changed += 1
	return changed


def _same_moment(left, right):
	if not left and not right:
		return True
	if not left or not right:
		return False
	return get_datetime(left) == get_datetime(right)
