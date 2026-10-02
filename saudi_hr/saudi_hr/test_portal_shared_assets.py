"""Guards the shared foundation behind /mobile-attendance and /saudi-admin.

The portal pages used to carry ~480 lines of CSS and a 290-key label object
inline, which is exactly the duplication that made a second page worth
extracting. These tests fail if anyone re-inlines that shared code, or if the
runtime starts calling an employee-only endpoint from the shared layer.
"""

import os
import re
import unittest

import frappe

APP = frappe.get_app_path("saudi_hr")
WWW = os.path.join(APP, "www")
CSS = os.path.join(APP, "public", "css", "saudi_portal.css")
JS = os.path.join(APP, "public", "js", "saudi_portal.js")

# every portal page must load the shared runtime this way
SHARED_CSS_HREF = "/assets/saudi_hr/css/saudi_portal.css"
SHARED_JS_SRC = "/assets/saudi_hr/js/saudi_portal.js"

# functions the shared runtime must own; pages call these, never redefine them
SHARED_FUNCTIONS = {
	"applyLang",
	"initPortalLang",
	"logoutUser",
	"navigate",
	"restorePanel",
	"serverErrorMessage",
	"showSessionBanner",
	"showToast",
	"t",
	"toggleLang",
}

SHARED_GLOBALS = {
	"CURRENT_LANG",
	"LABELS",
	"SAUDI_LANG_RENDERERS",
	"SAUDI_PANEL_LOADERS",
	"SAUDI_PANEL_STORE_KEY",
}


def read(path):
	with open(path, encoding="utf-8") as handle:
		return handle.read()


def defined_functions(source):
	return set(re.findall(r"^\s*function\s+([A-Za-z_$][\w$]*)\s*\(", source, re.M))


def strip_js_literals(source):
	"""Blank out comments, strings and regex literals, keeping line structure.

	A page builds HTML in strings and strips tags with regexes, so the raw
	source contains ``var(--text-muted)``, ``:not(...)`` and ``/\\?"/``. Left in
	place they look like calls to undefined functions. Regex literals are
	detected by the preceding character rather than by full parsing, which is
	enough for hand written page code.
	"""
	out = []
	i = 0
	length = len(source)
	# a slash opens a regex only after something that cannot end an expression
	regex_ok = set("(,=:[!&|?{};+-*%~^<>")
	while i < length:
		char = source[i]
		if source.startswith("//", i):
			while i < length and source[i] != "\n":
				i += 1
			continue
		if source.startswith("/*", i):
			end = source.find("*/", i + 2)
			end = length if end == -1 else end + 2
			out.append("\n" * source.count("\n", i, end))
			i = end
			continue
		if char in "\"'":
			quote = char
			i += 1
			while i < length:
				if source[i] == "\\":
					i += 2
					continue
				if source[i] == quote:
					i += 1
					break
				i += 1
			continue
		if char == "/" and (not out or out[-1] in regex_ok):
			end = i + 1
			in_class = False
			while end < length:
				if source[end] == "\\":
					end += 2
					continue
				if source[end] == "\n":
					break
				if source[end] == "[":
					in_class = True
				elif source[end] == "]":
					in_class = False
				elif source[end] == "/" and not in_class:
					break
				end += 1
			out.append("\n" * source.count("\n", i, end))
			i = end + 1
			continue
		out.append(char)
		i += 1
	return "".join(out)


def page_script(source):
	"""The page's own inline script, with comment and literal bodies removed."""
	return strip_js_literals("\n".join(re.findall(r"<script>(.*?)</script>", source, re.S)))


def portal_pages():
	"""www pages that load the shared runtime."""
	pages = []
	for name in sorted(os.listdir(WWW)):
		if not name.endswith(".html"):
			continue
		source = read(os.path.join(WWW, name))
		if SHARED_JS_SRC in source:
			pages.append((name, source))
	return pages


class TestPortalSharedAssets(unittest.TestCase):
	def test_shared_files_exist(self):
		self.assertTrue(os.path.isfile(CSS), "shared stylesheet is missing")
		self.assertTrue(os.path.isfile(JS), "shared runtime is missing")

	def test_stylesheet_is_balanced_and_themed(self):
		css = read(CSS)
		self.assertEqual(css.count("{"), css.count("}"), "unbalanced braces in shared CSS")
		self.assertIn(":root", css, "design tokens must live in the shared stylesheet")
		for token in ("--app-primary", "--app-bg", "--text-main", "--border-color"):
			self.assertIn(token, css, f"{token} is part of the shared theme contract")

	def test_stylesheet_covers_desktop_and_mobile(self):
		"""The admin shell is desktop; the employee page must keep its phone layout."""
		css = read(CSS)
		self.assertIn("@media (max-width: 650px)", css, "mobile breakpoint was lost")
		self.assertIn("@media (min-width: 1024px)", css, "desktop breakpoint is missing")
		for selector in (".saudi-shell", ".saudi-rail", ".saudi-stats", ".saudi-table"):
			self.assertIn(selector, css, f"{selector} is needed by the admin surface")

	def test_runtime_defines_the_shared_contract(self):
		js = read(JS)
		self.assertTrue(
			SHARED_FUNCTIONS <= defined_functions(js),
			f"runtime is missing: {sorted(SHARED_FUNCTIONS - defined_functions(js))}",
		)
		globals_ = set(re.findall(r"^var\s+([A-Za-z_$][\w$]*)", js, re.M))
		self.assertTrue(
			SHARED_GLOBALS <= globals_,
			f"runtime is missing globals: {sorted(SHARED_GLOBALS - globals_)}",
		)

	def test_runtime_is_balanced(self):
		js = read(JS)
		self.assertEqual(js.count("{"), js.count("}"), "unbalanced braces in shared JS")
		self.assertEqual(js.count("("), js.count(")"), "unbalanced parens in shared JS")

	def test_runtime_does_not_call_page_endpoints(self):
		"""The shared layer must stay data-free, or the admin page inherits
		employee-scoped calls it has no business making."""
		js = read(JS)
		self.assertNotIn("frappe.call(", js, "shared runtime must not make API calls")
		for forbidden in (
			"get_self_service_portal",
			"get_attendance_status",
			"submit_mobile_leave_request",
			"loadMyRequests",
			"loadAttendanceLog",
			"renderQuickActions",
			"populateLeaveSubtypes",
		):
			self.assertNotIn(forbidden, js, f"{forbidden} is page-specific, not shared")

	def test_labels_have_both_locales(self):
		js = read(JS)
		ar = set(re.findall(r"^\t\t([a-z_][\w]*):", js.split("ar: {")[1].split("\n\t}")[0], re.M))
		en = set(re.findall(r"^\t\t([a-z_][\w]*):", js.split("en: {")[1].split("\n\t}")[0], re.M))
		self.assertTrue(ar, "no Arabic labels found")
		self.assertEqual(ar, en, "label keys drifted between ar and en")

	def test_pages_load_the_shared_runtime(self):
		pages = portal_pages()
		self.assertTrue(pages, "no www page loads the shared runtime")
		for name, source in pages:
			with self.subTest(page=name):
				self.assertIn(SHARED_CSS_HREF, source)
				self.assertIn(SHARED_JS_SRC, source)

	def test_pages_do_not_reinline_the_shared_code(self):
		for name, source in portal_pages():
			with self.subTest(page=name):
				self.assertNotIn("<style>", source, f"{name} re-inlined the stylesheet")
				self.assertNotIn(
					"var LABELS", source, f"{name} re-inlined the label object"
				)
				for fn in sorted(SHARED_FUNCTIONS):
					self.assertNotRegex(
						source,
						r"^\s*function\s+%s\s*\(" % re.escape(fn),
						f"{name} redefines the shared {fn}()",
					)

	def test_page_callers_are_all_satisfied(self):
		"""Every function a page calls must exist in the page or the runtime.

		A missing shared asset fails silently in the browser, so this is the
		check that would have caught a bad extraction.
		"""
		js = read(JS)
		known = defined_functions(js) | {
			# browser and Frappe globals a page may legitimately call
			"if",
			"for",
			"while",
			"switch",
			"catch",
			"function",
			"return",
			"typeof",
			"setTimeout",
			"setInterval",
			"clearTimeout",
			"clearInterval",
			"parseInt",
			"parseFloat",
			"isNaN",
			"require",
			"confirm",
			"alert",
			"String",
			"Number",
			"Array",
			"Object",
			"Math",
			"JSON",
			"Date",
			"Error",
			"frappe",
			"moment",
			"localStorage",
			"document",
			"window",
			"console",
		}
		for name, source in portal_pages():
			page_js = page_script(source)
			called = set(re.findall(r"(?<![.\w$:])([a-z_$][\w$]*)\s*\(", page_js))
			own = defined_functions(page_js)
			missing = sorted(called - known - own)
			with self.subTest(page=name):
				self.assertEqual(missing, [], f"{name} calls undefined: {missing}")

	def test_pages_register_their_hooks(self):
		"""A page with panel loaders must hand them to the runtime, and the
		runtime must not hardcode any panel name."""
		js = read(JS)
		for name, source in portal_pages():
			inline = "\n".join(re.findall(r"<script>(.*?)</script>", source, re.S))
			with self.subTest(page=name):
				if "onclick=\"navigate(" in source or "onclick='navigate(" in source:
					self.assertIn("SAUDI_PANEL_LOADERS", inline, f"{name} routes but registers no loaders")
				if "data-i18n-key" in source:
					self.assertIn("SAUDI_LANG_RENDERERS", inline, f"{name} has i18n but no lang renderer")
				self.assertIn("initPortalLang()", inline, f"{name} must use the shared language init")
				self.assertIn("restorePanel(", inline, f"{name} must use the shared panel restore")

	def test_runtime_does_not_hardcode_panel_names(self):
		"""Panels belong to a page; hardcoding one here leaks it to the other."""
		js = read(JS)
		body = js.split("/* ─── Routing", 1)[-1]
		for panel in ("home", "requests", "leave", "attendance", "profile", "employees", "approvals"):
			self.assertNotRegex(
				body,
				r'["\']%s["\']' % panel,
				f"panel name {panel!r} is hardcoded in the shared router",
			)
