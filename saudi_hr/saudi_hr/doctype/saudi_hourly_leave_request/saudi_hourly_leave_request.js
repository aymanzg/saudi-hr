frappe.ui.form.on('Saudi Hourly Leave Request', {
	refresh: function(frm) {
		if (frm.doc.from_time && frm.doc.to_time && frm.doc.leave_date) {
			calc_hours(frm);
		}
	},
	leave_date: function(frm) {
		if (frm.doc.from_time && frm.doc.to_time) {
			calc_hours(frm);
		}
	},
	from_time: function(frm) {
		calc_hours(frm);
	},
	to_time: function(frm) {
		calc_hours(frm);
	}
});

function calc_hours(frm) {
	if (!frm.doc.from_time || !frm.doc.to_time || !frm.doc.leave_date) {
		return;
	}
	let start = moment(frm.doc.leave_date + ' ' + frm.doc.from_time, 'YYYY-MM-DD HH:mm:ss');
	let end = moment(frm.doc.leave_date + ' ' + frm.doc.to_time, 'YYYY-MM-DD HH:mm:ss');
	if (end.isAfter(start)) {
		let diff = end.diff(start, 'minutes');
		if (diff % 60 === 0 && diff >= 60) {
			frm.set_value('total_hours', diff / 60);
		}
	}
}
