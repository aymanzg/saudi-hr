"""One-off data fix: rename Employee documents to their employee_number.

The employee import created every Employee with the default naming-series id
(HR-EMP-00001 ...) instead of the real employee number, so the document id and
the business id did not match.  This renames `name` - and the Employee
"Employee ID" data field - to `employee_number`, keeping every linked record
consistent (check-ins, permits, attendance, payroll, user permissions, files).

Run it from the bench directory:

    bench --site hr.local backup --with-files

    # 1. inspect the plan - writes nothing
    bench --site hr.local execute saudi_hr.scripts.rename_employees_to_employee_number.run

    # 2. rehearse on a single employee
    bench --site hr.local execute saudi_hr.scripts.rename_employees_to_employee_number.run \
        --kwargs "{'apply': True, 'limit': 1}"

    # 3. apply the rest
    bench --site hr.local execute saudi_hr.scripts.rename_employees_to_employee_number.run \
        --kwargs "{'apply': True}"

    # 4. confirm nothing stale is left behind
    bench --site hr.local execute saudi_hr.scripts.rename_employees_to_employee_number.run \
        --kwargs "{'verify': True}"

    # 5. only if step 4 reports leftovers: re-point them and re-verify
    bench --site hr.local execute saudi_hr.scripts.rename_employees_to_employee_number.run \
        --kwargs "{'repair': True}"

Employees without an employee_number, and duplicated employee numbers, are left
untouched and reported.  Historical logs (Access Log, Data Import Log,
Notification Log, Deleted Document) deliberately keep the old names: they record
what the document was called when the event happened, and nothing resolves
through them.

`switch_naming=True` (a separate, explicit step) switches Employee autoname to
`field:employee_number` so future imports are named by employee number instead
of the HR-EMP- series.
"""

import re

import frappe
from frappe.model.rename_doc import rename_doc

# matches a real employee document id, but not the bare naming series "HR-EMP-"
STALE_PATTERN = "^HR-EMP-[0-9]+$"

# doctypes whose document name IS the employee name (autoname: field:employee),
# so they have to follow the employee rename as well
NAME_AFTER_EMPLOYEE = ("Saudi Employee Voice Profile",)

# audit/history columns that intentionally keep the old name
PRESERVED_REFERENCES = (
	("Access Log", "reference_document"),
	("Data Import Log", "docname"),
	("Notification Log", "document_name"),
	("Deleted Document", "deleted_name"),
)

# (doctype, column, filter column, filter values) - references that
# frappe.rename_doc() does not rewrite
MANUAL_REFERENCES = (
	("User Permission", "for_value", None, None),
	("Comment", "reference_name", "reference_doctype", ("Employee",)),
	("Version", "docname", "ref_doctype", ("Employee",) + NAME_AFTER_EMPLOYEE),
)

# naming series bookkeeping and search index - a value, not an employee reference
IGNORED_COLUMNS = (
	("Employee", "name"),
	("Employee", "naming_series"),
	("Employee", "old_parent"),
	("Series", "name"),
	("DocField", "options"),
	("Property Setter", "value"),
	("__GlobalSearch", "name"),
	("__GlobalSearch", "doctype"),
)


def is_valid_name(value):
	"""Mirrors the checks frappe.model.naming.validate_name() applies."""
	if not value or value != value.strip():
		return False
	if re.search(r"[<>]", value):
		return False
	if value == "Employee" or value.startswith("New Employee"):
		return False
	return True


def build_plan():
	"""Split every employee into rename / skip buckets. Read-only."""
	employees = frappe.get_all(
		"Employee",
		fields=["name", "employee_name", "employee_number", "employee", "status"],
		order_by="name asc",
	)

	numbers = {}
	for row in employees:
		number = (row.employee_number or "").strip()
		if number:
			numbers.setdefault(number, []).append(row.name)

	existing_names = {row.name for row in employees}
	plan = {
		"rename": [],
		"skip_no_number": [],
		"skip_duplicate": [],
		"skip_invalid": [],
		"skip_conflict": [],
		"skip_already": [],
	}

	for row in employees:
		number = (row.employee_number or "").strip()
		if not number:
			plan["skip_no_number"].append(row)
		elif not is_valid_name(number):
			plan["skip_invalid"].append((row, number))
		elif len(numbers[number]) > 1:
			plan["skip_duplicate"].append((row, number, numbers[number]))
		elif number in existing_names and number != row.name:
			plan["skip_conflict"].append((row, number))
		elif number == row.name:
			plan["skip_already"].append(row)
		else:
			plan["rename"].append((row, number))

	return plan, len(employees)


def count_manual_references(doctype, fieldname, column, values):
	"""How many rows of this kind still point at an old-style employee name."""
	if not frappe.db.table_exists(doctype):
		return "n/a"
	sql = "SELECT COUNT(*) AS `c` FROM `tab%s` WHERE `%s` REGEXP %%s" % (doctype, fieldname)
	params = [STALE_PATTERN]
	if column:
		placeholders = ", ".join(["%s"] * len(values))
		sql += " AND `%s` IN (%s)" % (column, placeholders)
		params.extend(values)
	return frappe.db.sql(sql, tuple(params), as_dict=True)[0].c


def print_plan(plan, total):
	print("")
	print("=" * 78)
	print("EMPLOYEE RENAME PLAN  (dry run - nothing was written)")
	print("=" * 78)
	print("employees in database : %s" % total)
	print("will rename           : %s" % len(plan["rename"]))
	print("skipped               : %s" % (total - len(plan["rename"])))
	print("")

	print("-- rename (%s) " % len(plan["rename"]) + "-" * 55)
	for row, number in plan["rename"]:
		print("   %-14s -> %-12s %s" % (row.name, number, row.employee_name or ""))

	for key, title in (
		("skip_no_number", "no employee_number - left unchanged"),
		("skip_duplicate", "duplicate employee_number - left unchanged"),
		("skip_invalid", "employee_number is not a usable name"),
		("skip_conflict", "employee_number is already another employee's id"),
		("skip_already", "name already equals employee_number"),
	):
		items = plan[key]
		print("")
		print("-- %s (%s) %s" % (title, len(items), "-" * 20))
		for item in items:
			row = item[0] if isinstance(item, tuple) else item
			extra = ""
			if isinstance(item, tuple):
				if key == "skip_duplicate":
					extra = "  (shares %s with %s)" % (item[1], ", ".join(item[2]))
				else:
					extra = "  (%r)" % item[1]
			print("   %-14s %s%s" % (row.name, row.employee_name or "", extra))

	print("")
	print("Also rewritten by the script (rename_doc does not cover these):")
	for doctype, fieldname, column, values in MANUAL_REFERENCES:
		print(
			"   %-16s . %-16s : %s row(s)"
			% (doctype, fieldname, count_manual_references(doctype, fieldname, column, values))
		)
	print("   %-16s . %-16s : renamed with the employee" % (NAME_AFTER_EMPLOYEE[0], "name"))
	print("")
	print("Kept as history on purpose: %s" % ", ".join("%s.%s" % ref for ref in PRESERVED_REFERENCES))
	print("=" * 78)
	print("")


def rename_named_after_employee(old, new):
	"""Follow the employee rename into docs that are named by employee."""
	followed = []
	for doctype in NAME_AFTER_EMPLOYEE:
		if not frappe.db.table_exists(doctype):
			continue
		if not frappe.db.exists(doctype, old):
			continue
		rename_doc(
			doctype,
			old,
			new,
			force=True,
			ignore_permissions=True,
			rebuild_search=False,
		)
		followed.append("%s %s -> %s" % (doctype, old, new))
	return followed


def apply_renames(limit=None):
	plan, _total = build_plan()
	queue = plan["rename"][:limit] if limit else plan["rename"]
	if not queue:
		print("Nothing to rename.")
		return []

	mapping = {row.name: number for row, number in queue}
	print("Renaming %s employee(s)..." % len(mapping))

	done, failed, followed = [], [], []
	for old, new in mapping.items():
		save_point = "rename_" + old.replace("-", "_")
		try:
			frappe.db.savepoint(save_point)
			rename_doc(
				"Employee",
				old,
				new,
				force=True,
				ignore_permissions=True,
				rebuild_search=False,
			)
			frappe.db.set_value("Employee", new, "employee", new, update_modified=False)
			followed.extend(rename_named_after_employee(old, new))
			frappe.db.commit()
			done.append((old, new))
			print("   ok   %-14s -> %s" % (old, new))
		except Exception as exc:
			frappe.db.rollback(save_point=save_point)
			failed.append((old, new, str(exc)))
			print("   FAIL %-14s -> %-12s %s" % (old, new, exc))

	# only the employees that were actually renamed
	fix_manual_references({old: new for old, new in done})
	rebuild_search()

	print("")
	print("renamed: %s   failed: %s" % (len(done), len(failed)))
	if followed:
		print("followed %s row(s) named after the employee, e.g. %s" % (len(followed), followed[0]))
	if failed:
		for old, new, error in failed:
			print("   %s -> %s : %s" % (old, new, error))
	print("Run again with {'verify': True} to confirm the result.")
	return done


def fix_manual_references(mapping):
	"""Rewrite the references frappe's rename_doc() leaves behind."""
	if not mapping:
		return
	for doctype, fieldname, column, values in MANUAL_REFERENCES:
		if not frappe.db.table_exists(doctype):
			continue
		where = "`%s` = %%s" % fieldname
		params_extra = ()
		if column:
			placeholders = ", ".join(["%s"] * len(values))
			where += " AND `%s` IN (%s)" % (column, placeholders)
			params_extra = values
		for old, new in mapping.items():
			frappe.db.sql(
				"UPDATE `tab%s` SET `%s` = %%s WHERE %s" % (doctype, fieldname, where),
				(new, old) + params_extra,
			)
	frappe.db.commit()
	print("Fixed User Permission / Comment / Version references for %s employee(s)." % len(mapping))


def rebuild_search():
	"""Rebuild the global search index so it stops serving old employee names."""
	for doctype in ("Employee",) + NAME_AFTER_EMPLOYEE:
		frappe.utils.global_search.rebuild_for_doctype(doctype)
	frappe.clear_cache()
	print("Rebuilt global search for Employee and %s." % ", ".join(NAME_AFTER_EMPLOYEE))


def rename_trail():
	"""old name -> new name, read back from the comments rename_doc() left."""
	rows = frappe.db.sql(
		"""
		SELECT reference_name, content FROM tabComment
		WHERE reference_doctype = 'Employee' AND content LIKE 'renamed from%'
		""",
		as_dict=True,
	)
	trail = {}
	for row in rows:
		names = re.findall(r">([^<>]+)<", row.content or "")
		if len(names) >= 2:
			trail[names[0]] = row.reference_name
	return trail


def scan_references():
	"""Classify every old-style name still sitting in a text column.

	Returns (problems, expected, preserved) where `problems` maps
	"Table.column" -> {old name: rows} for employees that were renamed.
	"""
	trail = rename_trail()
	kept = set(frappe.get_all("Employee", filters={"name": ["like", "HR-EMP-%"]}, pluck="name"))

	columns = frappe.db.sql(
		"""
		SELECT TABLE_NAME AS `table`, COLUMN_NAME AS `column`
		FROM information_schema.COLUMNS
		WHERE TABLE_SCHEMA = DATABASE()
		  AND DATA_TYPE IN ('char', 'varchar', 'text', 'mediumtext', 'longtext')
		  AND COLUMN_NAME NOT IN ('creation', 'modified', 'modified_by', 'owner', 'docstatus', 'idx')
		""",
		as_dict=True,
	)

	problems, expected, preserved = {}, {}, {}
	for column in columns:
		table = column["table"]
		name = column["column"]
		key = table[3:] if table.startswith("tab") else table
		if (key, name) in IGNORED_COLUMNS:
			continue
		if (key, name) in PRESERVED_REFERENCES:
			preserved["%s.%s" % (key, name)] = count_manual_references(key, name, None, None)
			continue
		try:
			found = frappe.db.sql(
				f"""
				SELECT DISTINCT `{name}` AS `value`, COUNT(*) AS `rows`
				FROM `{table}` WHERE `{name}` REGEXP %s
				GROUP BY `{name}`
				""",
				(STALE_PATTERN,),
				as_dict=True,
			)
		except Exception:
			continue
		for row in found:
			if row.value in trail:
				problems.setdefault("%s.%s" % (key, name), {})[row.value] = row.rows
			elif row.value in kept:
				expected.setdefault("%s.%s" % (key, name), {})[row.value] = row.rows

	return problems, expected, preserved, trail, kept


def verify_renames():
	problems, expected, preserved, trail, kept = scan_references()

	print("")
	print("=" * 78)
	print("EMPLOYEE RENAME VERIFICATION")
	print("=" * 78)
	print("renames recorded      : %s" % len(trail))
	print("employees still named HR-EMP-* : %s" % len(kept))
	for name in sorted(kept):
		print("   %s  (kept on purpose)" % name)
	print("")
	print("leftover links to renamed employees : %s column(s)" % len(problems))
	for key, values in sorted(problems.items()):
		print("   %-40s %s" % (key, values))
	if not problems:
		print("   none - every link follows the employee")
	print("")
	print("references to the skipped employees : %s column(s) (expected)" % len(expected))
	print("historical logs kept as-is : %s" % ", ".join("%s=%s" % kv for kv in sorted(preserved.items())))
	print("=" * 78)
	print("")
	return not problems


def repair_references():
	"""Follow up after a run: re-point anything the rename left behind."""
	problems, expected, preserved, trail, kept = scan_references()
	pending = {old: new for old, new in trail.items() if old not in kept}

	print("Re-pointing %s renamed employee name(s)..." % len(pending))
	followed = []
	for old, new in pending.items():
		try:
			followed.extend(rename_named_after_employee(old, new))
			frappe.db.commit()
		except Exception as exc:
			frappe.db.rollback()
			print("   FAIL %s -> %s : %s" % (old, new, exc))

	fix_manual_references(pending)
	rebuild_search()
	print("Repaired. Now run {'verify': True}.")


def use_employee_number_naming():
	"""Make Employee autoname use employee_number so imports stop repeating the mistake."""
	frappe.db.set_value("DocType", "Employee", "autoname", "field:employee_number")
	frappe.db.commit()
	frappe.reload_doctype("Employee", force=True)
	frappe.clear_cache()
	print("Employee autoname is now %r" % frappe.get_meta("Employee").autoname)
	print("Give every active employee an employee_number before the next import.")


def run(apply=False, limit=None, verify=False, repair=False, switch_naming=False):
	if switch_naming:
		use_employee_number_naming()
		return
	if repair:
		repair_references()
		return
	if verify:
		return verify_renames()
	if apply:
		apply_renames(limit=limit)
		return
	plan, total = build_plan()
	print_plan(plan, total)
