"""Flexible start shifts.

An 8-4 shift with an hour of flexibility lets the employee arrive any time
from 08:00 to 09:00 and then owe the full eight hours from arrival. Lateness
counts from 09:00 once the grace period is used up.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import get_datetime

from saudi_hr.saudi_hr import attendance_policy as policy_module
from saudi_hr.saudi_hr.attendance_policy import (
	_build_schedule_window,
	calculate_attendance_variance,
	flexible_expected_end,
)

DAY = "2026-11-01"


def _shift(flex=60, start="08:00:00", end="16:00:00", late_grace=15, early_grace=15):
	return frappe._dict(
		name="Flexible 8-4",
		start_time=start,
		end_time=end,
		begin_check_in_before_shift_start_time=60,
		allow_check_out_after_shift_end_time=60,
		enable_late_entry_marking=1,
		late_entry_grace_period=late_grace,
		enable_early_exit_marking=1,
		early_exit_grace_period=early_grace,
		flexible_start_minutes=flex,
	)


def _at(clock):
	return get_datetime(f"{DAY} {clock}")


class TestFlexibleShift(FrappeTestCase):
	def _variance(self, log_type, clock, flex=60, in_clock=None, **shift):
		policy = _build_schedule_window(DAY, _shift(flex=flex, **shift))
		return calculate_attendance_variance(log_type, _at(clock), policy, in_time=_at(in_clock) if in_clock else None)

	def test_arriving_inside_the_flexible_hour_is_not_late(self):
		self.assertEqual(self._variance("IN", "08:59")["late_minutes"], 0)

	def test_grace_applies_after_the_flexible_hour(self):
		self.assertEqual(self._variance("IN", "09:10")["late_minutes"], 0)

	def test_lateness_counts_from_the_end_of_the_flexible_hour(self):
		result = self._variance("IN", "09:30")
		self.assertEqual(result["late_minutes"], 30)
		self.assertEqual(result["late_entry"], 1)

	def test_shift_ends_eight_hours_after_arrival(self):
		self.assertEqual(self._variance("OUT", "17:00", in_clock="09:00")["early_exit_minutes"], 0)
		self.assertEqual(self._variance("OUT", "16:40", in_clock="08:40")["early_exit_minutes"], 0)
		self.assertEqual(self._variance("OUT", "16:00", in_clock="09:00")["early_exit_minutes"], 60)

	def test_early_grace_applies_to_the_moved_end(self):
		self.assertEqual(self._variance("OUT", "16:50", in_clock="09:00")["early_exit_minutes"], 0)

	def test_late_arrival_owes_only_up_to_the_latest_end(self):
		# in at 10:00 (an hour late): the day still ends at 17:00
		self.assertEqual(self._variance("OUT", "17:00", in_clock="10:00")["early_exit_minutes"], 0)

	def test_early_arrival_does_not_end_before_the_shift_end(self):
		self.assertEqual(self._variance("OUT", "15:30", in_clock="07:30")["early_exit_minutes"], 30)

	def test_without_check_in_the_plain_end_is_used(self):
		self.assertEqual(self._variance("OUT", "16:00")["early_exit_minutes"], 0)

	def test_fixed_shift_is_unchanged(self):
		self.assertEqual(self._variance("IN", "08:10", flex=0)["late_minutes"], 0)
		self.assertEqual(self._variance("IN", "08:30", flex=0)["late_minutes"], 30)
		self.assertEqual(self._variance("OUT", "15:30", flex=0, in_clock="08:00")["early_exit_minutes"], 30)

	def test_flexible_expected_end_clamps_to_the_window(self):
		policy = _build_schedule_window(DAY, _shift())
		self.assertEqual(flexible_expected_end(policy, _at("08:30")), _at("16:30"))
		self.assertEqual(flexible_expected_end(policy, _at("07:00")), _at("16:00"))
		self.assertEqual(flexible_expected_end(policy, _at("11:00")), _at("17:00"))

	def test_open_shift_never_counts_lateness(self):
		policy = _build_schedule_window(DAY, _shift(start="00:00:00", end="23:59:59"))
		self.assertEqual(calculate_attendance_variance("IN", _at("11:00"), policy)["late_minutes"], 0)


class TestRecomputeAttendanceVariance(FrappeTestCase):
	def _row(self, **values):
		row = frappe._dict(
			name="SDA-1",
			attendance_date=DAY,
			in_time=_at("09:53"),
			out_time=_at("16:27"),
			attendance_location=None,
			shift_type="Open",
			expected_start_time=None,
			expected_end_time=None,
			late_minutes=0,
			early_exit_minutes=0,
		)
		row.update(values)
		return row

	def _recompute(self, rows, shift):
		window = _build_schedule_window(DAY, shift)
		policy = dict(window, shift_type=shift.name, enable_late_entry_marking=1, enable_early_exit_marking=1)
		with patch.object(policy_module.frappe, "get_all", return_value=rows), patch.object(
			policy_module, "resolve_mobile_attendance_policy", return_value=policy
		), patch.object(policy_module.frappe.db, "set_value") as set_value:
			changed = policy_module.recompute_attendance_variance("EMP-1", DAY, DAY)
		return changed, set_value

	def test_open_shift_day_is_measured_against_the_new_flexible_shift(self):
		changed, set_value = self._recompute([self._row()], _shift())
		self.assertEqual(changed, 1)
		updates = set_value.call_args[0][2]
		# in 09:53 -> 53 late from 09:00; ends 17:00, out 16:27 -> 33 early
		self.assertEqual(updates["late_minutes"], 53)
		self.assertEqual(updates["early_exit_minutes"], 33)
		self.assertEqual(updates["shift_type"], "Flexible 8-4")
		self.assertEqual(get_datetime(updates["expected_end_time"]), _at("17:00"))

	def test_unchanged_day_is_left_alone(self):
		row = self._row(
			in_time=_at("08:30"),
			out_time=_at("16:30"),
			shift_type="Flexible 8-4",
			expected_start_time=_at("08:00"),
			expected_end_time=_at("16:30"),
		)
		changed, set_value = self._recompute([row], _shift())
		self.assertEqual(changed, 0)
		set_value.assert_not_called()
