import frappe
from frappe.model.document import Document

from saudi_hr.saudi_hr.location_utils import build_geolocation, resolve_location_reference


class AttendanceLocation(Document):
	def validate(self):
		self._validate_single_active_location_per_branch()
		resolved = resolve_location_reference(
			plus_code=self.plus_code,
			latitude=self.latitude,
			longitude=self.longitude,
			geolocation=self.geolocation,
			location_input_method=self.location_input_method,
			address_reference=self.address_reference,
		)
		self.latitude = resolved["latitude"]
		self.longitude = resolved["longitude"]
		self.plus_code = resolved["plus_code"]
		self.location_source = resolved["location_source"]
		self.geolocation = build_geolocation(self.latitude, self.longitude, self.allowed_radius_meters)

	def _validate_single_active_location_per_branch(self):
		if not (self.branch and self.is_active):
			return

		other_active = frappe.db.get_value(
			"Attendance Location",
			{"branch": self.branch, "is_active": 1, "name": ["!=", self.name]},
			"name",
		)
		if other_active:
			frappe.throw(
				frappe._(
					"Branch {0} already has an active check-in location ({1}). "
					"Mobile attendance can only match one active location per branch — "
					"deactivate the other location first, or update it instead of creating a new one. / "
					"الفرع {0} لديه بالفعل موقع حضور نشط ({1}). لا يمكن لتطبيق الحضور مطابقة أكثر من موقع نشط واحد لكل فرع — "
					"يرجى إلغاء تفعيل الموقع الآخر أولاً، أو تعديله بدلاً من إنشاء موقع جديد."
				).format(self.branch, other_active)
			)

	def on_update(self):
		if self.latitude and self.longitude:
			self.geolocation = build_geolocation(self.latitude, self.longitude, self.allowed_radius_meters)
			frappe.db.set_value(
				"Attendance Location",
				self.name,
				{
					"geolocation": self.geolocation,
					"plus_code": self.plus_code,
					"location_source": self.location_source,
				},
			)

	@frappe.whitelist(methods=["POST"])
	def set_geolocation(self):
		self.geolocation = build_geolocation(self.latitude, self.longitude, self.allowed_radius_meters)
		return self.geolocation

	@frappe.whitelist(methods=["POST"])
	def resolve_reference(self):
		resolved = resolve_location_reference(
			plus_code=self.plus_code,
			latitude=self.latitude,
			longitude=self.longitude,
			geolocation=self.geolocation,
			location_input_method=self.location_input_method,
			address_reference=self.address_reference,
		)
		self.update(resolved)
		self.geolocation = build_geolocation(self.latitude, self.longitude, self.allowed_radius_meters)
		return {
			**resolved,
			"geolocation": self.geolocation,
		}
