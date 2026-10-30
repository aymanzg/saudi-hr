
frappe.ui.form.on("Saudi Daily Attendance", {
	refresh: function(frm) {
		if (!frm.is_new() && frm.doc.employee && frm.doc.attendance_date) {
			if (frm.doc.status === "Missing" || (frm.doc.in_time && !frm.doc.out_time)) {
				frm.add_custom_button(__("Raise Disciplinary / رفع إجراء تأديبي"), function() {
					var url = "/app/disciplinary-procedure/new";
					var qs = [];
					qs.push("employee=" + encodeURIComponent(frm.doc.employee));
					qs.push("incident_date=" + encodeURIComponent(frm.doc.attendance_date));
					qs.push("violation_type=" + encodeURIComponent("Unauthorised Absence / غياب بدون إذن"));
					qs.push("reported_by=" + encodeURIComponent(frappe.session.user));
					var desc = "عدم تسجيل الخروج / Missing check-out on " + frm.doc.attendance_date + ". In Time: " + (frm.doc.in_time || "");
					qs.push("incident_description=" + encodeURIComponent(desc));
					window.open(url + "?" + qs.join("&"), "_blank");
				}, __("Actions"));
			}
		}
	}
});
