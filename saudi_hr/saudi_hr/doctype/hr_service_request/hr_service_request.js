const HR_DOCUMENTS_API = "saudi_hr.saudi_hr.hr_documents";

frappe.ui.form.on("HR Service Request", {
	refresh(frm) {
		const issued = ["GM Approved", "Completed", "Approved"].includes(frm.doc.workflow_state);
		const documents = ["salary_certificate", "employment_letter", "addressed_letter", "experience_certificate", "employee_clearance"];
		const officer = ["HR User", "HR Manager", "System Manager"].some((role) => frappe.user.has_role(role));
		if (frm.is_new() || !issued || !officer || !documents.includes(frm.doc.request_type)) return;

		const open_file = (method) => window.open(`/api/method/${HR_DOCUMENTS_API}.${method}?name=${encodeURIComponent(frm.doc.name)}`);
		frm.add_custom_button(__("Print Letter / طباعة الخطاب"), () => open_file("download_hr_document"));
		frm.add_custom_button(__("Upload Signed Copy / رفع النسخة الموقعة"), () => {
			new frappe.ui.FileUploader({
				allow_multiple: false,
				make_attachments_public: false,
				restrictions: { allowed_file_types: ["application/pdf", "image/jpeg", "image/png"] },
				on_success(file) {
					frappe
						.call("saudi_hr.saudi_hr.admin_api.save_signed_hr_document", { name: frm.doc.name, file_url: file.file_url })
						.then(() => frm.reload_doc());
				},
			});
		});
		if (frm.doc.signed_document) {
			frm.add_custom_button(__("Signed Copy / النسخة الموقعة"), () => open_file("download_signed_document"));
		}
	},
});
