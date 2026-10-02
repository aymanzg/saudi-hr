"""Tests for the /saudi-admin page, its shell, and its route.

The page is Jinja plus ES5 in a <script> block with no build step, so the only
way to know it is correct is to render it and read the result. These tests
assert the contract the page depends on: it renders for an admin, refuses a
non-admin, loads the shared runtime rather than inlining its own, and offers
only the actions the server authorised.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils.jinja import get_jenv

ADMIN_HTML = "saudi_hr/www/saudi-admin.html"
SHARED_CSS = "/assets/saudi_hr/css/saudi_portal.css"
SHARED_JS = "/assets/saudi_hr/js/saudi_portal.js"


def render_page(user="Administrator", context=None):
	"""Render the real template through the real context controller."""
	import importlib

	module = importlib.import_module("saudi_hr.www.saudi-admin")
	ctx = frappe._dict()
	ctx._context_dict = ctx
	module.get_context(ctx)
	ctx["base_template_path"] = "templates/base.html"
	ctx["boot"] = frappe._dict(lang=ctx.get("lang_code", "ar"), sitename=frappe.local.site, user=user)
	return get_jenv().get_template(ADMIN_HTML).render(**ctx), ctx


def page_source():
	"""The page's own template file, before Jinja runs over it."""
	import os

	with open(template_path()) as handle:
		return handle.read()


def template_path():
	return os.path.join(frappe.get_app_path("saudi_hr"), "www", "saudi-admin.html")


def page_js(html=None):
	"""The page's own <script> block from the rendered page, with the two
	Jinja-seeded values stubbed.

	The base template ships its own bootstrap <script>, so this picks the block
	that actually holds the page's behaviour.
	"""
	html = html if html is not None else render_page()[0]
	blocks = re.findall(r"<script>(.*?)</script>", html, re.S)
	own = [b for b in blocks if "SAUDI_PANEL_LOADERS" in b]
	if not own:
		return ""
	return re.sub(r"\{\{.*?\}\}", "0", own[0], flags=re.S)


class TestAdminPageRender(FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")

	def test_page_renders_for_an_admin(self):
		html, _ctx = render_page()
		self.assertGreater(len(html), 1000)
		self.assertNotIn("Traceback", html)

	def test_rendered_html_has_no_leftover_jinja_from_the_page(self):
		"""The base template legitimately keeps {{ path }} and {{ route }} for
		the Desk bootstrap, but the page body must not leak its own."""
		html, _ctx = render_page()
		# base.html keeps exactly these three for the Desk bootstrap
		allowed = {"{{ path }}", "{{ pathname }}", "{{ route }}"}
		leftovers = set(re.findall(r"\{\{.*?\}\}", html)) - allowed
		self.assertEqual(leftovers, set(), f"unrendered jinja in output: {leftovers}")
		self.assertNotIn("{%", html)

	def test_a_plain_employee_is_redirected_away(self):
		frappe.set_user(self._user_with("Employee"))
		import importlib

		module = importlib.import_module("saudi_hr.www.saudi-admin")
		ctx = frappe._dict()
		ctx._context_dict = ctx
		with self.assertRaises(frappe.Redirect):
			module.get_context(ctx)
		self.assertIn("mobile-attendance", frappe.local.flags.redirect_location)

	def test_guest_is_sent_to_login(self):
		frappe.set_user("Guest")
		import importlib

		module = importlib.import_module("saudi_hr.www.saudi-admin")
		ctx = frappe._dict()
		ctx._context_dict = ctx
		with self.assertRaises(frappe.Redirect):
			module.get_context(ctx)
		self.assertIn("/login", frappe.local.flags.redirect_location)

	def test_context_carries_the_first_paint_numbers(self):
		_html, ctx = render_page()
		self.assertTrue(ctx["can_manage_employees"])
		self.assertIn("admin_roles", ctx)
		self.assertIn("total", ctx["dashboard"]["employees"])
		self.assertIn("actionable_total", ctx["dashboard"])

	def test_a_broken_dashboard_does_not_blank_the_page(self):
		"""A failure here must degrade to an empty frame, since the JS reloads
		the same numbers on boot."""
		from unittest.mock import patch

		import importlib

		from saudi_hr.saudi_hr import admin_api

		module = importlib.import_module("saudi_hr.www.saudi-admin")
		frappe.set_user("Administrator")
		ctx = frappe._dict()
		ctx._context_dict = ctx
		with patch.object(admin_api, "get_admin_dashboard", side_effect=RuntimeError("boom")):
			module.get_context(ctx)
		self.assertEqual(ctx["dashboard"], {})
		self.assertTrue(ctx["can_manage_employees"])

	def test_language_and_direction_follow_the_user(self):
		frappe.set_user("Administrator")
		frappe.db.set_value("User", "Administrator", "language", "en")
		_html, ctx = render_page()
		self.assertEqual(ctx["lang_code"], "en")
		self.assertEqual(ctx["text_direction"], "ltr")
		frappe.db.set_value("User", "Administrator", "language", "ar")

	def _user_with(self, role):
		suffix = frappe.generate_hash(length=8).lower()
		email = f"saudi.page.{suffix}@example.com"
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": f"page{suffix}",
				"new_password": "N7!xP4@qR9#vT2$k",
				"send_welcome_email": 0,
				"roles": [{"role": role}],
			}
		).insert(ignore_permissions=True)
		return email


class TestAdminPageUsesTheSharedRuntime(FrappeTestCase):
	"""Phase 1 exists so the admin page cannot fork the design system."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.html, _ctx = render_page()

	def test_loads_the_shared_stylesheet_and_script(self):
		self.assertIn(SHARED_CSS, self.html)
		self.assertIn(SHARED_JS, self.html)

	def test_does_not_inline_its_own_stylesheet(self):
		"""A <style> block here would be the design system forking again."""
		self.assertNotIn("<style", self.html)

	def test_defines_no_page_functions_the_runtime_also_defines(self):
		shared = open(
			frappe.get_app_path("saudi_hr", "public", "js", "saudi_portal.js")
		).read()
		shared_defs = set(re.findall(r"^function (\w+)", shared, re.M))
		page_defs = set(re.findall(r"^function (\w+)", page_js(self.html), re.M))
		self.assertEqual(
			page_defs & shared_defs, set(), "the page redefines a shared runtime function"
		)

	def test_registers_its_panels_rather_than_hardcoding_them(self):
		js = page_js(self.html)
		for panel in ("dashboard", "approvals", "employees", "report"):
			self.assertIn(f'SAUDI_PANEL_LOADERS["{panel}"]', js, panel)
		self.assertIn("SAUDI_LANG_RENDERERS.push", js)

	def test_calls_only_admin_api_methods(self):
		"""The page must not reach into the employee-scoped API."""
		js = page_js(self.html)
		methods = set(re.findall(r'"saudi_hr\.saudi_hr\.(\w+)\." \+ method', js))
		self.assertEqual(methods, {"admin_api"})
		for forbidden in ("get_self_service_portal", "get_mobile_attendance", "issue_mobile_attendance"):
			self.assertNotIn(forbidden, js)

	def test_all_markup_is_addressed_by_a_registered_panel(self):
		for panel in ("dashboard", "approvals", "employees", "report"):
			self.assertIn(f'id="panel-{panel}"', self.html)

	def test_every_i18n_key_exists_in_both_languages(self):
		shared = open(
			frappe.get_app_path("saudi_hr", "public", "js", "saudi_portal.js")
		).read()
		arabic = set(re.findall(r"^\t\t(\w+):", shared.split("\tar: {")[1].split("\n\t},")[0], re.M))
		english = set(re.findall(r"^\t\t(\w+):", shared.split("\ten: {")[1].split("\n\t}\n")[0], re.M))
		self.assertEqual(arabic, english, "label parity is broken")

		used = set(re.findall(r'data-i18n-key="(\w+)"', self.html))
		used |= set(re.findall(r'(?<![A-Za-z0-9_.])t\("([\w]+)"\)', self.html))
		missing = sorted(key for key in used if key not in arabic)
		self.assertEqual(missing, [], f"page uses labels the runtime does not define: {missing}")
		self.assertGreater(len(used), 40, "the page should be fully translated")

	def test_rail_items_are_data_driven_not_inline_onclick(self):
		"""Inline handlers are not CSP friendly and cannot be delegated."""
		js = page_js(self.html)
		self.assertIn('querySelectorAll(".saudi-rail__item[data-panel]")', js)
		for item in re.findall(r'<button class="saudi-rail__item[^"]*"[^>]*>', self.html):
			if "data-panel" in item:
				self.assertNotIn("onclick", item, item)

	def test_the_page_carries_no_inline_handler_at_all(self):
		"""Every button is bound by the delegated listener instead."""
		self.assertNotIn("onclick", page_source())
		self.assertIn('document.addEventListener("click"', page_js())

	def test_every_data_action_in_the_markup_has_a_binding(self):
		"""An unbound data-action is a button that silently does nothing."""
		js = page_js(self.html)
		bound = set(re.findall(r'case "([\w-]+)":', js))
		for markup in (page_source(), js):
			for action in set(re.findall(r'data-action=[\'"]([\w-]+)[\'"]', markup)):
				self.assertIn(action, bound, f"{action} has no delegated binding")


class TestAdminPageSafety(FrappeTestCase):
	"""The page is a rendering shell, so its escaping and permissions matter."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.html, self.ctx = render_page()
		self.js = page_js(self.html)

	def test_dynamic_text_goes_through_the_escape_helper(self):
		"""Server data is interpolated into innerHTML, so every value must be
		escaped or an employee name could inject markup."""
		self.assertIn("function esc(value)", self.js)
		# no raw interpolation of a row field straight into markup
		for pattern in (r"\+ row\.full_name \+", r"\+ row\.department \+", r"\+ payload\.name \+"):
			self.assertNotRegex(self.js, pattern, pattern)

	def test_the_rendered_page_escapes_the_signed_in_name(self):
		"""Frappe's Jinja environment is not autoescaping, so this must be explicit."""
		self.assertIn("{{ full_name | e }}", page_source())
		html, _ctx = render_page()
		self.assertIn("&lt;", html)

	def test_a_hostile_display_name_cannot_inject_markup(self):
		"""The full name comes from the User record, which HR can edit freely."""
		import importlib

		from frappe.utils.jinja import get_jenv

		module = importlib.import_module("saudi_hr.www.saudi-admin")
		frappe.set_user("Administrator")
		ctx = frappe._dict()
		ctx._context_dict = ctx
		module.get_context(ctx)
		ctx["full_name"] = '<img src=x onerror="alert(1)">'
		ctx["base_template_path"] = "templates/base.html"
		ctx["boot"] = frappe._dict(lang="ar", sitename=frappe.local.site, user="Administrator")
		html = get_jenv().get_template(ADMIN_HTML).render(**ctx)
		self.assertNotIn("<img src=x", html)
		self.assertIn("&lt;img src=x", html)

	def test_the_boolean_flag_is_rendered_as_javascript(self):
		"""A Python True in a JS literal is a parse error that kills the page."""
		self.assertNotRegex(self.html, r":\s*True\b")
		self.assertNotRegex(self.html, r":\s*False\b")
		self.assertRegex(self.html, r"can_manage_employees:\s*(true|false)")

	def test_escape_helper_covers_the_dangerous_characters(self):
		body = self.js[self.js.index("function esc(") : self.js.index("function esc(") + 400]
		for char, entity in (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"), ('"', "&quot;"), ("'", "&#39;")):
			self.assertIn(entity, body, char)

	def test_employee_creation_reads_only_named_controls(self):
		"""The form must not serialise the whole DOM into the payload."""
		self.assertIn('form.querySelectorAll("[name]")', self.js)
		self.assertNotIn("new FormData", self.js)

	def test_add_button_is_hidden_without_create_permission(self):
		self.assertIn('addBtn.hidden = !ADMIN_CFG.can_manage_employees', self.js)
		self.assertIn("can_manage_employees", self.js)

	def test_actions_come_from_the_server_not_from_the_label(self):
		"""A hardcoded approve button would offer an action the API refuses."""
		# the attribute must be assembled from the server-supplied action name
		self.assertRegex(self.js, r"data-action='\"\s*\+\s*esc\(")
		for hardcoded in ("Approve", "Reject", "Cancel", "Submit Request"):
			self.assertNotRegex(self.js, r"data-action=['\"]%s['\"]" % hardcoded, hardcoded)

	def test_approval_detail_reasks_the_server_before_offering_actions(self):
		"""The list can be stale by the time a row is clicked."""
		self.assertIn("get_leave_request", self.js)
		self.assertIn("loadRequestDetail", self.js)

	def test_submit_uses_its_own_endpoint(self):
		self.assertIn("submit_leave_request", self.js)
		self.assertIn('action === "submit"', self.js)

	def test_no_hardcoded_admin_endpoints(self):
		"""The page must not call the API directly, only through callAdmin."""
		self.assertEqual(self.js.count("frappe.call"), 1)
		self.assertIn("function callAdmin(", self.js)

	def test_reads_are_sent_as_get_and_writes_as_post(self):
		"""Frappe rejects a mismatched verb with 'Not permitted'.

		The server declares reads as methods=["GET"], so posting them would fail
		every list, detail and dashboard call.
		"""
		self.assertIn('ADMIN_WRITES[method] ? "POST" : "GET"', self.js)
		for method in ("create_employee", "apply_leave_action", "submit_leave_request"):
			self.assertIn(method, self.js, method)

	def test_the_write_set_matches_the_server(self):
		"""Every POST-only endpoint must be listed, or its call is refused."""
		from saudi_hr.saudi_hr import admin_api

		self.assertEqual(
			self.page_write_set(), admin_api.POST_ONLY_METHODS, "client/server verb mismatch"
		)

	def page_write_set(self):
		block = self.js[self.js.index("var ADMIN_WRITES") : self.js.index("};", self.js.index("var ADMIN_WRITES"))]
		return set(re.findall(r"(\w+): 1", block))

	def test_read_endpoints_are_not_declared_as_writes(self):
		block = self.js[self.js.index("var ADMIN_WRITES") : self.js.index("};", self.js.index("var ADMIN_WRITES"))]
		self.assertNotIn("get_leave_request", block)
		self.assertNotIn("list_leave_requests", block)
		self.assertNotIn("get_admin_dashboard", block)

	def test_report_does_not_derive_approved_from_the_total(self):
		"""total - draft counts a cancelled request as approved."""
		self.assertNotRegex(self.js, r"\(v\.total \|\| 0\) - \(v\.draft \|\| 0\)")
		self.assertIn("(v.approved || 0)", self.js)
		self.assertIn("(v.rejected || 0)", self.js)

	def test_unreadable_headcount_is_hidden_not_shown_as_zero(self):
		self.assertIn('classList.toggle("saudi-stats--hidden", !!e.scoped)', self.js)
		self.assertIn("headcount-stats", self.html)

	def test_unreadable_leave_doctypes_are_hidden_from_both_tables(self):
		self.assertIn("leave[k].readable !== false", self.js)

	def test_the_modal_traps_focus_and_restores_it(self):
		"""A dialog that leaks focus is unusable by keyboard and mis-announced."""
		self.assertIn("function handleFocusTrap(", self.js)
		self.assertIn("e.key !== \"Tab\"", self.js)
		self.assertIn("ADMIN_STATE.lastFocus", self.js)
		self.assertIn("document.body.classList.add(\"saudi-modal-open\")", self.js)

	def test_a_visually_hidden_label_class_exists(self):
		"""The search inputs rely on .sr-only; a missing class shows a stray label."""
		css = open(
			os.path.join(frappe.get_app_path("saudi_hr"), "public", "css", "saudi_portal.css")
		).read()
		self.assertIn(".sr-only", css)
		self.assertIn("clip:", css)
		# display:none would drop the accessible name entirely
		block = css[css.index(".sr-only") : css.index(".sr-only") + 400]
		self.assertNotIn("display: none", block)

	def test_seeded_dashboard_is_json_encoded(self):
		"""tojson prevents a label containing a quote from breaking the script."""
		self.assertIn("| tojson", page_source(), "the template must seed via tojson")
		i = self.html.index("var seeded = ")
		block = self.html[i : self.html.index(";", i)]
		self.assertNotIn("\n", block, "the seed must be one statement")
		self.assertNotIn("&", block, "tojson output must use \\u0026, not a raw ampersand")
		self.assertIn("\\u", block, "tojson output must be escaped")


DOM_STUBS = """
/* The smallest DOM the page will touch, so its own functions can be executed. */
var FAILURES = [];
var elements = {};
function el(id) {
	if (!elements[id]) {
		elements[id] = {
			id: id, innerHTML: "", textContent: "", value: "", hidden: false, style: {},
			classList: {
				add: function(){}, remove: function(){}, toggle: function(){},
				contains: function(){ return false; }
			},
			addEventListener: function(){}, setAttribute: function(){},
			getAttribute: function(){ return null; }, focus: function(){},
			querySelectorAll: function(){ return []; }, querySelector: function(){ return null; },
			reset: function(){}, closest: function(){ return null; }, disabled: false
		};
	}
	return elements[id];
}
var document = {
	getElementById: el,
	querySelectorAll: function(){ return []; },
	querySelector: function(){ return null; },
	addEventListener: function(){},
	activeElement: null,
	body: { classList: { add: function(){}, remove: function(){} } }
};
var frappe = { call: function(){ return Promise.resolve({ message: {} }); }, ready: function(){} };
var window = { frappe: frappe };
var confirm = function(){ return true; };
function check(name, fn) {
	try {
		if (fn() !== true) { FAILURES.push(name); }
	} catch (e) {
		FAILURES.push(name + ": " + e.message);
	}
}
function noThrow(name, fn) {
	try { fn(); } catch (e) { FAILURES.push(name + ": " + e.message); }
}
"""


class TestAdminPageBehaviour(FrappeTestCase):
	"""The page's own JavaScript, executed.

	Reading the source proves the code is shaped right; running it proves it
	works. A Python test shells out to node, so these assertions catch a broken
	seed, a Python literal in a JS object, or an escape helper with a hole in it.
	"""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.html, _ctx = render_page()
		self.js = page_js(self.html)
		self.shared = open(
			os.path.join(frappe.get_app_path("saudi_hr"), "public", "js", "saudi_portal.js")
		).read()

	def _run(self, assertions):
		"""Run `assertions` against the page script and return the failures.

		The stubs, the shared runtime, the page script and the assertions all run
		in one V8 context, so the assertions see the page's own functions the way
		a browser would.
		"""
		if not shutil.which("node"):
			self.skipTest("node is not installed")
		harness = "const vm = require('vm');\nconst sandbox = { console: console };\nvm.createContext(sandbox);\n" + "".join(
			"vm.runInContext(%s, sandbox, { filename: %s });\n"
			% (json.dumps(source), json.dumps(name))
			for source, name in (
				(DOM_STUBS, "stubs.js"),
				(self.shared, "saudi_portal.js"),
				(self.js + "\n" + assertions + "\nFAILURES;\n", "saudi-admin.html"),
			)
		) + "console.log(JSON.stringify(sandbox.FAILURES));\n"
		with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as handle:
			handle.write(harness)
			path = handle.name
		try:
			result = subprocess.run(["node", path], capture_output=True, text=True, timeout=60)
		finally:
			os.unlink(path)
		self.assertEqual(result.returncode, 0, result.stderr[-2000:])
		return json.loads(result.stdout.strip().splitlines()[-1])

	def test_the_page_script_parses(self):
		"""A Python True in a JS literal parses as nothing at all."""
		self.assertEqual(self._run("check('booleans', () => typeof ADMIN_CFG.can_manage_employees === 'boolean');"), [])

	def test_the_seeded_dashboard_is_valid_json_the_page_can_render_immediately(self):
		"""The first paint comes from the server, so the seed must survive the trip."""
		match = re.search(r"var seeded = (\{.*?\});", self.html, re.S)
		self.assertIsNotNone(match, "the page should seed the report from the server dashboard")
		seeded = json.loads(match.group(1))
		self.assertIn("Saudi Annual Leave", seeded)
		self.assertIn("readable", seeded["Saudi Annual Leave"])
		for label, counts in seeded.items():
			self.assertIsInstance(counts["total"], int, label)
			self.assertIsInstance(counts["approved"], int, label)
			self.assertIsInstance(counts["actionable"], int, label)

	def test_the_escape_helper_covers_every_dangerous_character(self):
		self.assertEqual(
			self._run(
				"check('markup', () => esc('<img src=x onerror=\"a\">')"
				" === '&lt;img src=x onerror=&quot;a&quot;&gt;');"
				"check('ampersand', () => esc('a & b') === 'a &amp; b');"
				"check('quote', () => esc(\"it's\") === 'it&#39;s');"
				"check('null', () => esc(null) === '' && esc(undefined) === '');"
				"check('number', () => esc(0) === '0');"
			),
			[],
		)

	def test_action_labels_are_translated_and_never_blank(self):
		self.assertEqual(
			self._run(
				"check('submit', () => actionLabel('submit') === t('admin_action_submit'));"
				"check('approve', () => actionLabel('approve') === t('admin_action_approve'));"
				"check('case', () => actionLabel('APPROVE') === t('admin_action_approve'));"
				"check('fallback', () => actionLabel('Escalate') === 'Escalate');"
				"check('confirm', () => { const s = confirmText('approve', 'SAL-1');"
				" return s.includes('SAL-1') && !s.includes('{action}') && !s.includes('{name}'); });"
			),
			[],
		)

	def test_a_hostile_name_is_escaped_before_it_reaches_the_dom(self):
		self.assertEqual(
			self._run(
				"noThrow('render', function() {"
				" ADMIN_STATE.employees = [{ employee_number: '1',"
				" full_name: '<img src=x onerror=alert(1)>', status: 'Active', desk_url: '#' }];"
				" renderEmployees(false); });"
				"check('no raw tag', function() { return !document.getElementById('employees-rows')"
				" .innerHTML.includes('<img'); });"
				"check('escaped present', function() { return document.getElementById('employees-rows')"
				" .innerHTML.includes('&lt;img'); });"
			),
			[],
		)

	def test_reads_go_out_as_get_and_writes_as_post(self):
		self.assertEqual(
			self._run(
				"var seen = null; frappe.call = function(o) { seen = o;"
				" return Promise.resolve({ message: {} }); };"
				"check('read verb', function() { callAdmin('list_leave_requests', {});"
				" return seen.type === 'GET'; });"
				"check('read target', function() { return seen.args.method ==="
				" 'saudi_hr.saudi_hr.admin_api.list_leave_requests'; });"
				"check('write verb', function() { callAdmin('apply_leave_action',"
				" { doctype: 'x', name: 'y', action: 'approve' });"
				" return seen.type === 'POST'; });"
			),
			[],
		)

	def test_the_report_hides_doctypes_the_user_cannot_read(self):
		self.assertEqual(
			self._run(
				"noThrow('renderLeaveTables', function() { renderLeaveTables({"
				" A: { label: 'A', total: 3, draft: 1, approved: 2,"
				" rejected: 0, cancelled: 0, other: 0, actionable: 1, readable: true },"
				" B: { label: 'B', total: 9, draft: 9, approved: 0, rejected: 0,"
				" cancelled: 0, other: 0, actionable: 9, readable: false } }); });"
				"check('dashboard hides', function() { return !document.getElementById('dashboard-leave-rows')"
				" .innerHTML.includes('>B<'); });"
				"check('report hides', function() { return !document.getElementById('report-rows')"
				" .innerHTML.includes('>B<'); });"
			),
			[],
		)

	def test_the_report_uses_the_servers_outcome_counts(self):
		self.assertEqual(
			self._run(
				"noThrow('renderLeaveTables', function() { renderLeaveTables({"
				" A: { label: 'A', total: 10, draft: 4, approved: 3,"
				" rejected: 2, cancelled: 1, other: 0, actionable: 4, readable: true } }); });"
				"var out = document.getElementById('report-rows').innerHTML;"
				"check('approved', function() { return out.includes('>3<'); });"
				"check('rejected', function() { return out.includes('>2<'); });"
				"check('cancelled', function() { return out.includes('>1<'); });"
				"check('total', function() { return out.includes('>10<'); });"
			),
			[],
		)

	def test_a_capped_report_says_so_instead_of_looking_exact(self):
		self.assertEqual(
			self._run(
				"noThrow('render', function() { renderLeaveTables({"
				" A: { label: 'A', total: 10, draft: 4, approved: 3, rejected: 2,"
				" cancelled: 1, other: 0, actionable: 4, readable: true } },"
				" ['A']); });"
				"check('note shown', function() { var note = document.getElementById('report-note');"
				" return note.hidden === false && note.textContent.includes('A'); });"
				"noThrow('render again', function() { renderLeaveTables({"
				" A: { label: 'A', total: 10, draft: 4, approved: 3, rejected: 2,"
				" cancelled: 1, other: 0, actionable: 4, readable: true } }, []); });"
				"check('note hidden when nothing was capped', function() {"
				" return document.getElementById('report-note').hidden === true; });"
			),
			[],
		)

	def test_a_restricted_employee_list_says_so(self):
		self.assertEqual(
			self._run(
				"noThrow('renderEmployees', function() { renderEmployees(true); });"
				"check('message', function() { return document.getElementById('employees-rows')"
				" .innerHTML.includes(t('admin_employees_restricted')); });"
			),
			[],
		)


class TestAdminPageRoute(FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")

	def test_route_is_registered(self):
		routes = frappe.get_hooks("website_route_rules") or []
		from_routes = [r.get("from_route") for r in routes]
		self.assertIn("/saudi-admin", from_routes)

	def test_apps_screen_entry_points_at_the_route(self):
		entries = frappe.get_hooks("add_to_apps_screen") or []
		routes = [e.get("route") for e in entries]
		self.assertIn("/saudi-admin", routes)
		# the employee portal must survive alongside it
		self.assertIn("/mobile-attendance", routes)

	def test_page_file_is_named_to_match_its_route(self):
		self.assertTrue(os.path.exists(template_path()))
		self.assertTrue(os.path.exists(template_path().replace(".html", ".py")))

	def test_page_is_uncached(self):
		"""Caching the shell would cache a role gate decision."""
		import importlib

		module = importlib.import_module("saudi_hr.www.saudi-admin")
		self.assertEqual(getattr(module, "no_cache", 0), 1)
		self.assertEqual(getattr(module, "login_required", 0), 1)
