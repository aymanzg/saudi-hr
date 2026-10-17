"""Zero early-exit and start-less late flags produced by open (00:00-23:59) shifts.

Before the schedule-window fix, a shift stored as 00:00-23:59 was treated as
scheduled, so every normal punch read as an early exit (minutes until 23:59)
and, when the start was midnight or unset, as late (minutes since midnight).
Those flags are not lateness or early exit at all, and would feed a bogus late
deduction once payroll deducts late hours, so they are cleared once here. Only
the wrong flags are touched: a late flag with no recorded start, and an early
flag measured against a whole-day or missing end. Idempotent.
"""

import frappe


def execute():
	if not frappe.db.table_exists("Saudi Daily Attendance"):
		return

	# An early exit measured against a whole-day (23:00+) or missing end is not early.
	early = frappe.db.sql(
		"""
		UPDATE `tabSaudi Daily Attendance`
		SET early_exit = 0, early_exit_minutes = 0
		WHERE early_exit = 1
			AND (expected_end_time IS NULL OR TIME(expected_end_time) >= '23:00:00')
		"""
	)

	# Late with no recorded start is just time-since-midnight, not lateness.
	late = frappe.db.sql(
		"""
		UPDATE `tabSaudi Daily Attendance`
		SET late_entry = 0, late_minutes = 0
		WHERE late_entry = 1
			AND expected_start_time IS NULL
		"""
	)

	frappe.db.commit()
	print(
		f"[saudi_hr] cleared {len(early) if early else 0} open-shift early-exit flag(s) "
		f"and {len(late) if late else 0} start-less late flag(s)"
	)
