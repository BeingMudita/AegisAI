import { chromium } from "@playwright/test";
const OUT = "C:/Users/proje/AppData/Local/Temp/claude/d--rag-project/a5730e5c-810d-4846-8b2e-b195c70ae9de/scratchpad/audit";
const browser = await chromium.launch({ channel: "msedge" });
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
await page.goto("http://127.0.0.1:5173/#/database");
await page.getByLabel("Username").fill("admin");
await page.getByLabel("Password").fill("admin123");
await page.getByRole("button", { name: /continue to workspace/i }).click();
await page.getByText(/Showing 1–50 of/).waitFor({ timeout: 30000 });
await page.getByRole("tab", { name: /Map/ }).click();
const canvas = page.getByRole("img", { name: /Map of the archive/ });
await canvas.waitFor();
await canvas.scrollIntoViewIfNeeded();
await page.waitForTimeout(2500);
await canvas.screenshot({ path: `${OUT}/2d-1.png` });
// zoom deep into the red (dataset) cluster on the left
const b = await canvas.boundingBox();
await page.mouse.move(b.x + b.width * 0.27, b.y + b.height * 0.42);
for (let i = 0; i < 12; i++) { await page.mouse.wheel(0, -250); await page.waitForTimeout(50); }
await page.waitForTimeout(1200);
await page.mouse.move(b.x + 3, b.y + b.height - 3);
await page.waitForTimeout(300);
await canvas.screenshot({ path: `${OUT}/2d-2-zoom.png` });
console.log("errors:", errors.length ? errors : "none");
await browser.close();
