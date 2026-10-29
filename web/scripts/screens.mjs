// Screenshots of every page at 1920x1080 (the screen-recording size), for checking by eye.
//   node scripts/screens.mjs                 # all pages
//   node scripts/screens.mjs home journey    # some
// Needs the API (uvicorn pheri.app:app, mock or replay mode) on :8000 and `npm run dev` on :3000.
import { chromium } from "@playwright/test";
import { mkdir } from "node:fs/promises";

const BASE = process.env.WEB_URL ?? "http://localhost:3000";
const MAYA = encodeURIComponent("maya.okafor@pinecrest.example");
const PAGES = {
  home: "/brightdesk",
  "home-birgunj": "/birgunj",
  journey: "/brightdesk/journey",
  customer: `/brightdesk/customers/${MAYA}`,
  trace: `/brightdesk/customers/${MAYA}/trace`,
  "trace-aarav": `/brightdesk/customers/${encodeURIComponent("aarav.silva@granite.example")}/trace`,
  rules: "/brightdesk/rules",
  safety: "/brightdesk/safety",
  proof: "/brightdesk/proof",
  "proof-birgunj": "/birgunj/proof",
  spend: "/brightdesk/spend",
};

// What a viewer would click on some pages; the result is screenshotted too.
const ACTIONS = {
  safety: async (page) => {
    await page.getByRole("button", { name: /Private mode/ }).click();
    await page.getByText("Baseten", { exact: true }).first().waitFor({ timeout: 30_000 });
    await page.waitForTimeout(300);
  },
  rules: async (page) => {
    await page.getByRole("button", { name: "No discounts above 15%" }).click();
    await page.getByRole("button", { name: "Preview" }).click();
    await page.getByRole("status").waitFor({ timeout: 30_000 });
    await page.waitForTimeout(200);
  },
  proof: async (page) => {
    await page.getByText("How we know: the lift for each stage").click();
    await page.waitForTimeout(200);
  },
};

// Put back what a click changed in the running API, so the next run starts from the same state.
const UNDO = {
  safety: async (page) => {
    await page.getByRole("button", { name: /Meta Model API/ }).click();
    await page.waitForTimeout(500);
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
    if (UNDO[name]) await UNDO[name](page);
  }
}
await browser.close();
if (problems.length) {
  console.log("\nProblems seen in the browser:\n" + problems.join("\n"));
  process.exitCode = 1;
}
