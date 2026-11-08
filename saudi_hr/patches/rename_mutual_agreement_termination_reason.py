"""إعادة تسمية سبب الإنهاء في الإشعارات القائمة حتى تبقى مطابقة لخيارات الحقل
ولخرائط المادة النظامية وسبب المكافأة التي تعتمد على النص الكامل. Idempotent.
"""

import frappe

OLD_REASON = "Mutual Agreement / اتفاق مشترك"
NEW_REASON = "Mutual Agreement / انتهاء العقد باتفاق الطرفين"


def execute():
	if not frappe.db.table_exists("Termination Notice"):
		return
	frappe.db.sql(
		"""
		UPDATE `tabTermination Notice`
		SET termination_reason = %s,
			termination_article = REPLACE(termination_article, 'اتفاق مشترك', 'انتهاء العقد باتفاق الطرفين')
		WHERE termination_reason = %s
		""",
		(NEW_REASON, OLD_REASON),
	)
