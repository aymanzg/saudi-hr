"""إعادة حساب ساعات العمل لأيام الحضور التي صُحّحت ببصمة دخول أو خروج وبقيت
ساعاتها صفرًا، لأن حفظ السجل المعتمد بعد التصحيح لم يكن يحسبها. Idempotent.
"""

import frappe


def execute():
	if not frappe.db.table_exists("Saudi Daily Attendance"):
		return
	frappe.db.sql(
		"""
		UPDATE `tabSaudi Daily Attendance`
		SET working_hours = ROUND(TIMESTAMPDIFF(SECOND, in_time, out_time) / 3600, 2)
		WHERE in_time IS NOT NULL
			AND out_time > in_time
			AND IFNULL(working_hours, 0) = 0
		"""
	)
