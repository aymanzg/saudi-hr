import calendar

import frappe
from frappe.model.document import Document
from frappe.utils import flt

MONTH_MAP = {
    "January / يناير": 1, "February / فبراير": 2, "March / مارس": 3,
    "April / أبريل": 4, "May / مايو": 5, "June / يونيو": 6,
    "July / يوليو": 7, "August / أغسطس": 8, "September / سبتمبر": 9,
    "October / أكتوبر": 10, "November / نوفمبر": 11, "December / ديسمبر": 12
}

DAYS_AR = {
    0: "Monday / الاثنين", 1: "Tuesday / الثلاثاء", 2: "Wednesday / الأربعاء",
    3: "Thursday / الخميس", 4: "Friday / الجمعة", 5: "Saturday / السبت",
    6: "Sunday / الأحد"
}


class MonthlyAttendanceRecord(Document):
    def validate(self):
        self._recalculate_summary()

    def _recalculate_summary(self):
        """Compute summary fields from child attendance_details rows."""
        if not self.attendance_details:
            return

        totals = {
            "total_working_days": 0,
            "actual_present_days": 0,
            "absent_days": 0,
            "late_days": 0,
            "late_minutes_total": 0,
            "overtime_hours_total": 0.0,
            "annual_leave_days": 0,
            "sick_leave_days": 0,
            "maternity_leave_days": 0,
            "special_leave_days": 0,
            "unpaid_leave_days": 0,
            "other_leave_days": 0,
        }

        for row in self.attendance_details:
            # Set day_of_week from date
            if row.attendance_date:
                import datetime
                d = row.attendance_date if isinstance(row.attendance_date, datetime.date) else \
                    datetime.date.fromisoformat(str(row.attendance_date))
                row.day_of_week = DAYS_AR.get(d.weekday(), "")

            day_type = row.day_type or ""
            status = row.status or ""

            if "Working Day" in day_type:
                totals["total_working_days"] += 1

            if "Present" in status:
                totals["actual_present_days"] += 1
            elif "Absent" in status:
                totals["absent_days"] += 1
            elif "Late" in status:
                totals["actual_present_days"] += 1
                totals["late_days"] += 1

            totals["late_minutes_total"] += int(row.late_minutes or 0)
            totals["overtime_hours_total"] += float(row.overtime_hours or 0)

            if "Annual Leave" in day_type:
                totals["annual_leave_days"] += 1
            elif "Sick Leave" in day_type:
                totals["sick_leave_days"] += 1
            elif "Maternity Leave" in day_type:
                totals["maternity_leave_days"] += 1
            elif "Special Leave" in day_type:
                totals["special_leave_days"] += 1
            elif "Unpaid Leave" in day_type:
                totals["unpaid_leave_days"] += 1

        for field, val in totals.items():
            self.set(field, val)


WORKING_DAY = "Working Day / يوم عمل"
PUBLIC_HOLIDAY = "Public Holiday / عطلة رسمية"
WEEKLY_OFF_TYPES = {4: "Friday / الجمعة", 5: "Saturday / السبت"}
STANDARD_HOURS = 8.0

# The leave label from admin_api._leave_dates mapped to this doctype's day_type
# options.  The registry's generic labels (Mobile, Emergency) have no day_type
# of their own, so they land under "Special Leave" rather than being counted as
# a working day.
LEAVE_DAY_TYPES = (
    ("annual", "Annual Leave / إجازة سنوية"),
    ("sick", "Sick Leave / إجازة مرضية"),
    ("maternity", "Maternity Leave / إجازة أمومة"),
    ("paternity", "Maternity Leave / إجازة أمومة"),
    ("special", "Special Leave / إجازة خاصة"),
    ("unpaid", "Unpaid Leave / إجازة بدون راتب"),
)
DEFAULT_LEAVE_DAY_TYPE = "Special Leave / إجازة خاصة"


def _leave_day_type(label):
    text = (label or "").lower()
    for needle, day_type in LEAVE_DAY_TYPES:
        if needle in text:
            return day_type
    return DEFAULT_LEAVE_DAY_TYPE


def _monthly_status_and_type(view, day):
    """Map one admin_api day view onto this doctype's status/day_type options.

    The engine's ``status_key`` is the same vocabulary the admin portal uses, so
    translating it here (rather than re-deriving attendance) keeps the monthly
    record, the report grid and the daily board telling the same story.
    """
    key = view.get("status_key")

    if key == "on_leave":
        return "Leave / إجازة", _leave_day_type(view.get("reason") or view.get("status"))
    if key == "weekly_off":
        return "Holiday / عطلة", WEEKLY_OFF_TYPES.get(day.weekday(), PUBLIC_HOLIDAY)
    if key == "holiday":
        return "Holiday / عطلة", PUBLIC_HOLIDAY
    if key == "half_day":
        return "Half Day / نصف يوم", WORKING_DAY
    if key in ("present", "in_progress") or (key in (None, "other") and view.get("in_time")):
        if flt(view.get("late_minutes")):
            return "Late / متأخر", WORKING_DAY
        return "Present / حاضر", WORKING_DAY
    if view.get("future"):
        # a day that has not happened yet is not a present and not an absence
        return None, WORKING_DAY
    return "Absent / غائب", WORKING_DAY


def _calendar_day(day):
    """Fallback for a month generated without an employee: the calendar shape
    only, with no status, so nothing is ever labelled Present by default."""
    if day.weekday() in WEEKLY_OFF_TYPES:
        return "Holiday / عطلة", WEEKLY_OFF_TYPES[day.weekday()]
    return None, WORKING_DAY


@frappe.whitelist()
def get_monthly_days(month_label, year, employee=None):
    """Return a list of days for the given month/year to pre-populate child table.

    Each day is described from the attendance actually on record (daily
    attendance, punches, the employee's holiday list and approved leave), reusing
    the admin portal's day engine so this record cannot disagree with it.  Without
    an employee the calendar is still returned, but no day is claimed Present.
    """
    import datetime

    month_num = MONTH_MAP.get(month_label)
    if not month_num or not year:
        return []

    year = int(year)
    num_days = calendar.monthrange(year, month_num)[1]
    first = datetime.date(year, month_num, 1)
    last = datetime.date(year, month_num, num_days)

    views = {}
    if employee:
        from saudi_hr.saudi_hr.admin_api import _attendance_days

        rows = _attendance_days({"from_date": str(first), "to_date": str(last)}, employee)
        views = {row.get("date"): row for row in rows}

    out = []
    for offset in range(num_days):
        d = first + datetime.timedelta(days=offset)
        key = str(d)
        view = views.get(key)
        if view:
            status, day_type = _monthly_status_and_type(view, d)
            time_in = view.get("in_time")
            time_out = view.get("out_time")
            hours = flt(view.get("hours"))
            late_minutes = int(flt(view.get("late_minutes")))
            overtime = round(max(0.0, hours - STANDARD_HOURS), 2) if (time_in and time_out) else 0
        else:
            status, day_type = _calendar_day(d)
            time_in = time_out = None
            hours = late_minutes = overtime = 0
        out.append({
            "attendance_date": key,
            "day_of_week": DAYS_AR.get(d.weekday(), ""),
            "day_type": day_type,
            "status": status,
            "time_in": time_in,
            "time_out": time_out,
            "hours_worked": hours or None,
            "late_minutes": late_minutes or None,
            "overtime_hours": overtime or None,
        })
    return out
