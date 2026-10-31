// Screenshots for the design evidence record, at the contract's two viewports (390x844 phone, 1440x900 desktop).
//   node scripts/evidence.mjs <out-dir> [state]      state: main (default) | error | empty | permission
// Needs `next start` on :3000 and the API on :8000 (replay). "error": run with the API stopped. "empty": the API is
// the stand-in from scripts/empty_api.py. "permission": the API runs with PHERI_PUBLIC_DEMO=1.
import { chromium } from "@playwright/test";
import { mkdir } from "node:fs/promises";

const BASE = process.env.WEB_URL ?? "http://localhost:3000";
const out = process.argv[2] ?? "evidence";
const state = process.argv[3] ?? "main";
const VIEWPORTS = { "390x844": { width: 390, height: 844 }, "1440x900": { width: 1440, height: 900 } };
const PAGES = state === "main"
  ? { morning: "/birgunj", night: "/birgunj/night", slop: "/birgunj/slop", proof: "/birgunj/proof", rules: "/birgunj/rules",
      customer: "/birgunj/customers/%2B918965164000", brightdesk: "/brightdesk" }
  : { morning: "/birgunj" };

await mkdir(out, { recursive: true });
const browser = await chromium.launch();
const problems = [];
for (const [vp, size] of Object.entries(VIEWPORTS)) {
  const page = await browser.newPage({ viewport: size, deviceScaleFactor: 1 });
  page.on("pageerror", (e) => problems.push(`${vp} page error: ${e.message}`));
  if (state === "loading") {  // the stand-in answers the brief 10 s late: what the owner sees while waiting
    await page.goto(BASE + "/birgunj", { waitUntil: "commit" });
    await page.waitForTimeout(2500);
    await page.screenshot({ path: `${out}/loading-${vp}.png` });
    console.log(`${out}/loading-${vp}.png`);
    await page.close();
    continue;
  }
  for (const [name, path] of Object.entries(PAGES)) {
    await page.goto(BASE + path, { waitUntil: "networkidle", timeout: 120_000 });
    await page.waitForFunction(() => !document.querySelector('[aria-busy="true"]'), null, { timeout: 120_000 });
    const file = `${out}/${state === "main" ? name : state}-${vp}.png`;
    await page.screenshot({ path: file, fullPage: true });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    if (overflow > 1) problems.push(`${vp} ${name}: page is ${overflow}px wider than the viewport`);
    // No internal ids on any page an owner reads (the trace page is the raw record, by design, and isn't scanned).
    const ids = await page.evaluate(() =>
      [...document.body.innerText.matchAll(/\b[a-z]+(?:_[a-z0-9]+)+\b|(['"])(en|ne|hi|bho|ne-Latn)\1/g)].map((m) => m[0]));
    if (ids.length) problems.push(`${vp} ${name}: internal ids on the page: ${[...new Set(ids)].slice(0, 8).join(", ")}`);
    console.log(`${file}`);
  }
  if (state === "main") {
    // keyboard: the first Tab lands on a visible, focusable control
    await page.goto(BASE + "/birgunj", { waitUntil: "networkidle" });
    await page.keyboard.press("Tab");
    const focused = await page.evaluate(() => document.activeElement?.tagName + " " + (document.activeElement?.textContent ?? "").trim().slice(0, 30));
    console.log(`${vp} first Tab: ${focused}`);
    // Night shift playback: opens finished; at 4x the clock ticks through the arrivals, then rows tick through steps.
    await page.goto(BASE + "/birgunj/night", { waitUntil: "networkidle" });
    const rows = page.locator('section[aria-labelledby="tonight"] ol > li');
    const all = await rows.count();
    const href = await rows.first().locator("a").first().getAttribute("href");
    if (!href || !href.endsWith("/trace")) problems.push(`${vp} night: the first row's name does not link to its trace (${href})`);
    await page.getByRole("button", { name: "4×" }).click();
    await page.getByRole("button", { name: /Replay the night/ }).click();
    await page.waitForTimeout(2500);
    const clockMid = (await page.getByLabel("Time on the night clock").textContent())?.trim();
    const arrived = await rows.count();
    await page.screenshot({ path: `${out}/night-arriving-${vp}.png` });
    if (!(arrived > 0 && arrived < all)) problems.push(`${vp} night: ${arrived} of ${all} rows mid-arrivals`);
    if (!clockMid || clockMid === "06:15" || clockMid === "21:00") problems.push(`${vp} night: the clock read ${clockMid}`);
    await page.waitForTimeout(6000);  // arrivals end at 6 s (4x); the night shift is working through the steps
    const working = await page.locator('section[aria-labelledby="tonight"] ol > li ul > li').count();
    await page.screenshot({ path: `${out}/night-working-${vp}.png` });
    if (!(working > 0)) problems.push(`${vp} night: no steps shown while the night shift works`);
    console.log(`${vp} night playback: clock ${clockMid}, ${arrived}/${all} rows arrived, ${working} steps while working`);
  }
  await page.close();
}
if (state === "main") {
  // Reduced motion: the whole night at once, no controls, nothing animates.
  const ctx = await browser.newContext({ viewport: VIEWPORTS["390x844"], reducedMotion: "reduce" });
  const page = await ctx.newPage();
  await page.goto(BASE + "/birgunj/night", { waitUntil: "networkidle" });
  const controls = await page.getByRole("button", { name: /Replay the night|Play/ }).count();
  const steps = await page.locator('section[aria-labelledby="tonight"] ol > li ul > li').count();
  if (controls !== 0 || steps === 0) problems.push(`reduced motion: ${controls} play buttons, ${steps} steps shown`);
  console.log(`reduced motion: ${controls} play buttons, ${steps} steps shown at once`);
  await ctx.close();
}
if (state === "main") {
  // success, last: approving changes the server's state (one shared store outside the public demo), so every other
  // page is taken first. Approve once on the phone, then show where the item went at both viewports.
  for (const [i, [vp, size]] of Object.entries(VIEWPORTS).entries()) {
    const page = await browser.newPage({ viewport: size, deviceScaleFactor: 1 });
    await page.goto(BASE + "/birgunj", { waitUntil: "networkidle" });
    // the first card (Sita Karna's rate question) is approved with one of code's two choices
    const approve = page.getByRole("button", { name: /^(Same rate as their last order|Approve|Send anyway)$/ }).first();
    if (i === 0 && await approve.count()) {
      await approve.click();
      await page.waitForLoadState("networkidle");
      await page.waitForTimeout(500);
    }
    await page.screenshot({ path: `${out}/success-${vp}.png`, fullPage: true });
    console.log(`${out}/success-${vp}.png`);
    await page.close();
  }
}
await browser.close();
if (problems.length) {
  console.log("\nProblems:\n" + problems.join("\n"));
  process.exitCode = 1;
}
