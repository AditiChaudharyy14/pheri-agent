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
  ? { morning: "/birgunj", night: "/birgunj/night", slop: "/birgunj/slop", proof: "/birgunj/proof", rules: "/birgunj/rules" }
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
    console.log(`${file}`);
  }
  if (state === "main") {
    // keyboard: the first Tab lands on a visible, focusable control
    await page.goto(BASE + "/birgunj", { waitUntil: "networkidle" });
    await page.keyboard.press("Tab");
    const focused = await page.evaluate(() => document.activeElement?.tagName + " " + (document.activeElement?.textContent ?? "").trim().slice(0, 30));
    console.log(`${vp} first Tab: ${focused}`);
    // success: approve the first item that needs the owner, then show where it went. Birgunj's recorded night left
    // nothing for the owner, so this is Brightdesk's morning, where approvals wait.
    await page.goto(BASE + "/brightdesk", { waitUntil: "networkidle" });
    const approve = page.getByRole("button", { name: /^(Approve|Send anyway)$/ }).first();
    if (await approve.count()) {
      await approve.click();
      await page.waitForLoadState("networkidle");
      await page.waitForTimeout(500);
      await page.screenshot({ path: `${out}/success-${vp}.png`, fullPage: true });
      console.log(`${out}/success-${vp}.png`);
    }
  }
  await page.close();
}
await browser.close();
if (problems.length) {
  console.log("\nProblems:\n" + problems.join("\n"));
  process.exitCode = 1;
}
