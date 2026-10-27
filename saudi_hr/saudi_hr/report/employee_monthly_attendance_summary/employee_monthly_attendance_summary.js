frappe.query_reports["Employee Monthly Attendance Summary"] = {
	filters: [
		{
			fieldname: "employee",
			label: __("Employee / الموظف"),
			fieldtype: "Link",
			options: "Employee",
			reqd: 1,
			on_change: function() {
				var emp = frappe.query_report.get_filter_value("employee");
				if (!emp) return;
				frappe.db.get_value("Employee", emp, ["company", "department"], function(r) {
					if (!r) return;
					if (r.company && !frappe.query_report.get_filter_value("company")) {
						frappe.query_report.set_filter_value("company", r.company);
					}
					if (r.department && !frappe.query_report.get_filter_value("department")) {
						frappe.query_report.set_filter_value("department", r.department);
					}
				});
			}
		},
		{
			fieldname: "from_date",
			label: __("From Date / من تاريخ"),
			fieldtype: "Date",
			reqd: 1,
			default: frappe.datetime.month_start()
		},
		{
			fieldname: "to_date",
			label: __("To Date / إلى تاريخ"),
			fieldtype: "Date",
			reqd: 1,
			default: frappe.datetime.month_end()
		},
		{
			fieldname: "company",
			label: __("Company / الشركة"),
			fieldtype: "Link",
			options: "Company"
		},
		{
			fieldname: "department",
			label: __("Department / القسم"),
			fieldtype: "Link",
			options: "Department"
		}
	],

	onload: function(report) {
		if (!frappe.query_report.get_filter_value("from_date")) {
			frappe.query_report.set_filter_value("from_date", frappe.datetime.month_start());
		}
		if (!frappe.query_report.get_filter_value("to_date")) {
			frappe.query_report.set_filter_value("to_date", frappe.datetime.month_end());
		}
	}
};
