frappe.provide("saudi_hr");

frappe.pages["saudi-self-service"].on_page_load = function (wrapper) {
	new saudi_hr.SelfServicePortal(wrapper);
};

saudi_hr.SelfServicePortal = class SelfServicePortal {
	constructor(wrapper) {
		this.wrapper = wrapper;
		this.data = null;
		this.page = frappe.ui.make_app_page({ parent: wrapper, title: "بوابة الموظف الذاتية", single_column: true });
		this.ensureStyles();
		this.page.set_primary_action("تحديث ملفي", () => this.load(), "refresh");
		if ((frappe.user_roles || []).some((role) => ["HR Manager", "HR User", "System Manager"].includes(role))) {
			this.page.add_menu_item("مركز العمليات المؤسسي", () => this.open("/app/saudi-enterprise-center"));
		}
		this.renderLoading();
		this.load();
	}

	esc(value) { return frappe.utils.escape_html(String(value ?? "")); }
	money(value) { return new Intl.NumberFormat("ar-SA", { style: "currency", currency: "SAR", maximumFractionDigits: 2 }).format(Number(value || 0)); }

	getSvgIcon(name, color = "currentColor", size = 22) {
		const icons = {
			clock: `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>`,
			palm: `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 8c0-2.76-2.24-5-5-5s-5 2.24-5 5c0 2.4 1.7 4.41 4 4.88V21h2v-8.12c2.3-.47 4-2.48 4-4.88z"/><path d="M13 7.14C15.32 7.6 17 9.6 17 12c0 2.4-1.68 4.4-4 4.86"/><path d="M17 11.14C19.32 11.6 21 13.6 21 16"/></svg>`,
			calendar: `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>`,
			list: `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>`,
			user: `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>`,
			bell: `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>`,
			file: `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>`,
			wallet: `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 12V8H6a2 2 0 0 1-2-2c0-1.1.9-2 2-2h12v4"/><path d="M4 6v12a2 2 0 0 0 2 2h14v-4"/><path d="M18 12a2 2 0 0 0 0 4h4v-4z"/></svg>`,
			chevron: `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg>`,
			menu: `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="18" x2="21" y2="18"/></svg>`,
			checkCircle: `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>`,
			leaf: `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 20A7 7 0 0 1 9.8 6.1C15.5 5 17 4.48 19 2c1 2 2 4.18 2 8 0 5.5-4.78 10-10 10Z"/><path d="M2 21c0-3 1.85-5.36 5.08-6C9.5 14.52 12 13 13 12"/></svg>`,
			firstaid: `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 2h8a2 2 0 0 1 2 2v16a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z"/><line x1="12" y1="8" x2="12" y2="16"/><line x1="8" y1="12" x2="16" y2="12"/></svg>`,
			home: `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>`
		};
		return icons[name] || icons.file;
	}

	ensureStyles() {
		if (document.getElementById("saudi-self-service-style")) return;
		const style = document.createElement("style");
		style.id = "saudi-self-service-style";
		style.textContent = `
			:root {
				--app-primary: #0b5d4b;
				--app-bg: #f8faf7;
				--card-bg: #ffffff;
				--text-main: #1f2937;
				--text-muted: #6b7280;
				--border-color: #f0f3f1;
			}
			.saudi-app {
				direction: rtl;
				text-align: right;
				font-family: "Tajawal", "Noto Sans Arabic", -apple-system, sans-serif;
				background-color: var(--app-bg);
				min-height: 100vh;
				padding: 0 0 90px;
				color: var(--text-main);
				box-sizing: border-box;
				max-width: 760px;
				margin: 0 auto;
			}
			.saudi-app *, .saudi-app *::before, .saudi-app *::after {
				box-sizing: border-box;
			}

			/* Top Bar Header */
			.saudi-topbar {
				display: flex;
				align-items: center;
				justify-content: space-between;
				padding: 14px 18px;
				background: #ffffff;
				border-bottom: 1px solid var(--border-color);
				position: sticky;
				top: 0;
				z-index: 50;
			}
			.saudi-topbar__profile {
				display: flex;
				align-items: center;
				gap: 10px;
			}
			.saudi-topbar__avatar {
				width: 44px;
				height: 44px;
				border-radius: 50%;
				background: #e5e7eb;
				display: flex;
				align-items: center;
				justify-content: center;
				color: #4b5563;
				font-weight: bold;
				overflow: hidden;
			}
			.saudi-topbar__avatar img {
				width: 100%;
				height: 100%;
				object-fit: cover;
			}
			.saudi-topbar__user-info h4 {
				margin: 0;
				font-size: 15px;
				font-weight: 800;
				color: var(--text-main);
				display: flex;
				align-items: center;
				gap: 4px;
			}
			.saudi-topbar__user-info span {
				font-size: 12px;
				color: var(--text-muted);
			}
			.saudi-topbar__icon-btn {
				width: 42px;
				height: 42px;
				border-radius: 50%;
				background: #f3f4f6;
				display: flex;
				align-items: center;
				justify-content: center;
				position: relative;
				cursor: pointer;
				border: none;
				transition: background 0.2s;
			}
			.saudi-topbar__icon-btn:hover {
				background: #e5e7eb;
			}
			.saudi-topbar__badge {
				position: absolute;
				top: 3px;
				right: 3px;
				background: #ef4444;
				color: #ffffff;
				font-size: 10px;
				font-weight: 800;
				width: 17px;
				height: 17px;
				border-radius: 50%;
				display: flex;
				align-items: center;
				justify-content: center;
				border: 2px solid #ffffff;
			}

			/* Hero Banner */
			.saudi-hero {
				margin: 16px 18px 18px;
				padding: 22px 24px;
				background: linear-gradient(135deg, #f0f7f4 0%, #e3f2ea 100%);
				border-radius: 20px;
				display: flex;
				align-items: center;
				justify-content: space-between;
				position: relative;
				overflow: hidden;
				border: 1px solid #e1efe7;
			}
			.saudi-hero__text h2 {
				margin: 0 0 6px;
				font-size: 21px;
				font-weight: 800;
				color: #0b5d4b;
				display: flex;
				align-items: center;
				gap: 6px;
			}
			.saudi-hero__text p {
				margin: 0;
				font-size: 13px;
				color: #4b5563;
				line-height: 1.5;
			}
			.saudi-hero__decor {
				width: 90px;
				height: 70px;
				opacity: 0.85;
				display: flex;
				align-items: center;
				justify-content: center;
			}

			/* Quick Actions Grid (8 Cards) */
			.saudi-grid-actions {
				display: grid;
				grid-template-columns: repeat(4, 1fr);
				gap: 12px;
				padding: 0 18px 18px;
			}
			.saudi-action-card {
				background: #ffffff;
				border: 1px solid var(--border-color);
				border-radius: 18px;
				padding: 16px 8px 14px;
				display: flex;
				flex-direction: column;
				align-items: center;
				justify-content: center;
				cursor: pointer;
				transition: all 0.2s ease;
				position: relative;
				box-shadow: 0 2px 8px rgba(0,0,0,0.02);
			}
			.saudi-action-card:hover {
				transform: translateY(-3px);
				box-shadow: 0 8px 20px rgba(0,0,0,0.06);
				border-color: #cbd5e1;
			}
			.saudi-action-card__icon {
				width: 48px;
				height: 48px;
				border-radius: 14px;
				display: flex;
				align-items: center;
				justify-content: center;
				margin-bottom: 10px;
				position: relative;
			}
			.saudi-action-card__badge {
				position: absolute;
				top: -4px;
				left: -4px;
				background: #ef4444;
				color: #ffffff;
				font-size: 10px;
				font-weight: 800;
				width: 18px;
				height: 18px;
				border-radius: 50%;
				display: flex;
				align-items: center;
				justify-content: center;
				border: 2px solid #ffffff;
			}
			.saudi-action-card__title {
				font-size: 12px;
				font-weight: 700;
				color: #374151;
				text-align: center;
				margin-bottom: 4px;
			}
			.saudi-action-card__arrow {
				color: #9ca3af;
				margin-top: 2px;
				transform: rotate(180deg);
			}

			/* Middle Widgets Row */
			.saudi-widgets-row {
				display: grid;
				grid-template-columns: 1.15fr 0.85fr;
				gap: 14px;
				padding: 0 18px 18px;
			}
			.saudi-widget {
				background: #ffffff;
				border: 1px solid var(--border-color);
				border-radius: 20px;
				padding: 16px 18px;
				box-shadow: 0 2px 8px rgba(0,0,0,0.02);
			}
			.saudi-widget__header {
				display: flex;
				align-items: center;
				justify-content: space-between;
				margin-bottom: 14px;
			}
			.saudi-widget__title {
				display: flex;
				align-items: center;
				gap: 8px;
				font-size: 15px;
				font-weight: 800;
				color: var(--text-main);
			}
			.saudi-widget__link {
				font-size: 12px;
				color: #6b7280;
				text-decoration: none;
				display: flex;
				align-items: center;
				gap: 2px;
				font-weight: 600;
				cursor: pointer;
			}
			.saudi-widget__link:hover {
				color: var(--app-primary);
			}

			/* Leave Balance Widget Content */
			.saudi-leave-body {
				display: flex;
				align-items: center;
				gap: 16px;
			}
			.saudi-donut-chart {
				position: relative;
				width: 100px;
				height: 100px;
				flex-shrink: 0;
			}
			.saudi-donut-chart svg {
				width: 100%;
				height: 100%;
				transform: rotate(-90deg);
			}
			.saudi-donut-chart__center {
				position: absolute;
				top: 50%;
				left: 50%;
				transform: translate(-50%, -50%);
				text-align: center;
			}
			.saudi-donut-chart__number {
				font-size: 22px;
				font-weight: 900;
				color: #0b5d4b;
				line-height: 1;
			}
			.saudi-donut-chart__sub {
				font-size: 9px;
				color: var(--text-muted);
				font-weight: 700;
				margin-top: 3px;
			}
			.saudi-leave-list {
				display: flex;
				flex-direction: column;
				gap: 7px;
				width: 100%;
			}
			.saudi-leave-item {
				display: flex;
				align-items: center;
				justify-content: space-between;
				font-size: 12px;
				color: #4b5563;
			}
			.saudi-leave-item__label {
				display: flex;
				align-items: center;
				gap: 6px;
			}
			.saudi-leave-item__dot {
				width: 8px;
				height: 8px;
				border-radius: 50%;
			}
			.saudi-leave-item__count {
				font-weight: 800;
				color: var(--text-main);
			}

			/* Attendance Check-in Widget Content */
			.saudi-attendance-body {
				display: flex;
				flex-direction: column;
				align-items: flex-start;
				gap: 10px;
			}
			.saudi-status-badge {
				display: inline-flex;
				align-items: center;
				gap: 6px;
				padding: 5px 12px;
				background: #dcfce7;
				color: #15803d;
				border-radius: 999px;
				font-size: 12px;
				font-weight: 800;
			}
			.saudi-attendance-time {
				font-size: 26px;
				font-weight: 900;
				color: var(--text-main);
				margin: 4px 0 2px;
			}
			.saudi-attendance-date {
				font-size: 11px;
				color: var(--text-muted);
				display: flex;
				align-items: center;
				gap: 4px;
			}
			.saudi-attendance-btn {
				margin-top: 6px;
				width: 100%;
				padding: 9px;
				background: #f3f4f6;
				border: none;
				border-radius: 12px;
				color: #4b5563;
				font-size: 12px;
				font-weight: 700;
				cursor: pointer;
				display: flex;
				align-items: center;
				justify-content: center;
				gap: 4px;
				transition: background 0.2s;
			}
			.saudi-attendance-btn:hover {
				background: #e5e7eb;
			}

			/* Recent Requests Widget */
			.saudi-requests-widget {
				margin: 0 18px 18px;
				background: #ffffff;
				border: 1px solid var(--border-color);
				border-radius: 20px;
				padding: 16px 18px;
				box-shadow: 0 2px 8px rgba(0,0,0,0.02);
			}
			.saudi-requests-list {
				display: flex;
				flex-direction: column;
				gap: 10px;
				margin-top: 12px;
			}
			.saudi-request-row {
				display: flex;
				align-items: center;
				justify-content: space-between;
				padding: 12px 14px;
				background: #f9fafb;
				border: 1px solid #f0f2f5;
				border-radius: 14px;
				cursor: pointer;
				transition: all 0.2s;
			}
			.saudi-request-row:hover {
				background: #ffffff;
				border-color: #cbd5e1;
				box-shadow: 0 4px 12px rgba(0,0,0,0.03);
			}
			.saudi-request-row__right {
				display: flex;
				align-items: center;
				gap: 12px;
			}
			.saudi-request-row__icon {
				width: 40px;
				height: 40px;
				border-radius: 12px;
				background: #e0f2fe;
				display: flex;
				align-items: center;
				justify-content: center;
			}
			.saudi-request-row__info strong {
				display: block;
				font-size: 13px;
				color: var(--text-main);
			}
			.saudi-request-row__info span {
				font-size: 11px;
				color: var(--text-muted);
			}
			.saudi-request-row__left {
				display: flex;
				align-items: center;
				gap: 10px;
			}
			.saudi-badge {
				padding: 4px 10px;
				border-radius: 999px;
				font-size: 11px;
				font-weight: 800;
			}
			.saudi-badge--approved { background: #dcfce7; color: #15803d; }
			.saudi-badge--pending { background: #fef3c7; color: #b45309; }
			.saudi-badge--rejected { background: #fee2e2; color: #b91c1c; }

			/* Motivational Banner */
			.saudi-banner {
				margin: 0 18px 18px;
				padding: 14px 18px;
				background: linear-gradient(135deg, #f3f7f4 0%, #e9f2eb 100%);
				border: 1px solid #e1efe7;
				border-radius: 16px;
				display: flex;
				align-items: center;
				justify-content: space-between;
			}
			.saudi-banner__content {
				display: flex;
				align-items: center;
				gap: 12px;
			}
			.saudi-banner__img {
				width: 44px;
				height: 44px;
				border-radius: 10px;
				background: #ffffff;
				display: flex;
				align-items: center;
				justify-content: center;
				color: #0b5d4b;
			}
			.saudi-banner__text strong {
				display: block;
				font-size: 13px;
				color: #0b5d4b;
			}
			.saudi-banner__text span {
				font-size: 11px;
				color: #4b5563;
			}

			/* Bottom Navbar */
			.saudi-bottom-nav {
				position: fixed;
				bottom: 0;
				left: 50%;
				transform: translateX(-50%);
				width: 100%;
				max-width: 760px;
				background: #ffffff;
				border-top: 1px solid #e5e7eb;
				display: flex;
				align-items: center;
				justify-content: space-around;
				padding: 8px 0;
				z-index: 100;
				box-shadow: 0 -4px 20px rgba(0,0,0,0.05);
			}
			.saudi-nav-item {
				display: flex;
				flex-direction: column;
				align-items: center;
				gap: 3px;
				color: #6b7280;
				font-size: 11px;
				font-weight: 700;
				text-decoration: none;
				cursor: pointer;
				padding: 4px 12px;
				border-radius: 8px;
				transition: color 0.2s;
			}
			.saudi-nav-item--active {
				color: #0b5d4b;
			}
			.saudi-nav-item--active::after {
				content: "";
				display: block;
				width: 16px;
				height: 3px;
				background: #0b5d4b;
				border-radius: 999px;
				margin-top: 1px;
			}

			@media (max-width: 650px) {
				.saudi-widgets-row {
					grid-template-columns: 1fr;
				}
				.saudi-grid-actions {
					grid-template-columns: repeat(4, 1fr);
					gap: 8px;
				}
				.saudi-action-card {
					padding: 12px 4px;
				}
				.saudi-action-card__icon {
					width: 42px;
					height: 42px;
				}
				.saudi-action-card__title {
					font-size: 11px;
				}
			}
		`;
		document.head.appendChild(style);
	}

	renderLoading() {
		this.page.body.html(`
			<main class="saudi-app" aria-busy="true">
				<div style="padding: 40px; text-align: center; color: #6b7280; font-weight: bold;">
					جارٍ تحميل بوابة الموظف الذاتية...
				</div>
			</main>
		`);
	}

	async load() {
		try {
			const response = await frappe.call({ method: "saudi_hr.saudi_hr.enterprise_operations.get_self_service_portal" });
			this.data = response.message || {};
			this.render();
		} catch (error) {
			this.page.body.html(`
				<main class="saudi-app">
					<div style="padding: 40px; text-align: center; color: #ef4444; font-weight: bold;">
						تعذر تحميل البوابة. يرجى إعادة المحاولة.
						<br><br>
						<button class="saudi-attendance-btn" style="max-width:200px; margin:0 auto;" data-retry>إعادة المحاولة</button>
					</div>
				</main>
			`);
			this.page.body.find("[data-retry]").on("click", () => this.load());
		}
	}

	render() {
		const d = this.data;
		if (!d.employee) return this.renderUnlinked(d);
		const e = d.employee;
		const lb = d.leave_balance || { remaining_days: 18, annual: 18, sick: 5, marriage: 3, bereavement: 1, other: 2 };
		const att = d.attendance_status || { is_present: true, status_label: "حاضر الآن", time: "08:05 ص", date_hijri: "الأحد 28 صفر 1447 هـ" };
		const actions = d.quick_actions || [];
		const requests = d.recent_requests || [];

		// Header HTML
		const headerHtml = `
			<header class="saudi-topbar">
				<div class="saudi-topbar__profile">
					<div class="saudi-topbar__avatar">
						${e.image ? `<img src="${this.esc(e.image)}" alt="Profile">` : this.esc((e.employee_name || "A")[0])}
					</div>
					<div class="saudi-topbar__user-info">
						<h4>${this.esc(e.employee_name || "أحمد محمد علي")} <span>▾</span></h4>
						<span>${this.esc(e.designation || "موظف")}</span>
					</div>
				</div>
				<div style="display:flex; align-items:center; gap:8px;">
					<button class="saudi-topbar__icon-btn" data-route="/app/policy-acknowledgement">
						${this.getSvgIcon("bell", "#374151", 20)}
						<span class="saudi-topbar__badge">3</span>
					</button>
					<button class="saudi-topbar__icon-btn" data-route="/app">
						${this.getSvgIcon("menu", "#374151", 20)}
					</button>
				</div>
			</header>
		`;

		// Hero Banner HTML
		const heroHtml = `
			<section class="saudi-hero">
				<div class="saudi-hero__text">
					<h2>مرحباً، ${this.esc(e.employee_name || "أحمد محمد علي")} ☀️</h2>
					<p>نتمنى لك يوماً مليئاً بالإنجاز والنجاح</p>
				</div>
				<div class="saudi-hero__decor">
					${this.getSvgIcon("leaf", "#0b5d4b", 54)}
				</div>
			</section>
		`;

		// Quick Actions HTML (8 Cards)
		const actionCardsHtml = actions.map(act => `
			<div class="saudi-action-card" data-route="${this.esc(act.route)}">
				<div class="saudi-action-card__icon" style="background:${act.bg_color || '#f3e8ff'}; color:${act.icon_color || '#7e22ce'};">
					${this.getSvgIcon(act.icon || "file", act.icon_color || "#7e22ce", 24)}
					${act.badge ? `<span class="saudi-action-card__badge">${act.badge}</span>` : ""}
				</div>
				<span class="saudi-action-card__title">${this.esc(act.label_ar)}</span>
				<span class="saudi-action-card__arrow">${this.getSvgIcon("chevron", "#9ca3af", 14)}</span>
			</div>
		`).join("");

		// Leave Donut Progress (SVG Circle calculations)
		const radius = 38;
		const circumference = 2 * Math.PI * radius;
		const percent = Math.min(100, Math.max(0, (lb.remaining_days / 30) * 100));
		const strokeDashoffset = circumference - (percent / 100) * circumference;

		// Widgets HTML
		const widgetsHtml = `
			<section class="saudi-widgets-row">
				<!-- Leave Balance Widget -->
				<div class="saudi-widget">
					<div class="saudi-widget__header">
						<div class="saudi-widget__title">
							${this.getSvgIcon("palm", "#0b5d4b", 20)}
							<span>رصيد الإجازات</span>
						</div>
						<a class="saudi-widget__link" data-route="/app/saudi-annual-leave">عرض الكل ‹</a>
					</div>
					<div class="saudi-leave-body">
						<div class="saudi-donut-chart">
							<svg viewBox="0 0 100 100">
								<circle cx="50" cy="50" r="${radius}" fill="transparent" stroke="#e2e8f0" stroke-width="9"/>
								<circle cx="50" cy="50" r="${radius}" fill="transparent" stroke="#0b5d4b" stroke-width="9" stroke-dasharray="${circumference}" stroke-dashoffset="${strokeDashoffset}" stroke-linecap="round"/>
							</svg>
							<div class="saudi-donut-chart__center">
								<div class="saudi-donut-chart__number">${lb.remaining_days}</div>
								<div class="saudi-donut-chart__sub">يوم متبقي</div>
							</div>
						</div>
						<div class="saudi-leave-list">
							<div class="saudi-leave-item">
								<div class="saudi-leave-item__label">
									<span class="saudi-leave-item__dot" style="background:#10b981;"></span>
									<span>إجازة سنوية</span>
								</div>
								<span class="saudi-leave-item__count">${lb.annual}</span>
							</div>
							<div class="saudi-leave-item">
								<div class="saudi-leave-item__label">
									<span class="saudi-leave-item__dot" style="background:#3b82f6;"></span>
									<span>إجازة مرضية</span>
								</div>
								<span class="saudi-leave-item__count">${lb.sick}</span>
							</div>
							<div class="saudi-leave-item">
								<div class="saudi-leave-item__label">
									<span class="saudi-leave-item__dot" style="background:#a855f7;"></span>
									<span>إجازة زواج</span>
								</div>
								<span class="saudi-leave-item__count">${lb.marriage}</span>
							</div>
							<div class="saudi-leave-item">
								<div class="saudi-leave-item__label">
									<span class="saudi-leave-item__dot" style="background:#9ca3af;"></span>
									<span>إجازة وفاة</span>
								</div>
								<span class="saudi-leave-item__count">${lb.bereavement}</span>
							</div>
							<div class="saudi-leave-item">
								<div class="saudi-leave-item__label">
									<span class="saudi-leave-item__dot" style="background:#cbd5e1;"></span>
									<span>إجازات أخرى</span>
								</div>
								<span class="saudi-leave-item__count">${lb.other}</span>
							</div>
						</div>
					</div>
				</div>

				<!-- Attendance Checkin Widget -->
				<div class="saudi-widget">
					<div class="saudi-widget__header">
						<div class="saudi-widget__title">
							${this.getSvgIcon("clock", "#0b5d4b", 20)}
							<span>تسجيل الدوام</span>
						</div>
					</div>
					<div class="saudi-attendance-body">
						<div class="saudi-status-badge">
							${this.getSvgIcon("checkCircle", "#15803d", 16)}
							<span>${this.esc(att.status_label)}</span>
						</div>
						<div class="saudi-attendance-time">${this.esc(att.time)}</div>
						<div class="saudi-attendance-date">
							${this.getSvgIcon("calendar", "#6b7280", 14)}
							<span>${this.esc(att.date_hijri)}</span>
						</div>
						<button class="saudi-attendance-btn" data-route="/mobile-attendance">
							<span>عرض التفاصيل</span>
							<span>‹</span>
						</button>
					</div>
				</div>
			</section>
		`;

		// Recent Requests HTML
		const requestRowsHtml = requests.map(req => {
			const badgeClass = req.status_code === 'approved' ? 'saudi-badge--approved' : (req.status_code === 'rejected' ? 'saudi-badge--rejected' : 'saudi-badge--pending');
			const iconBg = req.icon === 'palm' ? '#dcfce7' : (req.icon === 'clock' ? '#e0f2fe' : (req.icon === 'wallet' ? '#ccfbf1' : '#fef3c7'));
			const iconColor = req.icon === 'palm' ? '#15803d' : (req.icon === 'clock' ? '#0369a1' : (req.icon === 'wallet' ? '#0d9488' : '#d97706'));

			return `
				<div class="saudi-request-row" data-route="${this.esc(req.route)}">
					<div class="saudi-request-row__right">
						<div class="saudi-request-row__icon" style="background:${iconBg};">
							${this.getSvgIcon(req.icon || "file", iconColor, 20)}
						</div>
						<div class="saudi-request-row__info">
							<strong>${this.esc(req.title)}</strong>
							<span>${this.esc(req.dates)}</span>
						</div>
					</div>
					<div class="saudi-request-row__left">
						<span class="saudi-badge ${badgeClass}">${this.esc(req.status)}</span>
						<span style="color:#9ca3af; transform:rotate(180deg); display:flex;">${this.getSvgIcon("chevron", "#9ca3af", 14)}</span>
					</div>
				</div>
			`;
		}).join("");

		const requestsHtml = `
			<section class="saudi-requests-widget">
				<div class="saudi-widget__header">
					<div class="saudi-widget__title">
						${this.getSvgIcon("list", "#0b5d4b", 20)}
						<span>طلباتي الأخيرة</span>
					</div>
					<a class="saudi-widget__link" data-route="/app/saudi-annual-leave">عرض الكل ‹</a>
				</div>
				<div class="saudi-requests-list">
					${requestRowsHtml}
				</div>
			</section>
		`;

		// Motivational Banner HTML
		const bannerHtml = `
			<section class="saudi-banner">
				<div class="saudi-banner__content">
					<div class="saudi-banner__img">
						${this.getSvgIcon("leaf", "#0b5d4b", 24)}
					</div>
					<div class="saudi-banner__text">
						<strong>معاً نحو بيئة عمل أفضل</strong>
						<span>نحن هنا لدعمك في رحلتك المهنية</span>
					</div>
				</div>
				<span style="color:#9ca3af; transform:rotate(180deg); display:flex;">${this.getSvgIcon("chevron", "#9ca3af", 16)}</span>
			</section>
		`;

		// Bottom Navbar HTML
		const navbarHtml = `
			<nav class="saudi-bottom-nav">
				<a class="saudi-nav-item saudi-nav-item--active" data-route="/app/saudi-self-service">
					${this.getSvgIcon("home", "#0b5d4b", 20)}
					<span>الرئيسية</span>
				</a>
				<a class="saudi-nav-item" data-route="/app/saudi-annual-leave">
					${this.getSvgIcon("list", "#6b7280", 20)}
					<span>طلباتي</span>
				</a>
				<a class="saudi-nav-item" data-route="/app/saudi-annual-leave">
					${this.getSvgIcon("palm", "#6b7280", 20)}
					<span>الإجازات</span>
				</a>
				<a class="saudi-nav-item" data-route="/mobile-attendance">
					${this.getSvgIcon("clock", "#6b7280", 20)}
					<span>الحضور</span>
				</a>
				<a class="saudi-nav-item" data-route="/app/employee/${e.name}">
					${this.getSvgIcon("user", "#6b7280", 20)}
					<span>المزيد</span>
				</a>
			</nav>
		`;

		// Combine Main Assembly
		this.page.body.html(`
			<main class="saudi-app">
				${headerHtml}
				${heroHtml}
				<section class="saudi-grid-actions">
					${actionCardsHtml}
				</section>
				${widgetsHtml}
				${requestsHtml}
				${bannerHtml}
				${navbarHtml}
			</main>
		`);

		this.bind();
	}

	renderUnlinked(d) {
		this.page.body.html(`
			<main class="saudi-app">
				<div style="padding: 40px; text-align: center; background:#fff; margin:20px; border-radius:16px;">
					<h2 style="color:#b54432;">حسابك غير مربوط بملف موظف</h2>
					<p style="color:#6b7280;">${this.esc(d.message_ar || "اطلب من الموارد البشرية ربط حسابك بملف الموظف.")}</p>
					<button class="saudi-attendance-btn" style="max-width:220px; margin:16px auto;" data-route="${this.esc(d.support_route || "/app/employee")}">فتح ملفات الموظفين</button>
				</div>
			</main>
		`);
		this.bind();
	}

	bind() {
		this.page.body.find("[data-route]").on("click", (event) => {
			const route = $(event.currentTarget).attr("data-route");
			this.open(route);
		});
	}

	open(route) {
		if (!route) return;
		if (route.startsWith("/app/")) frappe.set_route(route.replace(/^\/app\//, "").split("/"));
		else window.location.assign(route);
	}
};
