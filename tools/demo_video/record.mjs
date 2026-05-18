#!/usr/bin/env node
// SOXL Analysis app demo recorder.
//
// Drives a headless Chromium (via Playwright) through every tab + key
// interaction of the running Streamlit app, records the entire session to
// .webm video, and prints the output path so the caller can ffmpeg-convert
// it to mp4.
//
// Usage:
//   node tools/demo_video/record.mjs                # uses APP_URL or default
//   APP_URL=http://localhost:5000 node tools/demo_video/record.mjs
//
// Output: tools/demo_video/out/<timestamp>/soxl-demo.webm
//
// No narration, no overlay — just real cursor + real input being typed
// into the real app, paced tight so the eye keeps moving.

import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const APP_URL = process.env.APP_URL || 'http://localhost:5000';
// Wider viewport so the price chart + 5y future extension isn't clipped.
// Chart component itself is 900px tall; with the title bar + tabs + price
// metrics above it (~280px), we need ≥1200px of viewport height or the
// chart's x-axis date labels get clipped at the bottom.
const VIEWPORT = { width: 1680, height: 1200 };
const OUT_ROOT = path.join(__dirname, 'out');
const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
const OUT_DIR = path.join(OUT_ROOT, ts);
fs.mkdirSync(OUT_DIR, { recursive: true });

const log = (m) => console.log(`[${new Date().toISOString().slice(11, 19)}] ${m}`);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function moveTo(page, x, y, steps = 18) {
  await page.mouse.move(x, y, { steps });
}

async function moveToElement(page, locator, steps = 20) {
  const box = await locator.boundingBox();
  if (!box) return null;
  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;
  await moveTo(page, x, y, steps);
  return box;
}

async function clickElement(page, locator, { settle = 350 } = {}) {
  await moveToElement(page, locator);
  await sleep(120);
  await locator.click();
  await sleep(settle);
}

async function typeHuman(page, locator, text, { perChar = 32 } = {}) {
  await moveToElement(page, locator);
  await locator.click();
  await sleep(150);
  for (const ch of text) {
    await page.keyboard.type(ch, { delay: perChar });
  }
}

async function smoothScroll(page, totalY, steps = 16, pauseEach = 35) {
  const dy = totalY / steps;
  for (let i = 0; i < steps; i++) {
    await page.mouse.wheel(0, dy);
    await sleep(pauseEach);
  }
}

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
    await sleep(120);
  }
  return null;
}

async function waitForStreamlitIdle(page, ms = 600) {
  try {
    await page.waitForSelector('[data-testid="stStatusWidget"]', {
      state: 'detached',
      timeout: 1200,
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
  await clickElement(page, tab, { settle: 600 });
  await waitForStreamlitIdle(page, 500);
  return true;
}

// ── Per-tab demo routines ───────────────────────────────────────────────────
async function demoTopMetrics(page) {
  // Sweep cursor across the 7 price-metric cells, briskly.
  for (let i = 0; i < 7; i++) {
    const x = 200 + i * 200;
    await moveTo(page, x, 130, 8);
    await sleep(110);
  }
}

async function demoVolSurfaceTab(page) {
  log('▼ Vol Surface');
  await sleep(700);
  await smoothScroll(page, 700, 14, 40);
  await sleep(700);
  await smoothScroll(page, 700, 14, 40);
  await sleep(700);
}

async function demoChartTab(page) {
  log('▼ Chart & Probabilities');
  await sleep(600);
  await demoTopMetrics(page);

  // Toggle 4 benchmark overlays — quick on/off rhythm.
  for (const sym of ['QQQ', 'TQQQ', 'TLT', 'VIX']) {
    const btn = await firstVisible(page, [
      () => page.locator(`button:has-text("${sym}")`).first(),
    ], 1500);
    if (btn) await clickElement(page, btn, { settle: 350 });
  }

  // Scroll down through the probability tables and back, briskly.
  await smoothScroll(page, 1400, 22, 35);
  await sleep(700);
  await smoothScroll(page, 1200, 20, 35);
  await sleep(700);
}

async function demoDislocationTab(page) {
  log('▼ Dislocation');
  await sleep(600);
  await smoothScroll(page, 1000, 18, 40);
  await sleep(700);
  await smoothScroll(page, 700, 14, 40);
  await sleep(600);
}

async function demoStrategyBuilderTab(page) {
  log('▼ Strategy Builder');
  await sleep(700);

  const chatInput = await firstVisible(page, [
    () => page.locator('[data-testid="stChatInput"] textarea'),
    () => page.locator('textarea[placeholder*="message" i]'),
    () => page.locator('textarea').last(),
  ], 6000);
  if (!chatInput) { log('  ⚠ chat input not found'); return; }

  const before = await page.locator('[data-testid="stChatMessage"]').count().catch(() => 0);
  const prompt =
    'I have $50k cash and $100k in SPY. Moderate risk tolerance. ' +
    'Build me a tranched SOXL entry strategy.';
  await typeHuman(page, chatInput, prompt, { perChar: 28 });
  await sleep(300);
  await page.keyboard.press('Enter');
  log(`  prompt sent (msgs before=${before}), waiting for AI…`);
  // Hard floor: give Claude at least 18s to stream its response in
  // (Streamlit adds user-echo + placeholder bubbles instantly, so polling
  // message count alone short-circuits in <1s). After the floor, also
  // wait up to 60s more for the status widget to clear.
  await sleep(18_000);
  const deadline = Date.now() + 60_000;
  while (Date.now() < deadline) {
    const running = await page.locator('[data-testid="stStatusWidget"]').isVisible().catch(() => false);
    if (!running) break;
    await sleep(700);
  }
  log(`  AI responded (msgs after=${await page.locator('[data-testid="stChatMessage"]').count().catch(() => 0)})`);
  await sleep(1200);
  // Scroll through the rendered strategy doc.
  await smoothScroll(page, 1600, 24, 45);
  await sleep(900);
  await smoothScroll(page, 1200, 20, 45);
  await sleep(900);
}

async function demoBacktestTab(page) {
  log('▼ Backtest');
  await sleep(700);
  await smoothScroll(page, 1200, 22, 35);
  await sleep(700);
  await smoothScroll(page, 1200, 22, 35);
  await sleep(700);
}

async function demoDiagnosticTab(page) {
  log('▼ Diagnostic');
  await sleep(500);

  const sysSub = await firstVisible(page, [
    () => page.locator('button[role="tab"]', { hasText: /system check/i }),
  ], 4000);
  if (sysSub) await clickElement(page, sysSub, { settle: 400 });

  const runDiag = await firstVisible(page, [
    () => page.locator('button:has-text("Run diagnostic")'),
  ], 4000);
  if (runDiag) {
    await clickElement(page, runDiag, { settle: 500 });
    log('  System Check running (≤40s)…');
    const deadline = Date.now() + 40_000;
    while (Date.now() < deadline) {
      const running = await page.locator('[data-testid="stStatusWidget"]').isVisible().catch(() => false);
      const done = await page.locator('text=/checks? passed|check\\(s\\) failed/i').isVisible().catch(() => false);
      if (!running && done) break;
      await sleep(500);
    }
    await sleep(700);
    await smoothScroll(page, 800, 16, 40);
    await sleep(700);
  }

  const sweepSub = await firstVisible(page, [
    () => page.locator('button[role="tab"]', { hasText: /backtest sweep/i }),
  ], 4000);
  if (sweepSub) await clickElement(page, sweepSub, { settle: 400 });

  const runSweep = await firstVisible(page, [
    () => page.locator('button:has-text("Run exhaustive sweep")'),
  ], 4000);
  if (runSweep) {
    await clickElement(page, runSweep, { settle: 500 });
    log('  Sweep running (≤120s)…');
    const deadline = Date.now() + 120_000;
    while (Date.now() < deadline) {
      const verdict = await page.locator('text=/Verdict:/i').isVisible().catch(() => false);
      if (verdict) break;
      await sleep(700);
    }
    await sleep(900);
    await smoothScroll(page, 1500, 24, 40);
    await sleep(900);
    await smoothScroll(page, 1200, 20, 40);
    await sleep(900);
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

  // Inject a visible cursor overlay so the viewer can see what's being
  // clicked. Headless Chromium does NOT render the OS cursor into the
  // captured video, so without this every interaction looks like the
  // page is acting on its own.
  await page.addInitScript(() => {
    const install = () => {
      if (document.getElementById('__demo_cursor__')) return;
      const dot = document.createElement('div');
      dot.id = '__demo_cursor__';
      Object.assign(dot.style, {
        position: 'fixed',
        left: '0px', top: '0px',
        width: '22px', height: '22px',
        marginLeft: '-11px', marginTop: '-11px',
        borderRadius: '50%',
        background: 'rgba(255, 64, 64, 0.55)',
        border: '2px solid rgba(255,255,255,0.95)',
        boxShadow: '0 0 12px 4px rgba(255,64,64,0.35)',
        pointerEvents: 'none',
        zIndex: '2147483647',
        transition: 'transform 60ms linear',
      });
      document.documentElement.appendChild(dot);
      const move = (e) => {
        dot.style.left = e.clientX + 'px';
        dot.style.top  = e.clientY + 'px';
      };
      const pulse = () => {
        dot.style.transform = 'scale(0.55)';
        setTimeout(() => { dot.style.transform = 'scale(1)'; }, 180);
      };
      window.addEventListener('mousemove', move, true);
      window.addEventListener('mousedown', pulse, true);
    };
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', install);
    } else {
      install();
    }
    // Streamlit re-renders aggressively; reinstall periodically.
    setInterval(install, 1000);
  });

  try {
    log('open app');
    // `embed=true` hides Streamlit's top toolbar + footer + sidebar chrome
    // so the whole viewport is content. This is what keeps the chart from
    // being clipped on the right.
    const url = APP_URL.includes('?')
      ? `${APP_URL}&embed=true`
      : `${APP_URL}?embed=true`;
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30_000 });
    await page.waitForSelector('text=/SOXL Analysis/i', { timeout: 30_000 });
    await waitForStreamlitIdle(page, 1500);
    await sleep(1500);

    // LEAD with the Vol Surface — most visually striking.
    await clickTab(page, 'Vol Surface');      await demoVolSurfaceTab(page);
    await clickTab(page, 'Chart & Probabilities'); await demoChartTab(page);
    await clickTab(page, 'Dislocation');      await demoDislocationTab(page);
    await clickTab(page, 'Strategy Builder'); await demoStrategyBuilderTab(page);
    await clickTab(page, 'Backtest');         await demoBacktestTab(page);
    await clickTab(page, 'Diagnostic');       await demoDiagnosticTab(page);

    log('demo complete, finalizing video…');
    await sleep(800);
  } catch (err) {
    log(`ERROR: ${err.message}`);
    console.error(err.stack);
  } finally {
    await context.close();
    await browser.close();
  }

  const files = fs.readdirSync(OUT_DIR).filter((f) => f.endsWith('.webm'));
  if (files.length) {
    const src = path.join(OUT_DIR, files[0]);
    const dest = path.join(OUT_DIR, 'soxl-demo.webm');
    if (src !== dest) fs.renameSync(src, dest);
    log(`saved: ${dest}`);
    console.log(dest);
  } else {
    log('⚠ no .webm produced');
    process.exit(2);
  }
})();
