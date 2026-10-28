// Screenshots of every page at 1920x1080 (the screen-recording size), for checking by eye.
//   node scripts/screens.mjs                 # all pages
//   node scripts/screens.mjs home journey    # some
// Needs the API (uvicorn pheri.app:app, mock mode) on :8000 and `npm run dev` on :3000.
import { chromium } from "@playwright/test";
import { mkdir } from "node:fs/promises";

const BASE = process.env.WEB_URL ?? "http://localhost:3000";
const MAYA = encodeURIComponent("maya.okafor@pinecrest.example");
const PAGES = {
  home: "/brightdesk",
  "home-kettle": "/kettle",
  journey: "/brightdesk/journey",
  customer: `/brightdesk/customers/${MAYA}`,
  trace: `/brightdesk/customers/${MAYA}/trace`,
  rules: "/brightdesk/rules",
  safety: "/brightdesk/safety",
  proof: "/brightdesk/proof",
  spend: "/brightdesk/spend",
};

// What a viewer would click on some pages; the result is screenshotted too.
const ACTIONS = {
  customer: async (page) => {
    const button = page.getByRole("button", { name: "Offer a discount" });
    await button.scrollIntoViewIfNeeded();
    await button.click();
    await page.getByRole("status").waitFor({ timeout: 30_000 });
    await page.getByRole("status").scrollIntoViewIfNeeded();
    await page.waitForTimeout(200);
  },
};

const wanted = process.argv.slice(2).length ? process.argv.slice(2) : Object.keys(PAGES);
await mkdir("screenshots", { recursive: true });
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
const problems = [];
page.on("console", (m) => m.type() === "error" && problems.push(`console: ${m.text()}`));
page.on("pageerror", (e) => problems.push(`page error: ${e.message}`));
for (const name of wanted) {
  const res = await page.goto(BASE + PAGES[name], { waitUntil: "networkidle", timeout: 120_000 });
  await page.waitForFunction(() => !document.querySelector('[aria-busy="true"]'), null, { timeout: 120_000 });
  await page.waitForTimeout(300);
  await page.screenshot({ path: `screenshots/${name}.png` });
  await page.screenshot({ path: `screenshots/${name}-full.png`, fullPage: true });
  console.log(`${name}: ${res?.status()} -> screenshots/${name}.png`);
  if (ACTIONS[name]) {
    await ACTIONS[name](page);
    await page.screenshot({ path: `screenshots/${name}-after.png` });
    console.log(`${name}: after the click -> screenshots/${name}-after.png`);
  }
}
await browser.close();
if (problems.length) {
  console.log("\nProblems seen in the browser:\n" + problems.join("\n"));
  process.exitCode = 1;
}
