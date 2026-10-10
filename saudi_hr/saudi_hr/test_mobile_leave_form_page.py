"""The mobile leave form, rendered.

Emergency leave and punch correction are rules the employee has to be able to
see before they submit, so the page is checked for the fields, the hints and
the request type that make those rules legible.
"""

import os
import re

import frappe
from frappe.tests.utils import FrappeTestCase

from saudi_hr.saudi_hr.test_support import make_qa_employee


def render_page(user="Administrator"):
	"""Render the real template through the real context controller."""
	import importlib

	from frappe.utils.jinja import get_jenv

	module = importlib.import_module("saudi_hr.www.mobile_attendance")
	ctx = frappe._dict()
	ctx._context_dict = ctx
	module.get_context(ctx)
	ctx["base_template_path"] = "templates/base.html"
	ctx["boot"] = frappe._dict(lang=ctx.get("lang_code", "ar"), sitename=frappe.local.site, user=user)
	# the values a real TemplatePage render would set (see set_page_properties / set_missing_values)
	ctx["path"] = "/mobile-attendance"
	ctx["route"] = "mobile-attendance"
	ctx["pathname"] = "/mobile-attendance"
	ctx["name"] = "mobile-attendance"
	ctx.setdefault("title", "Mobile Attendance")
	template_path = os.path.join(frappe.get_app_path("saudi_hr"), "www", "mobile-attendance.html")
	return get_jenv().get_template("/www/mobile-attendance.html").render(**ctx), ctx


def page_js(html):
	return html


def page_source():
	with open(
		os.path.join(frappe.get_app_path("saudi_hr"), "www", "mobile-attendance.html")
	) as handle:
		return handle.read()


class TestMobileLeaveFormPage(FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.company = frappe.get_all("Company", pluck="name", limit_page_length=1)[0]
		self.employee = make_qa_employee(self.company, f"page-{frappe.generate_hash(length=6)}")
		self.employee_email = frappe.db.get_value("Employee", self.employee, "user_id")
		frappe.set_user(self.employee_email)
		try:
			self.html, self.ctx = render_page(self.employee_email)
		finally:
			frappe.set_user("Administrator")

	def test_the_form_offers_the_new_request_types(self):
		self.assertIn('value="emergency_leave"', self.html)
		self.assertNotIn('<option value="punch_correction"', self.html)
		self.assertIn('id="panel-punch-correction"', self.html)
		self.assertIn("pickNewRequest('punch-correction')", self.html)
		self.assertNotIn("navigate('punch-correction')", self.html)

	def test_punch_correction_is_one_of_the_new_request_choices(self):
		"""The correction is offered in the same 'new request' list as leave and
		service, not as a separate action outside that list."""
		self.assertIn('id="new-request-modal"', self.html)
		self.assertIn("pickNewRequest('leave')", self.html)
		self.assertIn("pickNewRequest('service')", self.html)
		self.assertIn("pickNewRequest('punch-correction')", self.html)

	def test_the_emergency_leave_fields_are_present(self):
		self.assertIn('id="leave-emergency-field"', self.html)
		self.assertIn('id="leave-emergency-balance"', self.html)
		self.assertIn('id="leave-emergency-warning"', self.html)

	def test_the_correction_shows_the_recorded_check_in_and_check_out(self):
		"""The form shows the punches it would correct instead of asking for trust."""
		self.assertIn('id="punch-current-time"', self.html)
		self.assertIn('id="punch-corrected-time"', self.html)
		self.assertIn('id="punch-current-out-time"', self.html)
		self.assertIn('id="punch-corrected-out-time"', self.html)
		self.assertIn('id="punch-correction-warning"', self.html)

	def test_the_correction_is_asked_for_one_day_only(self):
		"""A punch correction is one day, so the correction form has no end date."""
		self.assertIn('id="punch-correction-date"', self.html)
		self.assertIn("end_date: date", self.html)
		self.assertNotIn('value="punch_correction"', self.html)

	def test_two_buttons_choose_the_punch_to_correct(self):
		"""IN and OUT are offered as buttons; only the chosen punch is editable."""
		self.assertIn('id="punch-target-in"', self.html)
		self.assertIn('id="punch-target-out"', self.html)
		self.assertIn("selectPunchTarget('IN')", self.html)
		self.assertIn("selectPunchTarget('OUT')", self.html)
		self.assertIn('id="punch-in-field"', self.html)
		self.assertIn('id="punch-out-field"', self.html)
		self.assertIn("punchTarget === \"IN\"", self.html)
		self.assertIn("punchTarget === \"OUT\"", self.html)

	def test_the_dates_the_form_asks_for_are_rechecked_on_change(self):
		self.assertIn("function onLeaveDatesChanged()", self.html)
		self.assertIn("refreshEmergencyAvailability", self.html)
		self.assertIn("refreshPunchContext", self.html)

	def test_the_hints_are_filled_from_the_server_not_hardcoded(self):
		self.assertIn("get_emergency_leave_availability", self.html)
		self.assertIn("get_punch_correction_context", self.html)

	def test_the_rendered_page_leaks_no_jinja(self):
		body = self.html.split("</head>", 1)[-1]
		self.assertNotIn("{{ ", body)
		self.assertNotIn("{{\n", body)
		self.assertNotIn("{% ", body)
		self.assertNotIn("{%\n", body)
		self.assertNotIn("Traceback", self.html)

	def test_the_submit_path_sends_the_corrected_times(self):
		self.assertIn("args.corrected_time = correctedTime;", self.html)
		self.assertIn("args.corrected_out_time = correctedOutTime;", self.html)
		self.assertIn("correctedTime = document.getElementById(\"punch-corrected-time\").value", self.html)
		self.assertIn("correctedOutTime = document.getElementById(\"punch-corrected-out-time\").value", self.html)

	def test_every_new_label_exists_in_both_languages(self):
		shared = open(
			os.path.join(frappe.get_app_path("saudi_hr"), "public", "js", "saudi_portal.js")
		).read()
		search_space = self.html + "\n" + self.js if hasattr(self, "js") else self.html
		alt = "|".join((
			"leave_emergency", "leave_punch_correction", "emergency_balance",
			"emergency_remaining", "emergency_gate_warning", "emergency_quota_warning",
			"emergency_days_short", "current_checkin", "current_checkout", "no_checkin_found",
			"corrected_time_label", "corrected_out_time_label", "corrected_time_required",
			"future_date_not_allowed",
		))
		keys = {
			group0 or group1
			for group0, group1 in re.findall(
				r't\("(%s)"\)|data-i18n-key="(%s)"' % (alt, alt), search_space
			)
		}
		self.assertEqual(len(keys), 14, sorted(keys))
		for key in keys:
			self.assertEqual(shared.count(f"{key}:"), 2, f"{key} needs an ar and an en label")

	def test_the_hint_style_exists_in_the_shared_stylesheet(self):
		css = open(
			os.path.join(frappe.get_app_path("saudi_hr"), "public", "css", "saudi_portal.css")
		).read()
		self.assertIn(".saudi-hint", css)
		self.assertIn(".saudi-hint--blocked", css)