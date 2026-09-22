# Saudi HR (ERPNext v15)

Frappe/ERPNext app for Saudi Arabian HR operations — attendance, payroll, leave, permits, and a mobile employee self-service portal.

## Features

- **Mobile Self-Service Portal** (`/mobile-attendance`) — Arabic-first, RTL, PWA-style SPA:
  - Live attendance home screen (check-in / check-out punches, live clock, Hijri date)
  - Submit **leave requests** (annual, sick, special, maternity/paternity) with subtypes, reason, and attachments
  - Submit **HR service requests** (salary / experience certificates, advance salary, loan, data update, profession modification, etc.)
  - My requests list with live status
  - Team overview, policy acknowledgements, iqama/permit tracking, payroll snapshot, recent leaves
- **Approval workflows**:
  - `HR Service Request Approval Workflow` — Draft (employee) → Pending Manager Approval → Pending HR Approval → Approved/Rejected
  - `Mobile Leave Approval Workflow` — same approval chain
- **HR Service Request** and **Mobile Leave Request** doctypes with conditional fields (dates/amount/new-value shown per request type)
- **Employee Checkin** — location-aware mobile attendance with verification features
- **Payroll** — overtime workbook parsing and Saudi monthly payroll
- **Maternity/Paternity Leave** — subtype entitlements

## Workspace

The shipped workspace includes a **طلبات الموظفين** (Employee Requests) card linking directly to both HR Service Requests and Mobile Leave Requests for quick admin review.

## Install

```bash
bench get-app saudi_hr https://github.com/aymanzg/saudi-hr.git
bench --site your-site install-app saudi_hr
```

## Tech

- Frappe Framework v15 / ERPNext
- Python, Jinja server-rendered shell + vanilla JS SPA
- SQL (Frappe ORM)