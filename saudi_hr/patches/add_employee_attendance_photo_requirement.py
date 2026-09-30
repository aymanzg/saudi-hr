import frappe


def execute():
	fieldname = "require_attendance_photo"
	if frappe.db.exists("Custom Field", {"dt": "Employee", "fieldname": fieldname}):
		return

	frappe.get_doc(
		{
			"doctype": "Custom Field",
			"dt": "Employee",
			"fieldname": fieldname,
			"fieldtype": "Check",
			"label": "Require Camera Photo on Mobile Punch / طلب صورة الكاميرا عند الحضور من الجوال",
			"description": "يفرض التقاط صورة من الكاميرا عند تسجيل الحضور من الجوال لهذا الموظف (القيمة الافتراضية: غير مفعّل). Enforces a camera photo at mobile check-in for this employee. Default: off.",
			"default": "0",
			"insert_after": "status",
			"allow_on_submit": 1,
		}
	).insert(ignore_if_duplicate=True, ignore_permissions=True)