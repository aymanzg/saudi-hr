"""Official HR documents, issued as a PDF on company letterhead.

An employee requests one, or HR issues it without a request. No approval chain runs:
HR prints the letter, has it signed by hand, then uploads it or hands it over.

Details come from the employee's own record, so nothing is typed in except what only
the request can know (who a letter is addressed to). Issued PDFs are read past the
payroll and contract permissions employees lack, so download_hr_document is the only
way out, and it decides who may have each one.
"""

import os
import re
import shutil
import subprocess
import tempfile

import frappe
from frappe import _
from frappe.model.workflow import apply_workflow
from frappe.utils import cint, flt, format_date, getdate, scrub_urls, today
from num2words import num2words

from saudi_hr.saudi_hr.utils import get_employee_salary_components
from saudi_hr.saudi_hr.workflow_catalogue import ISSUE_ACTION

# The keys match workflow_catalogue.HR_ISSUED_REQUEST_TYPES, which routes these past the chain
HR_DOCUMENTS = {
	"salary_certificate": {"title": "تعريف راتب"},
	"employment_letter": {"title": "خطاب مشهد وظيفي"},
	"addressed_letter": {"title": "خطاب موجه إلى جهة"},
	"experience_certificate": {"title": "شهادة خبرة", "needs_end_date": True},
	"employee_clearance": {"title": "إخلاء طرف", "needs_end_date": True},
}

# Trial: HR prints, signs and uploads the letter, and employees do not get it from the system yet
EMPLOYEE_CAN_DOWNLOAD = False
ISSUED_STATES = ("GM Approved", "Completed", "Approved")
AWAITING_ISSUE_STATE = "Pending HR Review"
DOCUMENT_READER_ROLES = {"HR User", "HR Manager", "System Manager"}
SIGNED_COPY_EXTENSIONS = (".pdf", ".jpg", ".jpeg", ".png")
ID_LABELS = {"National ID": "الهوية الوطنية", "Iqama": "هوية مقيم"}
EMPLOYEE_FIELDS = [
	"name",
	"employee_name",
	"company",
	"gender",
	"designation",
	"date_of_joining",
	"relieving_date",
	"user_id",
	"custom_id_number",
	"custom_id_type",
	"custom_nationality",
	"custom_company_name",
]

MALE_WORDING = {
	"title": "السيد",
	"employee": "الموظف",
	"works": "يعمل",
	"worked": "عمل",
	"holds": "يحمل",
	"holder": "حامل",
	"stays": "يزال",
	"earns": "يتقاضى",
	"his": "ه",
	"held": "كان يشغل",
	"named": "المذكور",
	"known": "عُرف",
	"has": "يتمتع",
	"testified": "له",
	"did": "قام",
	"settled": "استوفى",
	"given": "أُعطي",
}
FEMALE_WORDING = {
	"title": "السيدة",
	"employee": "الموظفة",
	"works": "تعمل",
	"worked": "عملت",
	"holds": "تحمل",
	"holder": "حاملة",
	"stays": "تزال",
	"earns": "تتقاضى",
	"his": "ها",
	"held": "كانت تشغل",
	"named": "المذكورة",
	"known": "عُرفت",
	"has": "تتمتع",
	"testified": "لها",
	"did": "قامت",
	"settled": "استوفت",
	"given": "أُعطيت",
}


def is_document_ready(request_type, workflow_state):
	return request_type in HR_DOCUMENTS and workflow_state in ISSUED_STATES


def employee_can_download(request_type, workflow_state):
	return EMPLOYEE_CAN_DOWNLOAD and is_document_ready(request_type, workflow_state)


def is_document_officer():
	return bool(DOCUMENT_READER_ROLES.intersection(frappe.get_roles()))


def can_issue_document(request_type, workflow_state):
	return request_type in HR_DOCUMENTS and workflow_state == AWAITING_ISSUE_STATE and is_document_officer()


def assert_document_can_be_requested(employee, request_type, addressed_to=None, letter_subject=None, letter_purpose=None):
	"""Refuse now, with the reason, rather than leave a request that can never print."""
	if request_type == "addressed_letter" and not all(
		(value or "").strip() for value in (addressed_to, letter_subject, letter_purpose)
	):
		frappe.throw(_("يرجى إدخال اسم الجهة وموضوع الخطاب والغرض منه."))
	_assert_employee_data(_employee_row(employee), request_type)


def issue_requested_document(name):
	"""Issue a letter an employee asked for. Refused on the issuer's own request, as any
	approval is, so nobody signs off their own salary letter."""
	_assert_document_officer()
	request = frappe.get_doc("HR Service Request", name)
	if request.request_type not in HR_DOCUMENTS:
		frappe.throw(_("لا يوجد نموذج لهذا الطلب."))
	_assert_employee_data(_employee_row(request.employee), request.request_type)
	return apply_workflow(request, ISSUE_ACTION)


def issue_unrequested_document(employee, request_type, addressed_to=None, letter_subject=None, letter_purpose=None):
	"""Issue a letter nobody requested. It still gets a numbered request, so every letter
	that leaves HR can be traced. The workflow has no Draft to Completed transition, so
	the row is written straight, as admin_api.issue_hr_document does for its auto types."""
	_assert_document_officer()
	frappe.has_permission("Employee", "read", doc=employee, throw=True)
	assert_document_can_be_requested(employee, request_type, addressed_to, letter_subject, letter_purpose)
	request = frappe.get_doc(
		{
			"doctype": "HR Service Request",
			"employee": employee,
			"request_type": request_type,
			"addressed_to": addressed_to,
			"letter_subject": letter_subject,
			"letter_purpose": letter_purpose,
		}
	).insert()
	values = {"workflow_state": "Completed", "docstatus": 1, "issued_on": today()}
	frappe.db.set_value(request.doctype, request.name, values)
	request.update(values)
	return request


def save_signed_document(name, file_url):
	"""Record the signed scan. The file stays private and attached to nothing, so only
	download_signed_document can serve it, never the employee's own view of the request."""
	_assert_document_officer()
	request = frappe.get_doc("HR Service Request", name)
	frappe.has_permission("HR Service Request", "read", doc=request, throw=True)
	if not is_document_ready(request.request_type, request.workflow_state):
		frappe.throw(_("لا يمكن رفع النسخة الموقعة قبل إصدار الخطاب."))
	if not (file_url or "").lower().endswith(SIGNED_COPY_EXTENSIONS):
		frappe.throw(_("يرجى رفع النسخة الموقعة بصيغة PDF أو صورة."))
	if not frappe.db.exists("File", {"file_url": file_url, "is_private": 1, "owner": frappe.session.user}):
		frappe.throw(_("تعذر العثور على الملف المرفوع."))
	frappe.db.set_value(request.doctype, request.name, "signed_document", file_url)


@frappe.whitelist()
def download_signed_document(name):
	_assert_document_officer()
	request = frappe.get_doc("HR Service Request", name)
	frappe.has_permission("HR Service Request", "read", doc=request, throw=True)
	if not request.signed_document:
		frappe.throw(_("لم تُرفع نسخة موقعة لهذا الخطاب."))
	file = frappe.get_doc("File", {"file_url": request.signed_document})
	frappe.local.response.filename = f"{request.name}-signed{os.path.splitext(file.file_name)[1]}"
	frappe.local.response.filecontent = file.get_content()
	frappe.local.response.type = "download"


@frappe.whitelist()
def download_hr_document(name):
	request = frappe.get_doc("HR Service Request", name)
	if request.request_type not in HR_DOCUMENTS:
		frappe.throw(_("لا يوجد نموذج لهذا الطلب."))

	employee = _employee_row(request.employee)
	_assert_can_download(request, employee)
	if not is_document_ready(request.request_type, request.workflow_state):
		frappe.throw(_("لم يتم إصدار هذه الوثيقة بعد."))

	frappe.local.response.filename = f"{request.name}.pdf"
	frappe.local.response.filecontent = render_hr_document(request, employee)
	frappe.local.response.type = "pdf"


def render_hr_document(request, employee=None):
	employee = employee or _employee_row(request.employee)
	_assert_employee_data(employee, request.request_type)
	html = frappe.render_template(
		"templates/hr_documents/hr_document.html", _document_context(request, employee)
	)
	return _html_to_pdf(html)


def _html_to_pdf(html):
	"""Print with headless Chrome: the bench's wkhtmltopdf clips Arabic lines instead of
	wrapping them and has no page footers."""
	chrome = _chrome_binary()
	if not chrome:
		frappe.throw(_("تعذر إنشاء ملف PDF: متصفح Chrome غير مثبت على الخادم."))

	with tempfile.TemporaryDirectory(prefix="saudi-hr-document-") as folder:
		source = os.path.join(folder, "document.html")
		target = os.path.join(folder, "document.pdf")
		with open(source, "w", encoding="utf-8") as file:
			file.write(scrub_urls(html))
		subprocess.run(
			[
				chrome,
				"--headless",
				"--no-sandbox",
				"--disable-gpu",
				"--disable-dev-shm-usage",
				"--disable-javascript",
				"--no-pdf-header-footer",
				f"--user-data-dir={os.path.join(folder, 'profile')}",
				f"--print-to-pdf={target}",
				f"file://{source}",
			],
			check=True,
			capture_output=True,
			timeout=60,
		)
		with open(target, "rb") as file:
			return file.read()


def _chrome_binary():
	bench_chrome = os.path.abspath(os.path.join(frappe.utils.get_bench_path(), "chromium", "chrome-linux", "headless_shell"))
	if os.path.exists(bench_chrome):
		return bench_chrome
	return next(filter(None, map(shutil.which, ("google-chrome", "chromium", "chromium-browser"))), None)


def _assert_can_download(request, employee):
	if EMPLOYEE_CAN_DOWNLOAD and employee.user_id and employee.user_id == frappe.session.user:
		return
	_assert_document_officer()
	frappe.has_permission("HR Service Request", "read", doc=request, throw=True)


def _assert_document_officer():
	if not is_document_officer():
		frappe.throw(_("لا تملك صلاحية إصدار أو تحميل هذه الوثيقة."), frappe.PermissionError)


def _employee_row(employee):
	row = frappe.db.get_value("Employee", employee, EMPLOYEE_FIELDS, as_dict=True)
	if not row:
		frappe.throw(_("لا يوجد سجل لهذا الموظف."))
	return row


def _assert_employee_data(employee, request_type):
	required = {
		"رقم الهوية": employee.custom_id_number,
		"المسمى الوظيفي": employee.designation,
		"تاريخ المباشرة": employee.date_of_joining,
		"الجنسية": employee.custom_nationality,
	}
	if HR_DOCUMENTS[request_type].get("needs_end_date"):
		required["تاريخ انتهاء الخدمة"] = employee.relieving_date
	if request_type == "salary_certificate":
		required["الراتب"] = flt(get_employee_salary_components(employee.name)["total_salary"])

	missing = [label for label, value in required.items() if not value]
	if missing:
		frappe.throw(
			_("لا يمكن إصدار {0}: البيانات التالية غير مسجلة في ملف الموظف: {1}. يرجى مراجعة الموارد البشرية.").format(
				HR_DOCUMENTS[request_type]["title"], "، ".join(missing)
			)
		)


def _document_context(request, employee):
	company = employee.company
	issue_date = request.get("issued_on") or getdate(request.modified)
	context = {
		"request": request,
		"document_type": request.request_type,
		"document_title": HR_DOCUMENTS[request.request_type]["title"],
		"employee": employee,
		"w": FEMALE_WORDING if employee.gender == "Female" else MALE_WORDING,
		"company_name": employee.custom_company_name or company,
		"id_label": ID_LABELS.get(employee.custom_id_type, "الهوية"),
		"issue_date": _date(issue_date),
		"issue_date_hijri": _hijri_date(issue_date),
		"joining_date": _date(employee.date_of_joining),
		"end_date": _date(employee.relieving_date) if employee.relieving_date else "",
		"addressed_to": request.get("addressed_to") or request.description or "",
		"letter_subject": request.get("letter_subject") or "",
		"letter_purpose": request.get("letter_purpose") or "",
	}
	context.update(_letter_head(company))
	if request.request_type == "salary_certificate":
		context["salary"] = _salary_lines(employee.name)
	return context


def _letter_head(company):
	name = frappe.db.get_value("Company", company, "default_letter_head")
	if not name:
		return {"letter_head": "", "letter_foot": ""}
	head = frappe.db.get_value("Letter Head", name, ["content", "footer", "disabled"], as_dict=True)
	if not head or cint(head.disabled):
		return {"letter_head": "", "letter_foot": ""}
	return {"letter_head": head.content or "", "letter_foot": head.footer or ""}


def _salary_lines(employee):
	salary = get_employee_salary_components(employee)
	lines = [
		("الراتب الأساسي", salary["basic_salary"]),
		("بدل السكن", salary["housing_allowance"]),
		("بدل النقل", salary["transport_allowance"]),
		("بدلات أخرى", salary["other_allowances"]),
	]
	total = flt(salary["total_salary"])
	return {
		"lines": [{"label": label, "amount": _money(amount)} for label, amount in lines if flt(amount)],
		"total": _money(total),
		"total_in_words": _amount_in_words(total),
	}


def _money(amount):
	amount = flt(amount, 2)
	return f"{amount:,.2f}" if amount % 1 else f"{amount:,.0f}"


def _amount_in_words(amount):
	riyals = int(amount)
	halalas = int(round((amount - riyals) * 100))
	words = _arabic_number(riyals) + " ريال سعودي"
	if halalas:
		words += " و" + _arabic_number(halalas) + " هللة"
	return words + " فقط لا غير"


def _arabic_number(number):
	# num2words spaces the conjunction, as in "ستة آلاف و ستمائة"
	return re.sub(r" و ", " و", num2words(number, lang="ar"))


def _date(value):
	return format_date(value, "dd/mm/yyyy") + " م"


def _hijri_date(value):
	from saudi_hr.saudi_hr.enterprise_operations import _hijri_date_str

	return _hijri_date_str(getdate(value))
