// Run with: node --test saudi_hr/public/js/tests/
// Also run from Python by saudi_hr/saudi_hr/test_punch_geolocation.py
"use strict";
const test = require("node:test");
const assert = require("node:assert");
const geo = require("../punch_geolocation.js");

// fake timers: the watchdog only fires when a test calls fire()
function fakeTimers() {
	const timers = [];
	return {
		setTimeout(fn, ms) { const h = { fn, ms, cleared: false }; timers.push(h); return h; },
		clearTimeout(h) { if (h) h.cleared = true; },
		fireAll() { timers.filter((h) => !h.cleared).forEach((h) => { h.cleared = true; h.fn(); }); },
		timers,
	};
}

// a geolocation stub that answers each call from a script of outcomes
function scriptedGeo(outcomes) {
	const calls = [];
	return {
		calls,
		getCurrentPosition(ok, fail, opts) {
			calls.push(opts);
			const o = outcomes.shift();
			if (!o || o === "hang") return;
			if (o.coords) ok({ coords: o.coords });
			else fail(o);
		},
	};
}

function run(env) {
	return new Promise((resolve) => {
		geo.locate(Object.assign({ isSecureContext: true, permissions: null }, fakeTimers(), env), (err, res) => resolve({ err, res }));
	});
}

const POS = { coords: { latitude: 24.7, longitude: 46.7, accuracy: 30 } };

test("classifyError tells the codes apart", () => {
	assert.strictEqual(geo.classifyError({ code: 1, message: "User denied Geolocation" }), "denied");
	assert.strictEqual(geo.classifyError({ code: 2 }), "unavailable");
	assert.strictEqual(geo.classifyError({ code: 3 }), "timeout");
	assert.strictEqual(geo.classifyError({ code: 1, message: "Only secure origins are allowed" }), "insecure");
	assert.strictEqual(geo.classifyError(null), "unavailable");
});

test("success on the first try returns the coordinates", async () => {
	const g = scriptedGeo([POS]);
	const { err, res } = await run({ geolocation: g });
	assert.strictEqual(err, null);
	assert.deepStrictEqual(res, { latitude: 24.7, longitude: 46.7, accuracy: 30, attempt: 1 });
	assert.strictEqual(g.calls[0].enableHighAccuracy, true);
	assert.ok(g.calls[0].maximumAge > 0);
});

test("a timeout retries once with low accuracy and succeeds", async () => {
	const g = scriptedGeo([{ code: 3, message: "Timeout expired" }, POS]);
	const retries = [];
	const { err, res } = await run({ geolocation: g, onRetry: (i, kind) => retries.push([i, kind]) });
	assert.strictEqual(err, null);
	assert.strictEqual(res.attempt, 2);
	assert.strictEqual(g.calls.length, 2);
	assert.strictEqual(g.calls[1].enableHighAccuracy, false);
	assert.deepStrictEqual(retries, [[1, "timeout"]]);
});

test("position unavailable is retried, and reported as unavailable (not denied) when it keeps failing", async () => {
	const g = scriptedGeo([{ code: 2 }, { code: 2 }]);
	const { err } = await run({ geolocation: g });
	assert.strictEqual(err.kind, "unavailable");
	assert.strictEqual(err.attempts, 2);
});

test("permission denied is not retried", async () => {
	const g = scriptedGeo([{ code: 1, message: "User denied Geolocation" }, POS]);
	const { err } = await run({ geolocation: g });
	assert.strictEqual(err.kind, "denied");
	assert.strictEqual(g.calls.length, 1);
});

test("plain http is reported as insecure without asking the browser", async () => {
	const g = scriptedGeo([POS]);
	const { err } = await run({ geolocation: g, isSecureContext: false });
	assert.strictEqual(err.kind, "insecure");
	assert.strictEqual(g.calls.length, 0);
});

test("a browser without geolocation is reported as unsupported", async () => {
	const { err } = await run({ geolocation: null });
	assert.strictEqual(err.kind, "unsupported");
});

test("a browser that never answers is timed out by the watchdog and retried", async () => {
	const timers = fakeTimers();
	const g = scriptedGeo(["hang", "hang"]);
	const p = new Promise((resolve) => {
		geo.locate(Object.assign({ isSecureContext: true, permissions: null, geolocation: g }, timers), (err) => resolve(err));
	});
	timers.fireAll(); // first attempt's watchdog -> retry
	timers.fireAll(); // second attempt's watchdog -> give up
	const err = await p;
	assert.strictEqual(err.kind, "timeout");
	assert.strictEqual(g.calls.length, 2);
	assert.strictEqual(timers.timers[0].ms, geo.DEFAULT_ATTEMPTS[0].timeout + geo.WATCHDOG_GRACE_MS);
});

test("a late browser answer after the watchdog does not report twice", async () => {
	const timers = fakeTimers();
	let lateOk;
	const g = { getCurrentPosition(ok) { lateOk = ok; } };
	let calls = 0;
	geo.locate(Object.assign({ isSecureContext: true, permissions: null, geolocation: g }, timers), () => { calls++; }, [{ timeout: 1000 }]);
	timers.fireAll();
	lateOk(POS);
	assert.strictEqual(calls, 1);
});

test("a site already blocked in the browser is reported as denied straight away", async () => {
	const g = scriptedGeo([POS]);
	const permissions = { query: () => Promise.resolve({ state: "denied" }) };
	const { err } = await run({ geolocation: g, permissions });
	assert.strictEqual(err.kind, "denied");
	assert.strictEqual(g.calls.length, 0);
});

test("a permissions API that rejects (older Safari) still asks for the position", async () => {
	const g = scriptedGeo([POS]);
	const permissions = { query: () => Promise.reject(new TypeError("unsupported")) };
	const { err, res } = await run({ geolocation: g, permissions });
	assert.strictEqual(err, null);
	assert.strictEqual(res.latitude, 24.7);
});

test("every error kind has an Arabic and an English label", () => {
	const fs = require("node:fs");
	const path = require("node:path");
	const src = fs.readFileSync(path.join(__dirname, "..", "saudi_portal.js"), "utf8");
	for (const kind of Object.values(geo.KIND)) {
		const key = geo.labelKey(kind);
		const n = src.split(key + ":").length - 1;
		assert.strictEqual(n, 2, `${key} should appear once in each language, found ${n}`);
	}
});
