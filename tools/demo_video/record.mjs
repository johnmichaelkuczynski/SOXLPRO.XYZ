#!/usr/bin/env node
// SOXL Analysis app demo recorder.
//
// Drives a headed Chromium (via Playwright) through every tab + key
// interaction of the running Streamlit app, records the entire session to
// .webm video, and prints the output path so the caller can ffmpeg-convert
// it to mp4.
//
// Usage:
//   node tools/demo_video/record.mjs                # uses APP_URL or default
//   APP_URL=http://localhost:5000 node tools/demo_video/record.mjs
//
// Output: tools/demo_video/out/<timestamp>/<name>.webm
//
// No narration, no overlay, no captions — just real cursor + real input
// being typed into the real app, with deliberate pauses so the eye can
// follow what is happening.

import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const APP_URL = process.env.APP_URL || 'http://localhost:5000';
const VIEWPORT = { width: 1440, height: 900 };
const OUT_ROOT = path.join(__dirname, 'out');
const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
const OUT_DIR = path.join(OUT_ROOT, ts);
fs.mkdirSync(OUT_DIR, { recursive: true });

const log = (m) => console.log(`[${new Date().toISOString().slice(11, 19)}] ${m}`);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Human-like cursor move: move in N steps so the path is visible on video.
async function moveTo(page, x, y, steps = 25) {
  await page.mouse.move(x, y, { steps });
}

async function moveToElement(page, locator, steps = 30) {
  const box = await locator.boundingBox();
  if (!box) return null;
  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;
  await moveTo(page, x, y, steps);
  return box;
}

async function clickElement(page, locator, { settle = 800 } = {}) {
  await moveToElement(page, locator);
  await sleep(250);
  await locator.click();
  await sleep(settle);
}

async function typeHuman(page, locator, text, { perChar = 55 } = {}) {
  await moveToElement(page, locator);
  await locator.click();
  await sleep(200);
  for (const ch of text) {
    await page.keyboard.type(ch, { delay: perChar });
  }
}

async function smoothScroll(page, totalY, steps = 20, pauseEach = 60) {
  const dy = totalY / steps;
  for (let i = 0; i < steps; i++) {
    await page.mouse.wheel(0, dy);
    await sleep(pauseEach);
  }
}

// Try several locator strategies and return the first one that resolves.
async function firstVisible(page, candidates, timeout = 4000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    for (const make of candidates) {
      const loc = make();
      try {
        if (await loc.first().isVisible({ timeout: 200 }).catch(() => false)) {
          return loc.first();
        }
      } catch (_) { /* keep trying */ }
    }
    await sleep(150);
  }
  return null;
}

async function waitForStreamlitIdle(page, ms = 2500) {
  // Streamlit shows a "Running" status indicator in the top-right while it's
  // executing a script run. Wait for it to disappear, then add a buffer.
  try {
    await page.waitForSelector('[data-testid="stStatusWidget"]', {
      state: 'detached',
      timeout: 1500,
    }).catch(() => {});
  } catch (_) {}
  await sleep(ms);
}

async function clickTab(page, label) {
  log(`switch tab → ${label}`);
  const tab = await firstVisible(page, [
    () => page.getByRole('tab', { name: new RegExp(label, 'i') }),
    () => page.locator('button[role="tab"]', { hasText: new RegExp(label, 'i') }),
    () => page.locator(`button:has-text("${label}")`),
  ], 6000);
  if (!tab) { log(`  ⚠ tab "${label}" not found`); return false; }
  await clickElement(page, tab, { settle: 1500 });
  await waitForStreamlitIdle(page);
  return true;
}

// ── Per-tab demo routines ───────────────────────────────────────────────────
async function demoTopMetrics(page) {
  log('▼ top metrics + price chart');
  // Hover across each of the 7 metric cells so the cursor draws attention.
  for (let i = 0; i < 7; i++) {
    const x = 200 + i * 175;
    await moveTo(page, x, 195, 12);
    await sleep(220);
  }
  await sleep(600);
}

async function demoChartTab(page) {
  log('▼ Chart & Probabilities');
  await demoTopMetrics(page);

  // Click each benchmark overlay button.
  for (const sym of ['QQQ', 'TQQQ', 'TLT', 'XLU', 'VIX', 'Short Int.']) {
    const btn = await firstVisible(page, [
      () => page.locator(`button:has-text("${sym}")`).first(),
    ], 2000);
    if (btn) {
      await clickElement(page, btn, { settle: 900 });
    }
  }
  // Turn a couple back off
  for (const sym of ['Short Int.', 'VIX']) {
    const btn = await firstVisible(page, [
      () => page.locator(`button:has-text("${sym}")`).first(),
    ], 1500);
    if (btn) await clickElement(page, btn, { settle: 600 });
  }

  // Scroll down through probability tables + period analysis
  await smoothScroll(page, 1200, 30, 80);
  await sleep(1500);
  await smoothScroll(page, 1200, 30, 80);
  await sleep(1500);
  // Scroll back to top of tab
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'smooth' }));
  await sleep(1500);
}

async function demoVolSurfaceTab(page) {
  log('▼ Vol Surface');
  await sleep(1200);
  await smoothScroll(page, 800, 20, 80);
  await sleep(1500);
  await smoothScroll(page, 800, 20, 80);
  await sleep(1500);
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'smooth' }));
  await sleep(1200);
}

async function demoDislocationTab(page) {
  log('▼ Dislocation');
  await sleep(1200);
  await smoothScroll(page, 1000, 25, 80);
  await sleep(1500);
  await smoothScroll(page, 800, 20, 80);
  await sleep(1500);
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'smooth' }));
  await sleep(1000);
}

async function demoStrategyBuilderTab(page) {
  log('▼ Strategy Builder');
  await sleep(1200);

  // Type a realistic prompt into the chat input
  const chatInput = await firstVisible(page, [
    () => page.locator('[data-testid="stChatInput"] textarea'),
    () => page.locator('textarea[placeholder*="message" i]'),
    () => page.locator('textarea').last(),
  ], 6000);
  if (!chatInput) { log('  ⚠ chat input not found'); return; }

  const prompt =
    'I have $50k cash and $100k in SPY. Moderate risk tolerance. ' +
    'Build me a tranched SOXL entry strategy.';
  await typeHuman(page, chatInput, prompt, { perChar: 45 });
  await sleep(800);
  // Submit
  await page.keyboard.press('Enter');
  log('  prompt sent, waiting for AI to respond (up to 60s)…');
  // Wait for either an assistant message bubble or the running indicator to clear
  const deadline = Date.now() + 60_000;
  while (Date.now() < deadline) {
    const running = await page.locator('[data-testid="stStatusWidget"]').isVisible().catch(() => false);
    const hasAssistant = await page.locator('[data-testid="stChatMessage"]').count().catch(() => 0);
    if (!running && hasAssistant >= 2) break;
    await sleep(800);
  }
  await sleep(1500);
  await smoothScroll(page, 1500, 30, 80);
  await sleep(1500);
}

async function demoBacktestTab(page) {
  log('▼ Backtest');
  await sleep(1500);
  // Just scroll through the default Allocation Engine view
  await smoothScroll(page, 1200, 30, 80);
  await sleep(1500);
  await smoothScroll(page, 1200, 30, 80);
  await sleep(1500);
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'smooth' }));
  await sleep(1200);
}

async function demoDiagnosticTab(page) {
  log('▼ Diagnostic');
  await sleep(800);

  // ── System Check subtab
  const sysSub = await firstVisible(page, [
    () => page.locator('button[role="tab"]', { hasText: /system check/i }),
  ], 4000);
  if (sysSub) await clickElement(page, sysSub, { settle: 800 });

  const runDiag = await firstVisible(page, [
    () => page.locator('button:has-text("Run diagnostic")'),
  ], 4000);
  if (runDiag) {
    await clickElement(page, runDiag, { settle: 1000 });
    log('  System Check running, waiting up to 40s…');
    const deadline = Date.now() + 40_000;
    while (Date.now() < deadline) {
      const running = await page.locator('[data-testid="stStatusWidget"]').isVisible().catch(() => false);
      const done = await page.locator('text=/checks? passed|check\\(s\\) failed/i').isVisible().catch(() => false);
      if (!running && done) break;
      await sleep(600);
    }
    await sleep(1500);
    await smoothScroll(page, 900, 20, 80);
    await sleep(1500);
    await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'smooth' }));
    await sleep(1000);
  }

  // ── Backtest Sweep subtab
  const sweepSub = await firstVisible(page, [
    () => page.locator('button[role="tab"]', { hasText: /backtest sweep/i }),
  ], 4000);
  if (sweepSub) await clickElement(page, sweepSub, { settle: 800 });

  const runSweep = await firstVisible(page, [
    () => page.locator('button:has-text("Run exhaustive sweep")'),
  ], 4000);
  if (runSweep) {
    await clickElement(page, runSweep, { settle: 1000 });
    log('  Sweep running, waiting up to 120s…');
    const deadline = Date.now() + 120_000;
    while (Date.now() < deadline) {
      const verdict = await page.locator('text=/Verdict:/i').isVisible().catch(() => false);
      if (verdict) break;
      await sleep(800);
    }
    await sleep(2000);
    await smoothScroll(page, 1500, 30, 80);
    await sleep(2000);
    await smoothScroll(page, 1200, 25, 80);
    await sleep(2000);
  }
}

// ── Main ────────────────────────────────────────────────────────────────────
(async () => {
  log(`recording → ${OUT_DIR}`);
  log(`app url   → ${APP_URL}`);

  const browser = await chromium.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
  const context = await browser.newContext({
    viewport: VIEWPORT,
    recordVideo: { dir: OUT_DIR, size: VIEWPORT },
    deviceScaleFactor: 1,
  });
  const page = await context.newPage();

  try {
    log('open app');
    await page.goto(APP_URL, { waitUntil: 'domcontentloaded', timeout: 30_000 });
    // Wait for SOXL Analysis title to render
    await page.waitForSelector('text=/SOXL Analysis/i', { timeout: 30_000 });
    await waitForStreamlitIdle(page, 2500);
    // Initial pause — let the chart finish drawing
    await sleep(2500);

    await demoChartTab(page);
    await clickTab(page, 'Vol Surface');     await demoVolSurfaceTab(page);
    await clickTab(page, 'Dislocation');     await demoDislocationTab(page);
    await clickTab(page, 'Strategy Builder');await demoStrategyBuilderTab(page);
    await clickTab(page, 'Backtest');        await demoBacktestTab(page);
    await clickTab(page, 'Diagnostic');      await demoDiagnosticTab(page);

    log('demo complete, finalizing video…');
    await sleep(1500);
  } catch (err) {
    log(`ERROR: ${err.message}`);
    console.error(err.stack);
  } finally {
    await context.close();      // flushes the .webm
    await browser.close();
  }

  // Locate the produced .webm and rename it to something predictable
  const files = fs.readdirSync(OUT_DIR).filter((f) => f.endsWith('.webm'));
  if (files.length) {
    const src = path.join(OUT_DIR, files[0]);
    const dest = path.join(OUT_DIR, 'soxl-demo.webm');
    if (src !== dest) fs.renameSync(src, dest);
    log(`saved: ${dest}`);
    console.log(dest); // last line = produced path
  } else {
    log('⚠ no .webm produced');
    process.exit(2);
  }
})();
