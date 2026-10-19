"""تطبيق قواعد التأمينات المطابقة لبيانات العميل.

- وعاء الاشتراك = الراتب الأساسي + بدل السكن (وليس الأساسي وحده).
- النسبة الثابتة للسعودي 9.75% للموظف و11.75% لصاحب العمل، مع إيقاف جدول
  النظام الجديد حتى لا تُرفع النسبة إلى 10.75% وتخالف مبالغ العميل.
- تقريب المبالغ إلى ريال كامل (التقريب التجاري).

حقول الموظف الجديدة (تحمّل الشركة، النسب المخصّصة) تُنشأ عبر مزامنة الحقول
في دورة migrate، ويقتصر دور هذا الـpatch على ضبط الإعدادات وتصحيح النسب.
Idempotent.
"""

import frappe
from frappe.utils import flt


def execute():
	if not frappe.db.exists("DocType", "Saudi HR Settings"):
		return
	meta = frappe.get_meta("Saudi HR Settings")
	if not meta.has_field("gosi_apply_new_system_schedule"):
		return

	settings = frappe.get_single("Saudi HR Settings")
	changed = False

	if settings.gosi_apply_new_system_schedule:
		settings.gosi_apply_new_system_schedule = 0
		changed = True

	if not flt(settings.gosi_saudi_employee_rate):
		settings.gosi_saudi_employee_rate = 9.75
		changed = True
	if not flt(settings.gosi_saudi_employer_rate):
		settings.gosi_saudi_employer_rate = 11.75
		changed = True

	if changed:
		settings.flags.ignore_permissions = True
		settings.flags.ignore_validate = True
		settings.save()
	frappe.db.commit()
	print("[saudi_hr] applied client GOSI rules (base = basic + housing, flat 9.75%, whole-riyal)")
