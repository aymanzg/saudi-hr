"""Mobile punch geolocation: run the JS unit tests and check the page wiring.

The punch page used to show "please allow location permission" for every
geolocation failure. The JS tests in public/js/tests cover how errors are
told apart and retried; this file runs them under bench and checks that the
page actually uses that module.
"""

import os
import shutil
import subprocess
import unittest

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS_TEST = os.path.join(APP, "public", "js", "tests", "punch_geolocation.test.js")
PAGE = os.path.join(APP, "www", "mobile-attendance.html")
PORTAL_JS = os.path.join(APP, "public", "js", "saudi_portal.js")


def _read(path):
	with open(path, encoding="utf-8") as f:
		return f.read()


class TestPunchGeolocation(unittest.TestCase):
	def test_js_unit_tests_pass(self):
		node = shutil.which("node")
		if not node:
			self.skipTest("node is not installed")
		proc = subprocess.run([node, "--test", JS_TEST], capture_output=True, text=True, timeout=120)
		self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

	def test_page_loads_module_and_uses_it(self):
		page = _read(PAGE)
		self.assertIn("/assets/saudi_hr/js/punch_geolocation.js", page)
		self.assertIn("SaudiPunchGeo.locate(", page)
		self.assertIn('id="punch-gps-retry-btn"', page)
		# the page must not call geolocation directly any more, or the
		# single "allow permission" message comes back
		self.assertNotIn("navigator.geolocation.getCurrentPosition", page)

	def test_specific_messages_exist_in_both_languages(self):
		js = _read(PORTAL_JS)
		for kind in ("denied", "unavailable", "timeout", "insecure", "unsupported"):
			self.assertEqual(js.count("gps_err_%s:" % kind), 2, kind)
