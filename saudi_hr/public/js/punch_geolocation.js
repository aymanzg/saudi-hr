/*
 * Location lookup for the mobile punch (check-in / check-out).
 *
 * Every geolocation failure used to be shown as "please allow location
 * permission", so staff who had granted it were told to grant it again
 * when the real problem was a timeout indoors, the phone's location
 * service being off, or the page being opened over plain http.
 *
 * This module tells those cases apart and retries the ones a retry can
 * fix. It has no DOM dependencies so it can be tested under Node.
 */
(function(root) {
	"use strict";

	// error kinds; each has a matching "gps_err_<kind>" label in saudi_portal.js
	var KIND = {
		DENIED: "denied",
		UNAVAILABLE: "unavailable",
		TIMEOUT: "timeout",
		INSECURE: "insecure",
		UNSUPPORTED: "unsupported"
	};

	// first try: precise fix, a recent cached one is fine
	// second try: network/wifi position, which works indoors where GPS often does not
	var DEFAULT_ATTEMPTS = [
		{ enableHighAccuracy: true, timeout: 15000, maximumAge: 60000 },
		{ enableHighAccuracy: false, timeout: 20000, maximumAge: 120000 }
	];

	// some iOS/webview builds never call either callback; give up a bit after
	// the browser's own timeout so the employee is not left on "Locating..."
	var WATCHDOG_GRACE_MS = 3000;

	function classifyError(err) {
		var code = err && err.code;
		// PositionError constants: 1 PERMISSION_DENIED, 2 POSITION_UNAVAILABLE, 3 TIMEOUT
		if (code === 1) {
			// Chrome reports an insecure origin as PERMISSION_DENIED with this message
			var msg = String((err && err.message) || "").toLowerCase();
			if (msg.indexOf("secure origin") !== -1 || msg.indexOf("secure context") !== -1) return KIND.INSECURE;
			return KIND.DENIED;
		}
		if (code === 3) return KIND.TIMEOUT;
		return KIND.UNAVAILABLE;
	}

	function isRetryable(kind) {
		return kind === KIND.TIMEOUT || kind === KIND.UNAVAILABLE;
	}

	/*
	 * env: { geolocation, isSecureContext, permissions, setTimeout, clearTimeout }
	 *   (defaults to the browser globals), plus optional onRetry(attemptIndex, kind)
	 * done(err, result):
	 *   success -> done(null, { latitude, longitude, accuracy, attempt })
	 *   failure -> done({ kind, code, message, attempts })
	 */
	function locate(env, done, attempts) {
		env = env || {};
		attempts = attempts || DEFAULT_ATTEMPTS;
		var nav = root.navigator || {};
		var geo = "geolocation" in env ? env.geolocation : nav.geolocation;
		var secure = "isSecureContext" in env ? env.isSecureContext : root.isSecureContext;
		var perms = "permissions" in env ? env.permissions : nav.permissions;
		var setT = env.setTimeout || root.setTimeout;
		var clearT = env.clearTimeout || root.clearTimeout;
		var finished = false;

		function finish(err, res) {
			if (finished) return;
			finished = true;
			done(err, res);
		}

		if (secure === false) {
			return finish({ kind: KIND.INSECURE, code: null, message: "insecure context", attempts: 0 });
		}
		if (!geo || typeof geo.getCurrentPosition !== "function") {
			return finish({ kind: KIND.UNSUPPORTED, code: null, message: "geolocation unsupported", attempts: 0 });
		}

		function tryAttempt(i) {
			var opts = attempts[i];
			var settled = false;
			var watchdog = setT(function() {
				if (settled) return;
				settled = true;
				onError({ code: 3, message: "watchdog timeout" });
			}, opts.timeout + WATCHDOG_GRACE_MS);

			function onError(err) {
				var kind = classifyError(err);
				if (isRetryable(kind) && i + 1 < attempts.length) {
					if (typeof env.onRetry === "function") env.onRetry(i + 1, kind);
					return tryAttempt(i + 1);
				}
				finish({ kind: kind, code: err && err.code, message: (err && err.message) || "", attempts: i + 1 });
			}

			try {
				geo.getCurrentPosition(function(pos) {
					if (settled) return;
					settled = true;
					clearT(watchdog);
					finish(null, {
						latitude: pos.coords.latitude,
						longitude: pos.coords.longitude,
						accuracy: pos.coords.accuracy,
						attempt: i + 1
					});
				}, function(err) {
					if (settled) return;
					settled = true;
					clearT(watchdog);
					onError(err);
				}, opts);
			} catch (e) {
				if (settled) return;
				settled = true;
				clearT(watchdog);
				onError({ code: 2, message: String(e && e.message || e) });
			}
		}

		// if the browser already knows the site is blocked, say so without
		// waiting on a request that will be refused anyway
		if (perms && typeof perms.query === "function") {
			var started = false;
			var start = function() { if (!started) { started = true; tryAttempt(0); } };
			try {
				perms.query({ name: "geolocation" }).then(function(status) {
					if (status && status.state === "denied") {
						started = true;
						finish({ kind: KIND.DENIED, code: 1, message: "permission state denied", attempts: 0 });
					} else {
						start();
					}
				}, start);
			} catch (e) {
				start();
			}
			return;
		}
		tryAttempt(0);
	}

	var api = {
		KIND: KIND,
		DEFAULT_ATTEMPTS: DEFAULT_ATTEMPTS,
		WATCHDOG_GRACE_MS: WATCHDOG_GRACE_MS,
		classifyError: classifyError,
		isRetryable: isRetryable,
		locate: locate,
		labelKey: function(kind) { return "gps_err_" + kind; }
	};

	if (typeof module !== "undefined" && module.exports) {
		module.exports = api;
	} else {
		root.SaudiPunchGeo = api;
	}
})(typeof window !== "undefined" ? window : globalThis);
