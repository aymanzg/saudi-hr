"""Drop Company User Permissions that block self-service for their own employees.

Some users were pinned to a company other than the one on their Employee record.
Because that permission applies to all doctypes, every leave/request document
(which carries a ``company`` field) failed the document-level permission check,
so the mobile portal returned "no permission". This removes only those
mismatched rows; users without an Employee record are never touched. Idempotent.
"""

from saudi_hr.install import remove_mismatched_company_user_permissions


def execute():
	removed = remove_mismatched_company_user_permissions()
	print(f"[saudi_hr] removed {removed} mismatched Company User Permission(s)")
