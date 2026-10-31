# Copyright (c) 2026, IdeaOrbit and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class EmployeeDocumentCustodyLog(Document):
	pass


@frappe.whitelist()
def bulk_send_documents_to_employees(letter_name=None, letter_title=None, attachment=None, email_body=None, department=None, designation=None, company=None, include_all=True):
	"""Bulk send/store documents/letters to all employees with permission."""
	user = frappe.session.user
	roles = set(frappe.get_roles(user))
	if not ({"System Manager", "HR Manager", "HR User"} & roles):
		frappe.throw(_("Not permitted / غير مصرح"), frappe.PermissionError)
	filters = {"status": "Active"}
	if department:
		filters["department"] = department
	if designation:
		filters["designation"] = designation
	if company:
		filters["company"] = company
	employees = frappe.get_all("Employee", filters=filters, fields=["name", "employee_name", "user_id", "company_email"])
	count = 0
	for emp in employees:
		try:
			doc = frappe.get_doc({
				"doctype": "Employee Document Custody Log",
				"employee": emp.name,
				"employee_name": emp.employee_name,
				"document_type": letter_name or letter_title or "HR Letter / خطاب موارد بشرية",
				"document_name": letter_title or letter_name or "HR Letter",
				"received_by": emp.name,
				"status": "Issued / صادرة",
				"evidence_attachment": attachment,
				"remarks": email_body or "",
			})
			doc.insert(ignore_permissions=True)
			count += 1
		except Exception:
			continue
	frappe.db.commit()
	return {"status": "success", "count": count}
