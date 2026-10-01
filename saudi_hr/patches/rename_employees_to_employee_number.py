"""Rename Employee documents whose id does not match their employee_number.

An employee import created every Employee under the default naming series
(HR-EMP-00001 ...) rather than the real employee number, so document ids and
business ids did not match. This runs the same rename as
`saudi_hr.scripts.rename_employees_to_employee_number` automatically, so
`bench update` / `bench migrate` fixes the data on every site with no manual step.

Design notes:

- Idempotent. It only touches employees where `name != employee_number`, so a
  site that is already correct (or a re-run after a partial failure) does
  nothing. Because Frappe logs a patch once it returns, this runs a single time
  per site; employees renamed or edited by hand afterwards are handled by
  re-running the command printed on failure.
- Never blocks a deploy. A duplicate or missing employee_number is a data
  problem, not a reason to fail `bench migrate`, so those employees are skipped
  and reported. Real per-employee failures are logged to Error Log and printed
  with the command needed to finish the job.

Control it from site_config.json without touching code:

    "saudi_hr_employee_rename": "skip"      # do nothing (default: "run")
    "saudi_hr_employee_rename": "dry-run"   # only print the plan
"""

import frappe

from saudi_hr.scripts.rename_employees_to_employee_number import (
	SKIP_BUCKETS,
	SKIP_TITLES,
	apply_renames,
	build_plan,
)

DEFAULT_MODE = "run"
# braces are escaped because the command itself contains a kwargs dict
RETRY_COMMAND = (
	"bench --site {site} execute "
	"saudi_hr.scripts.rename_employees_to_employee_number.run "
	"--kwargs \"{{'apply': True}}\""
)


def _log(message):
	print(f"[saudi_hr] {message}")


def mode():
	"""How the patch should behave, from site_config.json.

	Separate from execute() so it can be overridden in tests without patching
	Frappe's own config plumbing.
	"""
	return (frappe.conf.get("saudi_hr_employee_rename") or DEFAULT_MODE).lower()


def _describe_skips(skipped):
	"""One line per non-empty skip bucket, ignoring the already-correct ones."""
	lines = []
	for key in SKIP_BUCKETS:
		if key == "skip_already":
			continue
		items = skipped.get(key) or []
		if not items:
			continue
		names = ", ".join(
			"%s (number=%s)" % (item[0].name, item[1]) if isinstance(item, tuple) else item.name
			for item in items
		)
		lines.append(f"    {SKIP_TITLES[key]}: {names}")
	return lines


def execute():
	run_mode = mode()
	if run_mode == "skip":
		_log("employee rename skipped (saudi_hr_employee_rename = skip)")
		return

	plan, total = build_plan()
	pending = len(plan["rename"])
	_log(f"employee rename check: {total} employee(s), {pending} to rename, mode = {run_mode}")

	if not pending:
		_already_correct(total, plan)
		return

	if run_mode == "dry-run":
		_log("dry run - listing what would change, writing nothing")
		for row, number in plan["rename"]:
			_log(f"    would rename {row.name} -> {number} ({row.employee_name or ''})")
		for line in _describe_skips(plan):
			_log(line)
		return

	# commit_each=False: the patch runs inside the migration transaction, so let
	# the patch framework commit once. `bench migrate` rebuilds the search index.
	result = apply_renames(commit_each=False)

	renamed, failed = result["renamed"], result["failed"]
	_log(f"employee rename done: {len(renamed)} renamed, {len(failed)} failed")

	for line in _describe_skips(result["skipped"]):
		_log(line)

	if not failed:
		return

	# Something went wrong for at least one employee. Do not stop the deploy, but
	# make it impossible to miss and leave the exact command that finishes the job.
	details = "\n".join(f"{old} -> {new}: {error}" for old, new, error in failed)
	retry = RETRY_COMMAND.format(site=frappe.local.site)
	_log("")
	_log("!! %s employee(s) could NOT be renamed - the fix is INCOMPLETE" % len(failed))
	for old, new, error in failed:
		_log(f"    {old} -> {new}: {error}")
	_log("    finish it with: %s" % retry)
	frappe.log_error(
		title="Saudi HR: employee rename incomplete",
		message="%s employee(s) failed to rename on %s:\n%s\n\nFinish with:\n%s"
		% (len(failed), frappe.local.site, details, retry),
	)


def _already_correct(total, plan):
	skipped = len(plan.get("skip_already") or [])
	_log(f"every employee id already matches its employee_number ({skipped}/{total}) - nothing to do")
