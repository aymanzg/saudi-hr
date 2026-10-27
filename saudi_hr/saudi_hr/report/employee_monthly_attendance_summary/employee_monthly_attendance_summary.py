"""Employee Monthly Attendance Summary - per employee with summary + details."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate

from saudi_hr.saudi_hr.admin_api import _attendance_days


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.get("employee"):
		frappe.throw(_("Employee is required / يرجى تحديد الموظف"))
	if not filters.get("from_date") or not filters.get("to_date"):
		frappe.throw(_("From Date and To Date are required / يرجى تحديد الفترة"))
	if getdate(filters.from_date) > getdate(filters.to_date):
		frappe.throw(_("From Date cannot be after To Date / تاريخ البداية لا يمكن أن يكون بعد تاريخ النهاية"))

	employee = filters.employee
	emp = frappe.db.get_value(
		"Employee",
		employee,
		["employee_name", "company", "department", "designation", "employee_number"],
		as_dict=True,
	) or {}

	if not filters.get("company") and emp.get("company"):
		filters.company = emp.get("company")
	if not filters.get("department") and emp.get("department"):
		filters.department = emp.get("department")

	views = _attendance_days(
		{"from_date": str(filters.from_date), "to_date": str(filters.to_date)},
		employee,
	)

	columns = get_columns()
	data = []
	summary = {
		"total_days": 0,
		"working_days": 0,
		"present": 0,
		"absent": 0,
		"on_leave": 0,
		"late_days": 0,
		"weekly_off_holiday": 0,
		"total_hours": 0.0,
		"late_minutes": 0,
		"overtime_hours": 0.0,
	}

	for view in views:
		key = view.get("status_key") or ""
		d = getdate(view.get("date"))
		day_name = d.strftime("%A")
		day_name_ar = {
			"Sunday": "الأحد",
			"Monday": "الاثنين",
			"Tuesday": "الثلاثاء",
			"Wednesday": "الأربعاء",
			"Thursday": "الخميس",
			"Friday": "الجمعة",
			"Saturday": "السبت",
		}.get(day_name, day_name)

		late_mins = cint(view.get("late_minutes") or 0)
		early_exit_mins = cint(view.get("early_exit_minutes") or 0)
		hours = flt(view.get("hours") or 0)
		overtime = flt(view.get("overtime_hours") or 0)
		if not overtime and hours and hours > 8:
			overtime = round(hours - 8, 2)

		status_label = view.get("status") or view.get("status_key") or ""
		reason = view.get("reason") or ""

		row = {
			"attendance_date": view.get("date"),
			"day": f"{day_name} / {day_name_ar}",
			"status": status_label,
			"day_type": view.get("day_type") or reason,
			"shift_type": view.get("shift_type") or "",
			"attendance_location": view.get("attendance_location") or "",
			"in_time": view.get("in_time") or "",
			"out_time": view.get("out_time") or "",
			"worked_hours": hours or 0,
			"late_minutes": late_mins or 0,
			"early_exit_minutes": early_exit_mins or 0,
			"overtime_hours": overtime or 0,
			"leave_type": reason if key == "on_leave" else "",
			"remarks": view.get("remarks") or reason or "",
		}
		data.append(row)

		summary["total_days"] += 1
		if key in ("weekly_off", "holiday"):
			summary["weekly_off_holiday"] += 1
			continue
		if key == "on_leave":
			summary["on_leave"] += 1
			if hours:
				summary["total_hours"] += hours
			if overtime:
				summary["overtime_hours"] += overtime
			continue
		summary["working_days"] += 1
		if key in ("present", "in_progress"):
			summary["present"] += 1
			if late_mins > 0:
				summary["late_days"] += 1
		elif key == "missing" and not view.get("future"):
			summary["absent"] += 1
		elif late_mins > 0 and key not in ("weekly_off", "holiday"):
			summary["late_days"] += 1
		summary["total_hours"] += hours
		summary["late_minutes"] += late_mins
		summary["overtime_hours"] += overtime

	chart = None
	report_summary = [
		{"label": _("Employee / الموظف"), "value": f"{emp.get('employee_name') or employee} ({employee})", "indicator": "blue"},
		{"label": _("Company / الشركة"), "value": emp.get("company") or filters.get("company") or "-", "indicator": "blue"},
		{"label": _("Department / القسم"), "value": emp.get("department") or filters.get("department") or "-", "indicator": "blue"},
		{"label": _("Period / الفترة"), "value": f"{filters.from_date} - {filters.to_date}", "indicator": "blue"},
		{"label": _("Total Days / إجمالي الأيام"), "value": summary["total_days"], "indicator": "gray"},
		{"label": _("Working Days / أيام العمل"), "value": summary["working_days"], "indicator": "gray"},
		{"label": _("Present / الحضور"), "value": summary["present"], "indicator": "green"},
		{"label": _("Absent / الغياب"), "value": summary["absent"], "indicator": "red"},
		{"label": _("On Leave / في إجازة"), "value": summary["on_leave"], "indicator": "orange"},
		{"label": _("Late Days / أيام التأخر"), "value": summary["late_days"], "indicator": "orange"},
		{"label": _("Weekly Off / Holiday / عطلة أسبوعية/رسمية"), "value": summary["weekly_off_holiday"], "indicator": "gray"},
		{"label": _("Total Hours / إجمالي الساعات"), "value": round(flt(summary["total_hours"]), 2), "indicator": "blue"},
		{"label": _("Late Minutes / دقائق التأخر"), "value": summary["late_minutes"], "indicator": "orange"},
		{"label": _("Overtime Hours / ساعات إضافية"), "value": round(flt(summary["overtime_hours"]), 2), "indicator": "green"},
	]

	return columns, data, None, chart, report_summary


def get_columns():
	return [
		{"fieldname": "attendance_date", "label": _("Date / التاريخ"), "fieldtype": "Date", "width": 110},
		{"fieldname": "day", "label": _("Day / اليوم"), "fieldtype": "Data", "width": 140},
		{"fieldname": "status", "label": _("Status / الحالة"), "fieldtype": "Data", "width": 150},
		{"fieldname": "day_type", "label": _("Day Type / نوع اليوم"), "fieldtype": "Data", "width": 160},
		{"fieldname": "shift_type", "label": _("Shift / الوردية"), "fieldtype": "Link", "options": "Saudi Shift Type", "width": 130},
		{"fieldname": "attendance_location", "label": _("Location / الموقع"), "fieldtype": "Link", "options": "Attendance Location", "width": 150},
		{"fieldname": "in_time", "label": _("In Time / دخول"), "fieldtype": "Time", "width": 100},
		{"fieldname": "out_time", "label": _("Out Time / خروج"), "fieldtype": "Time", "width": 100},
		{"fieldname": "worked_hours", "label": _("Worked Hours / ساعات العمل"), "fieldtype": "Float", "width": 130},
		{"fieldname": "late_minutes", "label": _("Late Min / دقائق التأخر"), "fieldtype": "Int", "width": 120},
		{"fieldname": "early_exit_minutes", "label": _("Early Exit / الخروج المبكر"), "fieldtype": "Int", "width": 130},
		{"fieldname": "overtime_hours", "label": _("Overtime / إضافي"), "fieldtype": "Float", "width": 110},
		{"fieldname": "leave_type", "label": _("Leave Type / نوع الإجازة"), "fieldtype": "Data", "width": 160},
		{"fieldname": "remarks", "label": _("Remarks / ملاحظات"), "fieldtype": "Data", "width": 200},
	]
