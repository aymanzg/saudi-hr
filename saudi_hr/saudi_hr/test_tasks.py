from types import SimpleNamespace
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from saudi_hr.saudi_hr import tasks as tasks_module


class TestSaudiHRTasks(FrappeTestCase):
	def test_should_send_days_left_alert_only_for_milestones(self):
		self.assertTrue(tasks_module._should_send_days_left_alert(60, 60))
		self.assertTrue(tasks_module._should_send_days_left_alert(30, 60))
		self.assertTrue(tasks_module._should_send_days_left_alert(7, 60))
		self.assertFalse(tasks_module._should_send_days_left_alert(59, 60))
		self.assertFalse(tasks_module._should_send_days_left_alert(5, 60))

	def test_get_pending_alert_recipients_skips_existing_notifications(self):
		with patch.object(tasks_module, "_has_existing_alert", side_effect=lambda user, *_args: user == "hr@example.com"):
			recipients = tasks_module._get_pending_alert_recipients(
				["hr@example.com", "manager@example.com"],
				"Contract alert",
				"Saudi Employment Contract",
				"CONT-0001",
			)

		self.assertEqual(recipients, ["manager@example.com"])

	def _run_repair(self, orphans, existing_row=None, branch="HQ"):
		created_docs = []

		def fake_get_value(doctype, filters=None, fieldname=None, **kwargs):
			if doctype == "Saudi Daily Attendance":
				return existing_row
			if doctype == "Employee":
				return branch
			return None

		def fake_build(*args, **kwargs):
			doc = SimpleNamespace(name="ATT-0001")
			created_docs.append((args, kwargs))
			return doc

		with patch.object(tasks_module.frappe, "get_all", return_value=orphans), patch.object(
			tasks_module.frappe.db, "get_value", side_effect=fake_get_value
		), patch.object(tasks_module.frappe.db, "set_value") as set_value, patch.object(
			tasks_module.frappe.db, "commit"
		), patch(
			"saudi_hr.saudi_hr.api._build_daily_attendance", side_effect=fake_build
		), patch(
			"saudi_hr.saudi_hr.api._get_location_for_branch", return_value=None
		), patch(
			"saudi_hr.saudi_hr.attendance_policy.resolve_mobile_attendance_policy", return_value={}
		), patch(
			"saudi_hr.saudi_hr.attendance_policy.calculate_attendance_variance", return_value={}
		):
			result = tasks_module.sync_missing_daily_attendance()

		return result, created_docs, set_value

	def test_sync_missing_daily_attendance_creates_row_for_in_and_out(self):
		orphans = [
			{"name": "C-IN", "employee": "E1", "log_type": "IN", "time": "2026-09-20 09:00:00"},
			{"name": "C-OUT", "employee": "E1", "log_type": "OUT", "time": "2026-09-20 17:00:00"},
		]

		result, created_docs, set_value = self._run_repair(orphans)

		self.assertEqual(result, {"created": 1, "linked": 0, "skipped": 0})
		self.assertEqual(len(created_docs), 1)
		args = created_docs[0][0]
		self.assertEqual(args[0], "E1")
		self.assertEqual(str(args[1]), "2026-09-20")
		self.assertEqual(str(args[2]), "2026-09-20 09:00:00")
		self.assertEqual(str(args[3]), "2026-09-20 17:00:00")
		linked_checkins = {call.args[1] for call in set_value.call_args_list}
		self.assertEqual(linked_checkins, {"C-IN", "C-OUT"})

	def test_sync_missing_daily_attendance_links_to_existing_row(self):
		orphans = [
			{"name": "C-IN", "employee": "E1", "log_type": "IN", "time": "2026-09-20 09:00:00"},
			{"name": "C-OUT", "employee": "E1", "log_type": "OUT", "time": "2026-09-20 17:00:00"},
		]

		result, created_docs, set_value = self._run_repair(orphans, existing_row="ATT-EXIST")

		self.assertEqual(result, {"created": 0, "linked": 2, "skipped": 0})
		self.assertEqual(created_docs, [])
		self.assertTrue(all(call.args[3] == "ATT-EXIST" for call in set_value.call_args_list))

	def test_sync_missing_daily_attendance_skips_incomplete_punch_days(self):
		orphans = [{"name": "C-IN", "employee": "E1", "log_type": "IN", "time": "2026-09-20 09:00:00"}]

		result, created_docs, set_value = self._run_repair(orphans)

		self.assertEqual(result, {"created": 0, "linked": 0, "skipped": 1})
		self.assertEqual(created_docs, [])
		set_value.assert_not_called()