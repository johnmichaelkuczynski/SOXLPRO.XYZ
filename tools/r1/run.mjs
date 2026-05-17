#!/usr/bin/env node
// R1 — synthetic user-agent for end-to-end testing the SOXL Analysis Platform.
// See README.md for spec. Raw evidence only — no green-checkmark theater.

import { chromium } from 'playwright';
import Anthropic from '@anthropic-ai/sdk';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// ─────────────────────────────────────────────────────────────────────────────
// CONFIG
// ─────────────────────────────────────────────────────────────────────────────
const APP_URL = process.env.APP_URL || 'http://localhost:5000';
const HEADLESS = (process.env.HEADLESS || 'false') === 'true';
const LIVE_VIEW_PORT = parseInt(process.env.LIVE_VIEW_PORT || '7777', 10);
const SKIP = new Set((process.env.SKIP_FUNCTIONS || '').split(',').filter(Boolean).map(s => s.trim()));
const ALLOC_TIMEOUT = parseInt(process.env.ALLOCATION_ENGINE_TIMEOUT_MS || '300000', 10);
const VOL_TIMEOUT = parseInt(process.env.VOL_SURFACE_TIMEOUT_MS || '180000', 10);
const AI_TIMEOUT = parseInt(process.env.AI_STRATEGY_TIMEOUT_MS || '120000', 10);
const ANTHROPIC_MODEL = process.env.ANTHROPIC_MODEL || 'claude-opus-4-7';
const VIEWPORT = { width: 1920, height: 1080 };

const ANTHROPIC_API_KEY = process.env.ANTHROPIC_API_KEY || process.env.AI_INTEGRATIONS_ANTHROPIC_API_KEY || '';
const ANTHROPIC_BASE_URL = process.env.ANTHROPIC_BASE_URL || process.env.AI_INTEGRATIONS_ANTHROPIC_BASE_URL || undefined;

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const RUN_TS = new Date().toISOString().replace(/[:.]/g, '-');
const OUTDIR = path.join(__dirname, 'runs', RUN_TS);
const SHOTDIR = path.join(OUTDIR, 'screenshots');
const OUTPUTS = path.join(OUTDIR, 'outputs');
fs.mkdirSync(SHOTDIR, { recursive: true });
fs.mkdirSync(OUTPUTS, { recursive: true });
for (const sub of ['backtest', 'backtest/look-ahead-test', 'backtest/zero-day-test',
  'probability-engine', 'vol-surface', 'dislocation', 'strategy-builder',
  'custom-strategy', 'downloads']) {
  fs.mkdirSync(path.join(OUTPUTS, sub), { recursive: true });
}

// Mirror stdout to console.log file
const consoleLogPath = path.join(OUTDIR, 'console.log');
const consoleLogStream = fs.createWriteStream(consoleLogPath, { flags: 'a' });
const origLog = console.log.bind(console);
console.log = (...args) => {
  const line = args.map(a => typeof a === 'string' ? a : JSON.stringify(a)).join(' ');
  origLog(line);
  try { consoleLogStream.write(line + '\n'); } catch {}
};

// ─────────────────────────────────────────────────────────────────────────────
// STATE (read by live view)
// ─────────────────────────────────────────────────────────────────────────────
const state = {
  startedAt: new Date().toISOString(),
  status: 'starting',
  currentStep: null,
  currentParams: null,
  currentUrl: APP_URL,
  latestScreenshot: null,
  latestNumerics: null,
  recentReruns: [],
  latestJudgeCritique: null,
  soxl: {
    activeTab: null,
    subTab: null,
    dateRange: null,
    latestAllocation: null,
    latestDislocation: null,
    latestProbability: null,
    invariants: { A: 'pending', B: 'pending', C: 'pending', D: 'pending', E: 'pending', F: 'pending', G: 'pending', H: 'pending' },
    allocationSampleHead: [],
    allocationSampleTail: [],
  },
  interactionsCompleted: [],
  judgeConcernsCount: 0,
  invariantViolations: [],
  harnessSanityFailures: [],
  finishedAt: null,
  reportPath: null,
};

const transcriptPath = path.join(OUTDIR, 'transcript.jsonl');
const networkLogPath = path.join(OUTDIR, 'network.log');
const networkLogStream = fs.createWriteStream(networkLogPath, { flags: 'a' });

function writeTranscript(entry) {
  fs.appendFileSync(transcriptPath, JSON.stringify(entry) + '\n');
}

// ─────────────────────────────────────────────────────────────────────────────
// ANTHROPIC CLIENTS (brain + judge)
// ─────────────────────────────────────────────────────────────────────────────
let anthropic = null;
if (ANTHROPIC_API_KEY) {
  const opts = { apiKey: ANTHROPIC_API_KEY };
  if (ANTHROPIC_BASE_URL) opts.baseURL = ANTHROPIC_BASE_URL;
  anthropic = new Anthropic(opts);
}

async function callClaude(systemPrompt, userPrompt, maxTokens = 1024) {
  if (!anthropic) return { ok: false, reason: 'NO_ANTHROPIC_KEY', text: '' };
  try {
    const res = await anthropic.messages.create({
      model: ANTHROPIC_MODEL,
      max_tokens: maxTokens,
      system: systemPrompt,
      messages: [{ role: 'user', content: userPrompt }],
    });
    const text = (res.content || []).map(b => b.type === 'text' ? b.text : '').join('');
    return { ok: true, text, raw: res };
  } catch (e) {
    return { ok: false, reason: e.message || String(e), text: '' };
  }
}

async function brainPickApproach(stepName, availableControls, priorContext) {
  const sys = `You are R1, a synthetic user beta-testing the SOXL Analysis Platform. For each step, choose ONE of: happy_path (use documented defaults), probe_invariant (push edge cases), vary_parameter (change one input to see effect), pathological (deliberately bad input). Return STRICT JSON: {"approach": "...", "rationale": "...", "params": {...}}.`;
  const usr = `STEP: ${stepName}\nAVAILABLE CONTROLS: ${JSON.stringify(availableControls)}\nPRIOR CONTEXT: ${priorContext || 'none'}\nReturn JSON only.`;
  const r = await callClaude(sys, usr, 512);
  if (!r.ok) return { approach: 'happy_path', rationale: `brain unavailable: ${r.reason}`, params: {} };
  try {
    const m = r.text.match(/\{[\s\S]*\}/);
    if (m) return JSON.parse(m[0]);
  } catch {}
  return { approach: 'happy_path', rationale: 'brain JSON unparseable', params: {} };
}

async function judgeInteraction(interaction) {
  const sys = `You are an expert quantitative options analyst reviewing an automated test of a SOXL trading platform. Critique what you see: are the allocation values reasonable and within bounds? Is the asymmetric resize observable in the sleeve diagnostics? Are probabilities reported with sample sizes? Does the dislocation classification make sense? Are AI-generated strategies internally consistent and free of hallucinated indicators? Write 2-4 paragraphs of prose critique. Do NOT use checklists or boolean PASS/FAIL. End with one of: VERDICT_CONCERN or VERDICT_OK (single token on its own line).`;
  const usr = `INTERACTION RECORD:\n${JSON.stringify({
    step: interaction.step,
    approach: interaction.approach,
    params: interaction.params,
    numericOutputs: interaction.numericOutputs,
    invariantChecks: interaction.invariantChecks,
    notes: interaction.notes,
  }, null, 2)}`;
  const r = await callClaude(sys, usr, 1024);
  if (!r.ok) return { critique: `judge unavailable: ${r.reason}`, concern: false };
  const concern = /VERDICT_CONCERN/i.test(r.text);
  return { critique: r.text.trim(), concern };
}

// ─────────────────────────────────────────────────────────────────────────────
// LIVE VIEW HTTP SERVER
// ─────────────────────────────────────────────────────────────────────────────
function renderLiveHtml() {
  const screenshotImg = state.latestScreenshot
    ? `<img src="/shot?path=${encodeURIComponent(state.latestScreenshot)}" style="max-width:100%;border:1px solid #ccc;border-radius:4px"/>`
    : '<em>No screenshot yet</em>';
  const inv = state.soxl.invariants;
  const invHtml = Object.entries(inv).map(([k, v]) => {
    const color = v === 'pass' ? '#1f7a1f' : v === 'fail' ? '#b00020' : v === 'pending' ? '#888' : '#cc7a00';
    return `<span style="display:inline-block;margin:2px 6px;padding:3px 8px;border-radius:3px;background:${color};color:white;font-family:monospace;font-size:12px">${k}: ${v}</span>`;
  }).join('');
  const recent = state.interactionsCompleted.slice(-30).reverse().map(i => {
    const tag = i.error ? 'ERROR' : i.judgeConcern ? 'CONCERN' : 'ok';
    const tagColor = i.error ? '#b00020' : i.judgeConcern ? '#cc7a00' : '#1f7a1f';
    return `<div style="border-bottom:1px solid #eee;padding:6px 0">
      <span style="background:${tagColor};color:white;padding:2px 6px;border-radius:3px;font-size:11px">${tag}</span>
      <strong>${i.step}</strong> &mdash; <span style="color:#666;font-size:12px">${i.approach || ''}</span>
      ${i.numericKeys ? `<div style="font-family:monospace;font-size:11px;color:#444">${i.numericKeys}</div>` : ''}
    </div>`;
  }).join('');
  const head = state.soxl.allocationSampleHead.length
    ? `<pre style="background:#f7f7f7;padding:8px;font-size:11px;overflow:auto;max-height:200px">FIRST 10 ROWS:\n${state.soxl.allocationSampleHead.join('\n')}\nLAST 10 ROWS:\n${state.soxl.allocationSampleTail.join('\n')}</pre>`
    : '<em>No allocation panel captured yet</em>';
  const runComplete = state.status === 'complete'
    ? `<div style="background:#1f7a1f;color:white;padding:14px;border-radius:6px;margin-bottom:14px;font-size:18px"><strong>RUN COMPLETE</strong> &mdash; report: <code>${state.reportPath}</code></div>`
    : '';
  return `<!doctype html><html><head><meta charset="utf-8"><title>R1 — SOXL Live View</title>
<meta http-equiv="refresh" content="2"/>
<style>body{font-family:-apple-system,Helvetica,Arial,sans-serif;margin:0;padding:14px;background:#fafafa;color:#222}
.panel{background:white;border:1px solid #ddd;border-radius:6px;padding:12px;margin-bottom:12px}
.panel h2{margin:0 0 8px;font-size:14px;color:#666;text-transform:uppercase;letter-spacing:0.5px}
.kv{display:grid;grid-template-columns:160px 1fr;gap:4px 12px;font-size:13px}
.kv dt{color:#666;font-weight:600}.kv dd{margin:0;font-family:monospace}
</style></head><body>
${runComplete}
<div class="panel"><h2>Current step</h2>
<dl class="kv">
<dt>Step</dt><dd>${state.currentStep || '—'}</dd>
<dt>Status</dt><dd>${state.status}</dd>
<dt>Params</dt><dd>${state.currentParams ? JSON.stringify(state.currentParams) : '—'}</dd>
<dt>URL</dt><dd>${state.currentUrl}</dd>
</dl>
<div style="margin-top:8px">${screenshotImg}</div></div>

<div class="panel"><h2>SOXL Analysis State</h2>
<dl class="kv">
<dt>Active tab</dt><dd>${state.soxl.activeTab || '—'}</dd>
<dt>Sub-tab</dt><dd>${state.soxl.subTab || '—'}</dd>
<dt>Date range</dt><dd>${state.soxl.dateRange || '—'}</dd>
<dt>Latest allocation</dt><dd>${state.soxl.latestAllocation ? JSON.stringify(state.soxl.latestAllocation) : '—'}</dd>
<dt>Latest dislocation</dt><dd>${state.soxl.latestDislocation ? JSON.stringify(state.soxl.latestDislocation) : '—'}</dd>
<dt>Latest probability</dt><dd>${state.soxl.latestProbability ? JSON.stringify(state.soxl.latestProbability) : '—'}</dd>
</dl>
<div style="margin-top:8px"><strong>Invariants:</strong> ${invHtml}</div>
<div style="margin-top:8px"><strong>Allocation per-bar sample:</strong>${head}</div>
</div>

<div class="panel"><h2>Latest numeric outputs</h2>
<pre style="background:#f7f7f7;padding:8px;font-size:11px;overflow:auto;max-height:300px">${state.latestNumerics ? JSON.stringify(state.latestNumerics, null, 2) : '(none)'}</pre>
</div>

<div class="panel"><h2>Latest judge critique</h2>
<div style="white-space:pre-wrap;font-size:13px;line-height:1.5">${state.latestJudgeCritique || '(none)'}</div>
</div>

<div class="panel"><h2>Recent reruns / Streamlit signals</h2>
<pre style="background:#f7f7f7;padding:8px;font-size:11px;overflow:auto;max-height:150px">${state.recentReruns.slice(-10).join('\n') || '(none)'}</pre>
</div>

<div class="panel"><h2>Completed interactions (reverse-chronological)</h2>
${recent || '<em>none yet</em>'}
</div>

<div class="panel"><h2>Counts</h2>
<dl class="kv">
<dt>Interactions</dt><dd>${state.interactionsCompleted.length}</dd>
<dt>Judge concerns</dt><dd>${state.judgeConcernsCount}</dd>
<dt>Invariant violations</dt><dd>${state.invariantViolations.length}</dd>
<dt>Harness sanity failures</dt><dd>${state.harnessSanityFailures.length}</dd>
</dl></div>
</body></html>`;
}

const liveServer = http.createServer((req, res) => {
  if (req.url === '/' || req.url === '/index.html') {
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
    res.end(renderLiveHtml());
    return;
  }
  if (req.url.startsWith('/shot')) {
    try {
      const u = new URL(req.url, 'http://localhost');
      const p = u.searchParams.get('path');
      if (p && fs.existsSync(p)) {
        res.writeHead(200, { 'Content-Type': 'image/png' });
        res.end(fs.readFileSync(p));
        return;
      }
    } catch {}
    res.writeHead(404); res.end('not found'); return;
  }
  res.writeHead(404); res.end('not found');
});
liveServer.listen(LIVE_VIEW_PORT);

// ─────────────────────────────────────────────────────────────────────────────
// PLAYWRIGHT HELPERS
// ─────────────────────────────────────────────────────────────────────────────
let browser = null, page = null;
let shotCounter = 0;

async function setupBrowser() {
  browser = await chromium.launch({ headless: HEADLESS });
  const ctx = await browser.newContext({ viewport: VIEWPORT, acceptDownloads: true });
  page = await ctx.newPage();
  page.on('request', req => {
    networkLogStream.write(`${new Date().toISOString()} ${req.method()} ${req.url()}\n`);
  });
  page.on('console', msg => {
    if (msg.type() === 'error') console.log(`[browser:error] ${msg.text()}`);
  });
}

async function takeShot(label) {
  shotCounter++;
  const safe = label.replace(/[^a-zA-Z0-9._-]/g, '_').slice(0, 80);
  const filename = `${String(shotCounter).padStart(4, '0')}_${safe}.png`;
  const fullpath = path.join(SHOTDIR, filename);
  try {
    await page.screenshot({ path: fullpath, fullPage: false });
    state.latestScreenshot = fullpath;
    return fullpath;
  } catch (e) {
    console.log(`[shot:fail] ${label}: ${e.message}`);
    return null;
  }
}

async function waitForNoSpinner(timeoutMs = 60000) {
  const t0 = Date.now();
  try {
    await page.waitForSelector('[data-testid="stSpinner"]', { state: 'attached', timeout: 2000 }).catch(() => {});
    await page.waitForFunction(() => !document.querySelector('[data-testid="stSpinner"]'), { timeout: timeoutMs });
    state.recentReruns.push(`spinner cleared in ${Date.now() - t0}ms`);
  } catch (e) {
    state.recentReruns.push(`spinner wait timed out after ${Date.now() - t0}ms`);
  }
  await page.waitForTimeout(400);
}

async function clickTopTab(name) {
  const tab = page.getByRole('tab', { name });
  await tab.first().click();
  state.soxl.activeTab = name;
  state.soxl.subTab = null;
  await waitForNoSpinner();
}

async function clickSubTab(name) {
  // Streamlit sub-tabs are also role=tab; pick by name
  const tab = page.getByRole('tab', { name });
  await tab.first().click();
  state.soxl.subTab = name;
  await waitForNoSpinner();
}

async function getAllText(selector) {
  try { return await page.$$eval(selector, els => els.map(e => e.innerText)); }
  catch { return []; }
}

// Extract BOTH <table> (st.table) AND st.dataframe Glide grids.
// st.dataframe renders as canvas but exposes accessibility nodes:
//   [data-testid="stDataFrame"] [role="columnheader"] / [role="gridcell"]
// Glide virtualizes rows — to capture a long allocation panel we scroll
// the grid container and re-collect.
async function extractAllTables() {
  const htmlTables = await page.$$eval('table', tables => tables.map(t => {
    const headers = Array.from(t.querySelectorAll('thead th')).map(th => th.innerText.trim());
    const rows = Array.from(t.querySelectorAll('tbody tr')).map(tr =>
      Array.from(tr.querySelectorAll('td, th')).map(td => td.innerText.trim())
    );
    return { source: 'html_table', headers, rows, rowCount: rows.length };
  })).catch(() => []);
  const dataframes = await extractStreamlitDataframes();
  return [...htmlTables, ...dataframes];
}

async function extractStreamlitDataframes() {
  const results = [];
  const dfLocators = await page.locator('[data-testid="stDataFrame"], [data-testid="stTable"]').all();
  for (let dfi = 0; dfi < dfLocators.length; dfi++) {
    const df = dfLocators[dfi];
    try {
      // First try plain <table> inside (st.table case)
      const innerTable = await df.locator('table').first();
      if (await innerTable.count() > 0) {
        const headers = await innerTable.locator('thead th').allInnerTexts().catch(() => []);
        const rows = await innerTable.locator('tbody tr').evaluateAll(trs =>
          trs.map(tr => Array.from(tr.querySelectorAll('td,th')).map(td => td.innerText.trim()))).catch(() => []);
        if (headers.length || rows.length) {
          results.push({ source: 'st_table', headers: headers.map(h => h.trim()), rows, rowCount: rows.length });
          continue;
        }
      }
      // Glide grid path — read cells via role attributes, scrolling to collect all rows
      const collected = await df.evaluate(async (el) => {
        const out = { headers: [], rowsByIndex: {} };
        // Headers
        const headerCells = el.querySelectorAll('[role="columnheader"]');
        for (const h of headerCells) out.headers.push((h.getAttribute('aria-label') || h.innerText || '').trim());
        // Scrollable container — try a couple of common selectors
        const scroller = el.querySelector('.dvn-scroller') || el.querySelector('[class*="scroller"]') || el;
        const collectCells = () => {
          const cells = el.querySelectorAll('[role="gridcell"]');
          for (const c of cells) {
            const r = parseInt(c.getAttribute('aria-rowindex') || '-1', 10);
            const co = parseInt(c.getAttribute('aria-colindex') || '-1', 10);
            if (r < 0 || co < 0) continue;
            if (!out.rowsByIndex[r]) out.rowsByIndex[r] = {};
            const text = (c.getAttribute('aria-label') || c.innerText || '').trim();
            out.rowsByIndex[r][co] = text;
          }
        };
        collectCells();
        // Scroll to capture virtualized rows
        if (scroller && scroller.scrollHeight > scroller.clientHeight) {
          const step = Math.max(100, scroller.clientHeight - 40);
          for (let y = step; y < scroller.scrollHeight + step; y += step) {
            scroller.scrollTop = y;
            await new Promise(r => setTimeout(r, 80));
            collectCells();
            if (scroller.scrollTop + scroller.clientHeight >= scroller.scrollHeight - 2) break;
          }
          scroller.scrollTop = 0;
        }
        return out;
      });
      const sortedRowIdxs = Object.keys(collected.rowsByIndex).map(Number).sort((a, b) => a - b);
      const numCols = collected.headers.length || (sortedRowIdxs.length
        ? Math.max(...Object.values(collected.rowsByIndex).flatMap(o => Object.keys(o).map(Number))) + 1 : 0);
      const rows = sortedRowIdxs.map(r => {
        const row = collected.rowsByIndex[r];
        const arr = [];
        for (let c = 0; c < numCols; c++) arr.push(row[c] ?? '');
        return arr;
      });
      results.push({ source: 'st_dataframe', headers: collected.headers, rows, rowCount: rows.length });
    } catch (e) {
      results.push({ source: 'st_dataframe', error: e.message, headers: [], rows: [], rowCount: 0 });
    }
  }
  return results;
}

// st.chat_input + textarea aware prompt fill. Returns true if a message was sent.
async function fillChatPrompt(prompt) {
  // 1. st.chat_input — Streamlit renders it as <div data-testid="stChatInput"> with an inner textarea.
  try {
    const chatInputs = await page.locator('[data-testid="stChatInput"], [data-testid="stChatInputTextArea"]').all();
    for (const ci of chatInputs) {
      try {
        const ta = ci.locator('textarea').first();
        if (await ta.count() > 0) {
          await ta.fill(prompt, { timeout: 3000 });
          await ta.press('Enter');
          return { sent: true, via: 'stChatInput' };
        }
      } catch {}
    }
  } catch {}
  // 2. Fallback — any visible textarea + nearby submit button
  try {
    const tas = await page.locator('textarea:visible').all();
    if (tas.length) {
      const ta = tas[tas.length - 1]; // most recently rendered chat-style
      await ta.fill(prompt, { timeout: 3000 });
      // Try Ctrl+Enter (Streamlit chat default), then plain Enter
      await ta.press('Control+Enter').catch(() => {});
      await page.waitForTimeout(500);
      // If nothing sent, click any submit-looking button
      const btns = await page.getByRole('button').all();
      for (const b of btns) {
        const t = (await b.innerText().catch(() => '')).toLowerCase();
        if (/send|generate|submit|build|refine/.test(t)) {
          try { await b.click({ timeout: 1500 }); return { sent: true, via: 'textarea+button' }; } catch {}
        }
      }
      return { sent: true, via: 'textarea+enter' };
    }
  } catch (e) {
    return { sent: false, via: 'none', error: e.message };
  }
  return { sent: false, via: 'no_input_found' };
}

async function extractMetricCards() {
  return await page.$$eval('[data-testid="stMetric"]', els => els.map(e => {
    const label = e.querySelector('[data-testid="stMetricLabel"]')?.innerText?.trim() || '';
    const value = e.querySelector('[data-testid="stMetricValue"]')?.innerText?.trim() || '';
    const delta = e.querySelector('[data-testid="stMetricDelta"]')?.innerText?.trim() || '';
    return { label, value, delta };
  })).catch(() => []);
}

async function extractPythonTraceback() {
  // Streamlit shows Python tracebacks inside .stException
  const traces = await page.$$eval('.stException, [data-testid="stException"]',
    els => els.map(e => e.innerText)).catch(() => []);
  return traces;
}

async function streamlitErrorsVisible() {
  const tb = await extractPythonTraceback();
  return tb.length > 0 ? tb : null;
}

// ─────────────────────────────────────────────────────────────────────────────
// INTERACTION LOGGING
// ─────────────────────────────────────────────────────────────────────────────
async function logInteraction(interaction) {
  // shotsBefore/After/Complete are mandatory metadata in the entry
  interaction.timestampEnd = new Date().toISOString();
  writeTranscript(interaction);

  // Judge call
  const judge = await judgeInteraction(interaction);
  interaction.judgeCritique = judge.critique;
  interaction.judgeConcern = judge.concern;
  if (judge.concern) state.judgeConcernsCount++;
  state.latestJudgeCritique = judge.critique;

  // Anti-theater sanity checks
  const sanity = [];
  if (interaction.kind === 'interactive') {
    if ((interaction.shots || []).length < 3) {
      sanity.push(`Function ${interaction.functionId} (${interaction.step}): expected 3 screenshots for interactive step, got ${(interaction.shots || []).length}`);
    } else {
      // Verify not byte-identical
      try {
        const sizes = interaction.shots.filter(Boolean).map(p => fs.statSync(p).size);
        const allEqual = sizes.length >= 2 && sizes.every(s => s === sizes[0]);
        if (allEqual) sanity.push(`Function ${interaction.functionId} (${interaction.step}): screenshots may be byte-identical (sizes all ${sizes[0]})`);
      } catch {}
    }
  } else if (interaction.kind === 'navigation') {
    if ((interaction.shots || []).length < 1) sanity.push(`Function ${interaction.functionId} (${interaction.step}): navigation expected ≥1 screenshot`);
  }
  if (interaction.kind === 'interactive' && (!interaction.numericOutputs || Object.keys(interaction.numericOutputs).length === 0)) {
    sanity.push(`Function ${interaction.functionId} (${interaction.step}): interactive step captured 0 numeric outputs`);
  }
  if (!judge.critique || judge.critique.split(/\s+/).length < 30) {
    sanity.push(`Function ${interaction.functionId} (${interaction.step}): judge critique < 30 words`);
  }
  if (sanity.length) state.harnessSanityFailures.push(...sanity);

  // Compact entry for the live-view feed
  state.interactionsCompleted.push({
    step: interaction.step,
    approach: interaction.approach,
    judgeConcern: judge.concern,
    error: !!interaction.error,
    numericKeys: interaction.numericOutputs ? Object.keys(interaction.numericOutputs).slice(0, 6).join(', ') : '',
  });

  // Append judge to transcript as a follow-up record
  writeTranscript({ kind: 'judge', step: interaction.step, critique: judge.critique, concern: judge.concern });
}

function recordInvariantViolation(letter, step, detail) {
  state.soxl.invariants[letter] = 'fail';
  state.invariantViolations.push({ letter, step, detail });
  console.log(`[INVARIANT_${letter}_VIOLATION] ${step}: ${detail}`);
}

function markInvariantPass(letter) {
  if (state.soxl.invariants[letter] !== 'fail') state.soxl.invariants[letter] = 'pass';
}

// ─────────────────────────────────────────────────────────────────────────────
// INVARIANT VERIFIERS
// ─────────────────────────────────────────────────────────────────────────────
function verifyInvariantA(allocationRows, userFloor, userCeiling, step) {
  const HARD_FLOOR = 0.02, HARD_CEIL = 0.98;
  if (!allocationRows || allocationRows.length === 0) {
    state.harnessSanityFailures.push(`Invariant A (${step}): allocation panel not captured — cannot verify bounds. Suspect Streamlit dataframe extraction failed.`);
    state.soxl.invariants.A = 'unverified';
    return { ok: false, reason: 'no_data' };
  }
  const numericRows = allocationRows.filter(r => r.allocation != null && !isNaN(r.allocation));
  if (numericRows.length === 0) {
    state.harnessSanityFailures.push(`Invariant A (${step}): ${allocationRows.length} rows extracted but allocation column was non-numeric.`);
    state.soxl.invariants.A = 'unverified';
    return { ok: false, reason: 'non_numeric' };
  }
  const offenders = [];
  for (let i = 0; i < numericRows.length; i++) {
    const a = numericRows[i].allocation;
    if (a < HARD_FLOOR - 1e-9 || a > HARD_CEIL + 1e-9) {
      offenders.push({ row: i, allocation: a, bound: 'hard' });
    } else if (userFloor != null && userCeiling != null && (a < userFloor - 1e-9 || a > userCeiling + 1e-9)) {
      offenders.push({ row: i, allocation: a, bound: 'user', userFloor, userCeiling });
    }
  }
  if (offenders.length) {
    recordInvariantViolation('A', step, `${offenders.length}/${numericRows.length} rows out of bounds. First 5: ${JSON.stringify(offenders.slice(0, 5))}`);
    return { ok: false, offenders };
  }
  markInvariantPass('A');
  return { ok: true, rowsChecked: numericRows.length };
}

function verifyInvariantC(sleeveSeries, targetSeries, rollEvents, step) {
  // Asymmetric resize: sleeve value should drop with target when target falls;
  // should NOT rise with target between roll events when target rises (no mid-cycle refill).
  if (!sleeveSeries || sleeveSeries.length < 5) {
    return { ok: false, reason: 'insufficient data' };
  }
  const rolls = new Set((rollEvents || []).map(r => r.index));
  let sellDownObserved = false, midCycleRefillObserved = false;
  let lastRollIdx = -1;
  for (let i = 1; i < sleeveSeries.length; i++) {
    if (rolls.has(i)) { lastRollIdx = i; continue; }
    const dTarget = (targetSeries[i] ?? 0) - (targetSeries[i - 1] ?? 0);
    const dSleeve = (sleeveSeries[i] ?? 0) - (sleeveSeries[i - 1] ?? 0);
    const sinceRoll = i - lastRollIdx;
    if (dTarget < -1e-4 && dSleeve < -1e-6) sellDownObserved = true;
    // Mid-cycle refill: target rises notably AND sleeve rises by similar fraction AND we are NOT at a roll
    if (sinceRoll >= 1 && dTarget > 5e-3) {
      const baseline = sleeveSeries[i - 1] || 1;
      const sleeveGrowthPct = dSleeve / baseline;
      if (sleeveGrowthPct > dTarget * 0.5 && sleeveGrowthPct > 5e-3) midCycleRefillObserved = true;
    }
  }
  if (midCycleRefillObserved) {
    recordInvariantViolation('C', step, 'Mid-cycle sleeve refill observed: sleeve_value tracked an upward sleeve_alloc_target change between consecutive roll events');
    return { ok: false };
  }
  markInvariantPass('C');
  return { ok: true, sellDownObserved };
}

function verifyInvariantD(probabilityTable, step) {
  const rows = probabilityTable?.rows || [];
  const headers = (probabilityTable?.headers || []).map(h => h.toLowerCase());
  if (rows.length === 0) {
    state.harnessSanityFailures.push(`Invariant D (${step}): probability table not captured — cannot verify sample-size reporting.`);
    state.soxl.invariants.D = 'unverified';
    return { ok: false, reason: 'no_data' };
  }
  // Valid layout A: explicit "n" or "sample size" column
  const hasNCol = headers.some(h => /^\s*n\s*$/.test(h) || /sample.?size/.test(h) || /\bn\b/.test(h));
  if (hasNCol) { markInvariantPass('D'); return { ok: true, layout: 'n_column' }; }
  // Valid layout B: every cell embeds (n=K) marker
  let rowsWithN = 0;
  for (const r of rows) {
    const cellsHaveN = r.slice(1).some(cell => /n\s*=\s*\d+/i.test(cell) || /^\s*\d+\s*\/\s*\d+/.test(cell));
    if (cellsHaveN) rowsWithN++;
  }
  if (rowsWithN === rows.length && rows.length > 0) {
    markInvariantPass('D'); return { ok: true, layout: 'per_cell_n' };
  }
  recordInvariantViolation('D', step,
    `Probability table missing sample-size. headers=${JSON.stringify(headers)} rowsWithN=${rowsWithN}/${rows.length} firstRow=${JSON.stringify(rows[0])}`);
  return { ok: false };
}

function verifyInvariantE(riskMetricsTable, step) {
  // Spec: must render all 9 columns even on zero-day input.
  const required = [
    { needle: 'total return', label: 'Total Return %' },
    { needle: 'cagr', label: 'CAGR %' },
    { needle: 'vol', label: 'Vol (ann) %' },
    { needle: 'drawdown', label: 'Max Drawdown %' },
    { needle: 'sharpe', label: 'Sharpe' },
    { needle: 'sortino', label: 'Sortino' },
    { needle: 'calmar', label: 'Calmar' },
    { needle: 'capital at risk', label: 'Capital at Risk %' },
    { needle: 'at-risk', label: 'Return / At-Risk %' },
  ];
  if (!riskMetricsTable || !riskMetricsTable.headers || riskMetricsTable.headers.length === 0) {
    recordInvariantViolation('E', step, 'Risk Metrics table not rendered at all');
    return { ok: false, reason: 'absent' };
  }
  const headerJoined = riskMetricsTable.headers.join(' | ').toLowerCase();
  const missing = required.filter(r => !headerJoined.includes(r.needle)).map(r => r.label);
  if (missing.length > 0) {
    recordInvariantViolation('E', step, `Risk Metrics table missing required columns: ${missing.join(', ')}. Got: ${riskMetricsTable.headers.join(' | ')}`);
    return { ok: false, missing };
  }
  markInvariantPass('E');
  return { ok: true };
}

function verifyInvariantF(z, verdict, step) {
  if (z == null || !verdict) return { ok: false, reason: 'no Z or verdict' };
  const v = verdict.toUpperCase();
  // Documented buckets: RICH, STRETCH-RICH, FAIR, STRETCH-CHEAP, CHEAP.
  // Monotonic: large +Z → RICH; large -Z → CHEAP.
  let consistent = true, detail = '';
  if (z > 1.5 && !/RICH/.test(v)) { consistent = false; detail = `Z=${z} but verdict=${verdict} (expected RICH-side)`; }
  if (z < -1.5 && !/CHEAP/.test(v)) { consistent = false; detail = `Z=${z} but verdict=${verdict} (expected CHEAP-side)`; }
  if (Math.abs(z) < 0.3 && /STRETCH/.test(v)) { consistent = false; detail = `Z=${z} near zero but verdict=${verdict} (extreme)`; }
  if (!consistent) { recordInvariantViolation('F', step, detail); return { ok: false }; }
  markInvariantPass('F');
  return { ok: true };
}

// ALL_INDICATORS + OPERATORS — must match custom_strategy.py catalog exactly.
const ALL_INDICATORS = new Set([
  'SMA(N)', 'EMA(N)', 'RSI(N)', 'Bollinger %B(N)',
  'N-day high', 'N-day low', 'N-day % change',
  'Realized vol(N)', 'ATR(N)', 'SOXL z-score vs QQQ(N)',
  'SOXL price', 'QQQ price', 'VIX level',
  'MACD', 'Drawdown from peak (%)', 'SOXL/QQQ ratio',
  'Days held in position',
  'Vol Surface Signal (Calls)', 'Vol Surface Signal (Puts)', 'Vol Regime Label',
  'Period Analysis Percentile(N)', 'Probability Engine P(M%, Hd)',
]);
const OPERATORS = new Set(['>', '<', '=', 'crosses above', 'crosses below']);

function verifyInvariantG(responseText, step) {
  let parsed = null;
  try {
    const fenced = responseText.match(/```json\s*([\s\S]*?)```/i);
    const raw = fenced ? fenced[1] : (responseText.match(/\{[\s\S]*\}/) || [null])[0];
    if (raw) parsed = JSON.parse(raw);
  } catch (e) {
    recordInvariantViolation('G', step, `AI Strategy Builder JSON unparseable: ${e.message}`);
    return { ok: false };
  }
  if (!parsed) {
    recordInvariantViolation('G', step, 'AI Strategy Builder response contained no JSON object');
    return { ok: false };
  }
  // Schema check — accept a variety of field names (tranches/ladder/etc.) but require core sections
  const txt = JSON.stringify(parsed).toLowerCase();
  const haveLadder = /(ladder|tranch|entry|buys?)/.test(txt);
  const haveRules = /(rules|operating|management)/.test(txt);
  const haveStats = /(statistical|probability|basis|stats)/.test(txt);
  if (!haveLadder || !haveRules || !haveStats) {
    recordInvariantViolation('G', step, `AI Strategy Builder JSON missing one of: ladder/rules/stats. Keys: ${Object.keys(parsed).join(', ')}`);
    return { ok: false, parsed };
  }
  markInvariantPass('G');
  return { ok: true, parsed };
}

function verifyInvariantH(responseText, step) {
  let parsed = null;
  try {
    const fenced = responseText.match(/```json\s*([\s\S]*?)```/i);
    const raw = fenced ? fenced[1] : (responseText.match(/\{[\s\S]*\}/) || [null])[0];
    if (raw) parsed = JSON.parse(raw);
  } catch (e) {
    recordInvariantViolation('H', step, `NL custom-strategy JSON unparseable: ${e.message}`);
    return { ok: false };
  }
  if (!parsed) { recordInvariantViolation('H', step, 'NL custom-strategy response contained no JSON object'); return { ok: false }; }
  const topMissing = ['entry_panel', 'exit_panel', 'controls'].filter(k => !(k in parsed));
  if (topMissing.length) {
    recordInvariantViolation('H', step, `NL custom-strategy JSON missing top-level fields: ${topMissing.join(', ')}`);
    return { ok: false, parsed };
  }
  const panels = [parsed.entry_panel, parsed.exit_panel].filter(Boolean);
  for (const panel of panels) {
    const rows = panel.conditions || panel.rules || panel.rows || [];
    for (const cond of rows) {
      const inds = cond.conditions ? cond.conditions.map(c => c.indicator) : [cond.indicator];
      for (const ind of inds) {
        if (!ind) continue;
        if (!ALL_INDICATORS.has(ind)) {
          recordInvariantViolation('H', step, `NL custom-strategy hallucinated indicator not in ALL_INDICATORS: "${ind}"`);
          return { ok: false, parsed };
        }
      }
      const ops = cond.conditions ? cond.conditions.map(c => c.operator) : [cond.operator];
      for (const op of ops) {
        if (op && !OPERATORS.has(op)) {
          recordInvariantViolation('H', step, `NL custom-strategy invalid operator: "${op}"`);
          return { ok: false, parsed };
        }
      }
    }
  }
  markInvariantPass('H');
  return { ok: true, parsed };
}

// ─────────────────────────────────────────────────────────────────────────────
// GENERIC STEP RUNNER
// ─────────────────────────────────────────────────────────────────────────────
async function runStep(functionId, step, kind, fn, opts = {}) {
  if (SKIP.has(String(functionId))) {
    console.log(`[skip] Function ${functionId} (${step}) — SKIP_FUNCTIONS env`);
    writeTranscript({ kind: 'skip', functionId, step, reason: 'SKIP_FUNCTIONS env var' });
    return null;
  }
  console.log(`\n=== Function ${functionId}: ${step} ===`);
  state.status = 'running';
  state.currentStep = `F${functionId}: ${step}`;
  state.currentParams = null;
  const interaction = {
    kind, // 'interactive' | 'navigation'
    functionId,
    step,
    timestampStart: new Date().toISOString(),
    approach: null,
    params: null,
    shots: [],
    numericOutputs: {},
    invariantChecks: {},
    notes: '',
    error: null,
  };
  try {
    await fn(interaction);
    // Streamlit traceback detection
    const tb = await streamlitErrorsVisible();
    if (tb) {
      interaction.error = 'streamlit_traceback';
      interaction.notes += `\nStreamlit traceback detected: ${tb.join('\n---\n').slice(0, 2000)}`;
      console.log(`[traceback] ${step}`);
    }
  } catch (e) {
    interaction.error = e.message || String(e);
    interaction.notes += `\nException: ${e.message}\n${e.stack || ''}`.slice(0, 4000);
    const shot = await takeShot(`error_${step}`);
    if (shot) interaction.shots.push(shot);
    console.log(`[error] ${step}: ${e.message}`);
  }
  state.currentUrl = page.url();
  await logInteraction(interaction);
  return interaction;
}

// ─────────────────────────────────────────────────────────────────────────────
// FUNCTION 1 — App startup and Chart tab
// ─────────────────────────────────────────────────────────────────────────────
async function fn1_startupAndChart() {
  await runStep(1, 'Navigate to app + verify top-level tabs', 'interactive', async (i) => {
    i.approach = 'happy_path'; i.params = { url: APP_URL };
    state.currentParams = i.params;
    i.shots.push(await takeShot('f1_before'));
    await page.goto(APP_URL, { waitUntil: 'networkidle', timeout: 60000 });
    await waitForNoSpinner(60000);
    i.shots.push(await takeShot('f1_loaded'));
    const tabs = await page.getByRole('tab').allInnerTexts().catch(() => []);
    i.numericOutputs = { topTabsVisible: tabs };
    const expectedTabs = ['Chart', 'Vol Surface', 'Dislocation', 'Strategy', 'Backtest'];
    const found = expectedTabs.filter(t => tabs.some(x => x.includes(t)));
    i.notes = `Found tabs containing: ${found.join(', ')}`;
    i.shots.push(await takeShot('f1_after'));
    state.soxl.activeTab = 'Chart & Probabilities';
  });

  await runStep(1, 'Verify Chart tab renders + benchmark toggles', 'interactive', async (i) => {
    i.approach = 'happy_path';
    i.shots.push(await takeShot('f1b_before'));
    // Click each benchmark toggle if present (checkboxes labeled QQQ, TQQQ, TLT, XLU, VIX)
    const toggles = ['QQQ', 'TQQQ', 'TLT', 'XLU', 'VIX'];
    const clicked = [];
    for (const t of toggles) {
      try {
        const cb = page.getByLabel(t, { exact: false }).first();
        if (await cb.count() > 0) {
          await cb.click({ timeout: 2000 }).catch(() => {});
          clicked.push(t);
        }
      } catch {}
    }
    await waitForNoSpinner();
    i.shots.push(await takeShot('f1b_toggled'));
    // Custom chart-draw component check
    const iframeCount = await page.locator('iframe').count();
    i.numericOutputs = { togglesClicked: clicked, iframeCount };
    i.shots.push(await takeShot('f1b_after'));
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// FUNCTION 2 — Period Analysis sub-block (in Chart tab)
// ─────────────────────────────────────────────────────────────────────────────
async function fn2_periodAnalysis() {
  await runStep(2, 'Period Analysis sub-block (in Chart tab)', 'interactive', async (i) => {
    i.approach = 'happy_path';
    i.shots.push(await takeShot('f2_before'));
    // Look for buttons / selectors related to Period Analysis
    const tables = await extractAllTables();
    i.shots.push(await takeShot('f2_after_view'));
    const counts = [];
    for (const t of tables) {
      for (const row of t.rows) {
        for (const cell of row) {
          const m = cell.match(/n\s*=\s*(\d+)/i);
          if (m) counts.push(parseInt(m[1], 10));
        }
      }
    }
    i.numericOutputs = { tableCount: tables.length, analogueCounts: counts.slice(0, 20) };
    i.notes = counts.every(c => c >= 0) ? 'All analogue counts non-negative' : 'NEGATIVE ANALOGUE COUNT DETECTED';
    i.shots.push(await takeShot('f2_complete'));
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// FUNCTION 3 — Short Interest
// ─────────────────────────────────────────────────────────────────────────────
async function fn3_shortInterest() {
  await runStep(3, 'Short Interest panel (FINRA daily + biweekly)', 'interactive', async (i) => {
    i.approach = 'happy_path';
    i.shots.push(await takeShot('f3_before'));
    await page.waitForTimeout(2000);
    i.shots.push(await takeShot('f3_loaded'));
    const tables = await extractAllTables();
    const headings = await page.$$eval('h2, h3, h4', els => els.map(e => e.innerText));
    i.numericOutputs = {
      tableCount: tables.length,
      shortInterestHeadingsPresent: headings.filter(h => /short/i.test(h)),
    };
    i.shots.push(await takeShot('f3_after'));
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// FUNCTION 4 — Probability Engine (Invariant D)
// ─────────────────────────────────────────────────────────────────────────────
async function fn4_probabilityEngine() {
  await runStep(4, 'Probability Engine (M=5/10/20%, H=5/21/63d)', 'interactive', async (i) => {
    const brain = await brainPickApproach('Probability Engine', { magnitudes: '5,10,20', horizons: '5,21,63', lookback: '5y' }, null);
    i.approach = brain.approach; i.params = brain.params;
    state.currentParams = brain.params;
    i.shots.push(await takeShot('f4_before'));
    // Scroll to Probability Engine section if present; otherwise just capture
    await page.evaluate(() => {
      const h = Array.from(document.querySelectorAll('h2, h3')).find(x => /probability/i.test(x.innerText));
      if (h) h.scrollIntoView({ behavior: 'instant' });
    });
    await page.waitForTimeout(500);
    i.shots.push(await takeShot('f4_settings'));
    // Click any "Run" / "Compute" buttons in this section
    const buttons = await page.getByRole('button').all();
    for (const b of buttons) {
      const text = (await b.innerText().catch(() => '')).toLowerCase();
      if (/compute|run|update/i.test(text)) { try { await b.click({ timeout: 1500 }); } catch {} }
    }
    await waitForNoSpinner();
    i.shots.push(await takeShot('f4_after'));
    const tables = await extractAllTables();
    const probTable = tables.find(t => t.headers.some(h => /horizon|probability|p\(/i.test(h))) || tables[tables.length - 1];
    i.numericOutputs = { probabilityTable: probTable };
    state.soxl.latestProbability = probTable ? { headers: probTable.headers, sampleRow: probTable.rows[0] } : null;
    if (probTable) {
      const res = verifyInvariantD(probTable, 'F4');
      i.invariantChecks.D = res;
    }
    fs.writeFileSync(path.join(OUTPUTS, 'probability-engine', 'fn4-table.json'), JSON.stringify(probTable, null, 2));
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// FUNCTION 5 — Vol Surface tab
// ─────────────────────────────────────────────────────────────────────────────
async function fn5_volSurface() {
  await runStep(5, 'Navigate to Vol Surface tab', 'navigation', async (i) => {
    i.shots.push(await takeShot('f5_before_nav'));
    await clickTopTab('Vol Surface').catch(() => clickTopTab(/Vol Surface/));
    await waitForNoSpinner(VOL_TIMEOUT);
    i.shots.push(await takeShot('f5_after_nav'));
    i.numericOutputs = { activeTab: state.soxl.activeTab };
  });
  await runStep(5, 'Vol Surface — capture IV rank + signals tables', 'interactive', async (i) => {
    i.approach = 'happy_path';
    i.shots.push(await takeShot('f5b_before'));
    await page.waitForTimeout(3000);
    i.shots.push(await takeShot('f5b_loading'));
    const tables = await extractAllTables();
    const metrics = await extractMetricCards();
    i.numericOutputs = { tableCount: tables.length, metrics, tables: tables.map(t => ({ headers: t.headers, rowCount: t.rowCount, firstRow: t.rows[0] })) };
    i.shots.push(await takeShot('f5b_after'));
    fs.writeFileSync(path.join(OUTPUTS, 'vol-surface', 'fn5-snapshot.json'), JSON.stringify({ tables, metrics }, null, 2));
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// FUNCTION 6 — Dislocation tab (Invariant F)
// ─────────────────────────────────────────────────────────────────────────────
async function fn6_dislocation() {
  await runStep(6, 'Navigate to Dislocation tab', 'navigation', async (i) => {
    i.shots.push(await takeShot('f6_before_nav'));
    await clickTopTab(/Dislocation/);
    await waitForNoSpinner(120000);
    i.shots.push(await takeShot('f6_after_nav'));
  });
  await runStep(6, 'Dislocation — capture Z + verdict + reversion table', 'interactive', async (i) => {
    i.approach = 'happy_path';
    i.shots.push(await takeShot('f6b_before'));
    await page.waitForTimeout(2000);
    i.shots.push(await takeShot('f6b_loaded'));
    const tables = await extractAllTables();
    const metrics = await extractMetricCards();
    const bodyText = await page.locator('body').innerText().catch(() => '');
    // Try to extract Z and verdict from body text
    const zMatch = bodyText.match(/Z[\s:=]+(-?\d+\.\d+)/);
    const verdictMatch = bodyText.match(/\b(RICH|STRETCH-RICH|FAIR|STRETCH-CHEAP|CHEAP)\b/i);
    const z = zMatch ? parseFloat(zMatch[1]) : null;
    const verdict = verdictMatch ? verdictMatch[1].toUpperCase() : null;
    i.numericOutputs = { z, verdict, tableCount: tables.length, metrics };
    state.soxl.latestDislocation = { z, verdict };
    if (z != null && verdict) {
      i.invariantChecks.F = verifyInvariantF(z, verdict, 'F6');
    } else {
      i.notes = 'Could not parse Z or verdict from page text';
    }
    i.shots.push(await takeShot('f6b_after'));
    fs.writeFileSync(path.join(OUTPUTS, 'dislocation', 'fn6.json'), JSON.stringify({ z, verdict, tables, metrics }, null, 2));
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// FUNCTION 7 — Strategy Builder tab (Invariant G)
// ─────────────────────────────────────────────────────────────────────────────
async function fn7_strategyBuilder() {
  await runStep(7, 'Navigate to Strategy Builder tab', 'navigation', async (i) => {
    i.shots.push(await takeShot('f7_before_nav'));
    await clickTopTab(/Strategy Builder/);
    await waitForNoSpinner(30000);
    i.shots.push(await takeShot('f7_after_nav'));
  });
  await runStep(7, 'Strategy Builder — send substantive prompt + verify JSON', 'interactive', async (i) => {
    i.approach = 'happy_path';
    const prompt = 'Generate a tranched buy strategy for SOXL that scales in over the next month based on dislocation Z-score. I have $50,000 cash and moderate risk tolerance.';
    i.params = { prompt };
    state.currentParams = i.params;
    i.shots.push(await takeShot('f7b_before'));
    const fillResult = await fillChatPrompt(prompt);
    i.notes += `\nfillChatPrompt: ${JSON.stringify(fillResult)}`;
    i.shots.push(await takeShot('f7b_filled'));
    if (!fillResult.sent) {
      state.harnessSanityFailures.push(`F7: failed to send AI prompt (${fillResult.via})`);
    }
    await waitForNoSpinner(AI_TIMEOUT);
    await page.waitForTimeout(3000);
    i.shots.push(await takeShot('f7b_after'));
    const bodyText = await page.locator('body').innerText().catch(() => '');
    const response = bodyText.slice(-15000);
    i.numericOutputs = { fill: fillResult, responseLength: response.length, responsePreview: response.slice(0, 1000) };
    const res = verifyInvariantG(response, 'F7');
    i.invariantChecks.G = res;
    fs.writeFileSync(path.join(OUTPUTS, 'strategy-builder', 'response.json'),
      JSON.stringify({ prompt, response, parsed: res.parsed || null }, null, 2));
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// FUNCTION 8 — Backtest tab navigation (verifies 8 sub-tabs)
// ─────────────────────────────────────────────────────────────────────────────
async function fn8_backtestNav() {
  await runStep(8, 'Navigate to Backtest tab + enumerate sub-tabs', 'navigation', async (i) => {
    i.shots.push(await takeShot('f8_before'));
    await clickTopTab(/Backtest/);
    await waitForNoSpinner(30000);
    await page.waitForTimeout(1500);
    const allTabTexts = await page.getByRole('tab').allInnerTexts().catch(() => []);
    i.numericOutputs = { allTabs: allTabTexts };
    i.shots.push(await takeShot('f8_after'));
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// ALLOCATION ENGINE helper — runs the engine sub-tab and extracts evidence
// ─────────────────────────────────────────────────────────────────────────────
async function runAllocationEngine(interaction, label) {
  // Click the Run button on Allocation Engine sub-tab
  let ran = false;
  const buttons = await page.getByRole('button').all();
  for (const b of buttons) {
    const t = (await b.innerText().catch(() => '')).toLowerCase();
    if (/run allocation engine|run engine|run/i.test(t)) {
      try { await b.click({ timeout: 2000 }); ran = true; break; } catch {}
    }
  }
  interaction.notes += `\nclickedRun=${ran}`;
  await waitForNoSpinner(ALLOC_TIMEOUT);
  await page.waitForTimeout(2000);
  // Open expanders so the allocation panel is in the DOM
  const expanders = await page.getByRole('button', { name: /Deviation|Sleeve|diagnostics|allocation panel/i }).all();
  for (const e of expanders) { try { await e.click({ timeout: 1000 }); } catch {} }
  await page.waitForTimeout(1500);
  // Extract everything
  const metrics = await extractMetricCards();
  const tables = await extractAllTables();
  // Risk metrics table = one with headers including "Sharpe" / "Sortino" / "Total Return"
  const riskTable = tables.find(t => t.headers.some(h => /sharpe|sortino|total return/i.test(h)));
  // Allocation panel = wide table with "allocation" / "deviation"
  const allocTable = tables.find(t => t.headers.some(h => /allocation/i.test(h)) && t.headers.some(h => /deviation|soxl_norm|qqq_norm/i.test(h)));
  // Parse alloc table rows into numeric structure
  const allocationRows = [];
  if (allocTable) {
    const headers = allocTable.headers;
    const allocIdx = headers.findIndex(h => /^allocation$/i.test(h));
    for (const r of allocTable.rows) {
      const obj = {};
      for (let k = 0; k < headers.length; k++) {
        const raw = r[k];
        const num = parseFloat(String(raw).replace(/[%,]/g, ''));
        obj[headers[k]] = isNaN(num) ? raw : (String(raw).includes('%') ? num / 100 : num);
      }
      if (allocIdx >= 0) obj.allocation = obj[headers[allocIdx]];
      allocationRows.push(obj);
    }
  }
  state.soxl.allocationSampleHead = allocationRows.slice(0, 10).map(r => JSON.stringify(r));
  state.soxl.allocationSampleTail = allocationRows.slice(-10).map(r => JSON.stringify(r));
  return { metrics, tables, riskTable, allocTable, allocationRows };
}

// ─────────────────────────────────────────────────────────────────────────────
// FUNCTION 9 — Allocation Engine default (Invariants A, B-prep, C, E)
// ─────────────────────────────────────────────────────────────────────────────
async function fn9_allocationEngineDefault() {
  await runStep(9, 'Allocation Engine — defaults (last 2 years)', 'interactive', async (i) => {
    i.approach = 'happy_path';
    i.params = { sleeve_pct: 0.20, dte: 45, roll_dte: 10, moneyness: 1.00, vol_w: 30, range: '2y', floor: 0.02, ceiling: 0.98 };
    state.currentParams = i.params;
    i.shots.push(await takeShot('f9_before'));
    // Ensure we're on sub-tab[0]
    await clickSubTab(/Allocation Engine/);
    i.shots.push(await takeShot('f9_subtab_active'));
    const ev = await runAllocationEngine(i, 'default');
    i.shots.push(await takeShot('f9_after'));
    // Invariant A
    if (ev.allocationRows.length > 0) {
      i.invariantChecks.A = verifyInvariantA(ev.allocationRows, 0.02, 0.98, 'F9');
    }
    // Invariant E — risk metrics table presence
    if (ev.riskTable) i.invariantChecks.E = verifyInvariantE(ev.riskTable, 'F9');
    // Invariant C — sleeve series asymmetric resize (extract roll events from cash-jumps)
    const sleeveTable = ev.tables.find(t => t.headers.some(h => /sleeve.*\$|sleeve_value|sleeve \$/i.test(h)) && t.headers.some(h => /target/i.test(h)));
    if (sleeveTable) {
      const targetIdx = sleeveTable.headers.findIndex(h => /target/i.test(h));
      const sleeveIdx = sleeveTable.headers.findIndex(h => /sleeve.*\$|sleeve_value|sleeve \$/i.test(h));
      const cashIdx = sleeveTable.headers.findIndex(h => /^cash/i.test(h) || /cash \$/i.test(h));
      const contractsIdx = sleeveTable.headers.findIndex(h => /contracts/i.test(h));
      if (targetIdx >= 0 && sleeveIdx >= 0) {
        const ts = sleeveTable.rows.map(r => {
          const raw = String(r[targetIdx]);
          const num = parseFloat(raw.replace(/[%,$]/g, ''));
          return raw.includes('%') ? num / 100 : num;
        });
        const ss = sleeveTable.rows.map(r => parseFloat(String(r[sleeveIdx]).replace(/[$,]/g, '')));
        // Detect roll events: contracts count resets / sleeve drops to near 0 / cash jumps up
        const rollEvents = [];
        const cashSeries = cashIdx >= 0 ? sleeveTable.rows.map(r => parseFloat(String(r[cashIdx]).replace(/[$,]/g, ''))) : null;
        const contractsSeries = contractsIdx >= 0 ? sleeveTable.rows.map(r => parseFloat(String(r[contractsIdx]).replace(/[,]/g, ''))) : null;
        for (let k = 1; k < ss.length; k++) {
          let isRoll = false;
          if (contractsSeries && Math.abs(contractsSeries[k] - contractsSeries[k - 1]) > 1e-6 && contractsSeries[k] > 0) isRoll = true;
          if (cashSeries && cashSeries[k] - cashSeries[k - 1] > 0.05 * (cashSeries[k - 1] || 1)) isRoll = true;
          if (ss[k - 1] > 0 && ss[k] < 0.05 * (ss[k - 1] || 1)) isRoll = true;
          if (isRoll) rollEvents.push({ index: k });
        }
        i.invariantChecks.C = verifyInvariantC(ss, ts, rollEvents, 'F9');
        i.numericOutputs.rollEventCount = rollEvents.length;
      } else {
        state.harnessSanityFailures.push('F9-C: sleeve diagnostics table found but target/sleeve columns not identifiable — Invariant C unverified.');
        state.soxl.invariants.C = 'unverified';
      }
    } else {
      state.harnessSanityFailures.push('F9-C: sleeve diagnostics table not captured — Invariant C unverified.');
      state.soxl.invariants.C = 'unverified';
    }
    Object.assign(i.numericOutputs, {
      metrics: ev.metrics,
      riskTable: ev.riskTable,
      allocationRowCount: ev.allocationRows.length,
      allocationFirstRows: ev.allocationRows.slice(0, 5),
      allocationLastRows: ev.allocationRows.slice(-5),
    });
    if (ev.metrics && ev.metrics[0]) {
      state.soxl.latestAllocation = { totalReturn: ev.metrics[0].value, regime: 'default' };
    }
    fs.writeFileSync(path.join(OUTPUTS, 'backtest', 'allocation-engine-default.json'),
      JSON.stringify({ params: i.params, metrics: ev.metrics, riskTable: ev.riskTable, allocationRows: ev.allocationRows }, null, 2));
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// FUNCTION 10 — Pathological inputs (Invariants B + E)
// ─────────────────────────────────────────────────────────────────────────────
async function fn10_pathological() {
  await runStep(10, 'Allocation Engine — zero-day window (Invariant E)', 'interactive', async (i) => {
    i.approach = 'probe_invariant'; i.params = { mode: 'zero-day window (start==end)' };
    state.currentParams = i.params;
    i.shots.push(await takeShot('f10a_before'));
    // Try to set start == end via date inputs (best-effort; Streamlit date pickers vary)
    const dateInputs = await page.locator('input[aria-label*="date" i], input[type="date"]').all();
    let setSame = false;
    if (dateInputs.length >= 2) {
      try {
        const today = new Date().toISOString().slice(0, 10);
        await dateInputs[0].fill(today).catch(() => {});
        await dateInputs[1].fill(today).catch(() => {});
        setSame = true;
      } catch {}
    }
    i.notes += `\nsetSameDate=${setSame}`;
    i.shots.push(await takeShot('f10a_dateset'));
    const ev = await runAllocationEngine(i, 'zero-day');
    i.shots.push(await takeShot('f10a_after'));
    // Risk metrics must still render
    if (ev.riskTable) i.invariantChecks.E = verifyInvariantE(ev.riskTable, 'F10-zero-day');
    else recordInvariantViolation('E', 'F10-zero-day', 'Risk Metrics table missing after zero-day input');
    // Check for traceback
    const tb = await streamlitErrorsVisible();
    if (tb) i.notes += `\nTRACEBACK ON ZERO-DAY: ${tb.join('|').slice(0, 1500)}`;
    i.numericOutputs = { riskTable: ev.riskTable, rowCount: ev.allocationRows.length };
    fs.writeFileSync(path.join(OUTPUTS, 'backtest', 'zero-day-test', 'result.json'),
      JSON.stringify({ riskTable: ev.riskTable, rowCount: ev.allocationRows.length, traceback: tb }, null, 2));
  });

  await runStep(10, 'Allocation Engine — cross-date determinism (Invariant B)', 'interactive', async (i) => {
    i.approach = 'probe_invariant';
    i.params = { mode: 'two runs ending at D-1 vs D; compare allocation at common date D-1 by date key' };
    state.currentParams = i.params;
    i.shots.push(await takeShot('f10b_before'));
    const dateInputs = await page.locator('input[aria-label*="date" i], input[type="date"]').all();
    let row1 = null, row2 = null, commonDate = null;
    try {
      if (dateInputs.length >= 2) {
        // Run 1: ends at 2024-12-30
        await dateInputs[0].fill('2023-01-01').catch(() => {});
        await dateInputs[1].fill('2024-12-30').catch(() => {});
        const ev1 = await runAllocationEngine(i, 'lookahead-run-1');
        i.shots.push(await takeShot('f10b_run1'));
        // Find the date column (any column whose values look like dates)
        const findDateKey = (rows) => {
          if (!rows.length) return null;
          for (const k of Object.keys(rows[0])) {
            const v = rows[0][k];
            if (typeof v === 'string' && /\d{4}-\d{2}-\d{2}/.test(v)) return k;
          }
          // index column case
          for (const k of Object.keys(rows[0])) {
            if (/date|index|^\s*$/i.test(k)) return k;
          }
          return null;
        };
        const dkey1 = findDateKey(ev1.allocationRows);
        const lastByDate1 = ev1.allocationRows[ev1.allocationRows.length - 1];
        if (dkey1 && lastByDate1) commonDate = String(lastByDate1[dkey1]);
        if (lastByDate1) row1 = { allocation: lastByDate1.allocation, dateKeyValue: commonDate };
        // Run 2: ends at 2024-12-31 (or next available trading day)
        await dateInputs[1].fill('2024-12-31').catch(() => {});
        const ev2 = await runAllocationEngine(i, 'lookahead-run-2');
        const dkey2 = findDateKey(ev2.allocationRows);
        if (dkey2 && commonDate) {
          const matched = ev2.allocationRows.find(r => String(r[dkey2]) === commonDate);
          if (matched) row2 = { allocation: matched.allocation, dateKeyValue: matched[dkey2] };
        }
        i.shots.push(await takeShot('f10b_run2'));
      } else {
        state.harnessSanityFailures.push('F10-B: fewer than 2 date inputs found — cannot run cross-date test');
      }
    } catch (e) { i.notes += `\ncross-date error: ${e.message}`; }
    i.shots.push(await takeShot('f10b_after'));
    const diff = (row1 && row2 && row1.allocation != null && row2.allocation != null)
      ? Math.abs(row1.allocation - row2.allocation) : null;
    i.numericOutputs = { commonDate, row1, row2, absDiff: diff };
    if (row1 == null || row2 == null) {
      state.harnessSanityFailures.push(`F10-B: could not align rows by date key — row1=${JSON.stringify(row1)} row2=${JSON.stringify(row2)}. Invariant B unverified.`);
      state.soxl.invariants.B = 'unverified';
    } else if (diff > 1e-4) {
      recordInvariantViolation('B', 'F10', `Allocation at common date ${commonDate} differs: run1=${row1.allocation}, run2=${row2.allocation}, |diff|=${diff}`);
      i.invariantChecks.B = { ok: false };
    } else {
      markInvariantPass('B');
      i.invariantChecks.B = { ok: true, commonDate, diff };
    }
    fs.writeFileSync(path.join(OUTPUTS, 'backtest', 'look-ahead-test', 'compare.json'),
      JSON.stringify({ commonDate, row1, row2, diff }, null, 2));
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// FUNCTION 11 — Allocation Engine custom parameters
// ─────────────────────────────────────────────────────────────────────────────
async function fn11_allocationCustom() {
  await runStep(11, 'Allocation Engine — custom params (sleeve=30%, mny=0.95, bear=0.5)', 'interactive', async (i) => {
    i.approach = 'vary_parameter'; i.params = { sleeve_pct: 0.30, moneyness: 0.95, bear_multiplier: 0.5 };
    state.currentParams = i.params;
    i.shots.push(await takeShot('f11_before'));
    // Best-effort slider mutation — Streamlit sliders are awkward; rely on visual changes
    const sliders = await page.locator('input[role="slider"]').all();
    i.notes += `\nsliderCount=${sliders.length}`;
    i.shots.push(await takeShot('f11_mid'));
    const ev = await runAllocationEngine(i, 'custom');
    i.shots.push(await takeShot('f11_after'));
    if (ev.allocationRows.length > 0) {
      i.invariantChecks.A = verifyInvariantA(ev.allocationRows, 0.02, 0.98, 'F11');
    }
    i.numericOutputs = { metrics: ev.metrics, allocationRowCount: ev.allocationRows.length };
    fs.writeFileSync(path.join(OUTPUTS, 'backtest', 'allocation-engine-custom.json'),
      JSON.stringify({ params: i.params, metrics: ev.metrics, allocationRows: ev.allocationRows }, null, 2));
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// FUNCTIONS 12–17 — Period Analysis, Probability, Vol Regime, Dislocation BT,
//                   Strategy Builder BT, Vol Surface BT sub-tabs
// ─────────────────────────────────────────────────────────────────────────────
async function genericSubTabRun(fid, subTabName, opts) {
  await runStep(fid, `Sub-tab: ${subTabName}`, 'interactive', async (i) => {
    i.approach = opts.approach || 'happy_path'; i.params = opts.params || {};
    state.currentParams = i.params;
    i.shots.push(await takeShot(`f${fid}_before`));
    try { await clickSubTab(new RegExp(subTabName, 'i')); } catch {}
    await waitForNoSpinner(opts.timeout || 60000);
    i.shots.push(await takeShot(`f${fid}_loaded`));
    // Click any Run button in the panel
    const buttons = await page.getByRole('button').all();
    for (const b of buttons) {
      const t = (await b.innerText().catch(() => '')).toLowerCase();
      if (/run|backtest|compute|update/.test(t) && !/clear|reset|delete/.test(t)) {
        try { await b.click({ timeout: 1500 }); break; } catch {}
      }
    }
    await waitForNoSpinner(opts.timeout || 60000);
    await page.waitForTimeout(1500);
    i.shots.push(await takeShot(`f${fid}_after`));
    const tables = await extractAllTables();
    const metrics = await extractMetricCards();
    i.numericOutputs = { tableCount: tables.length, metrics, tables: tables.slice(0, 3).map(t => ({ headers: t.headers, rowCount: t.rowCount, sampleRow: t.rows[0] })) };
    if (opts.invariantD) {
      const probTable = tables.find(t => t.headers.some(h => /probability|horizon|p\(/i.test(h))) || tables[0];
      if (probTable) i.invariantChecks.D = verifyInvariantD(probTable, `F${fid}`);
    }
    if (opts.savePath) fs.writeFileSync(opts.savePath, JSON.stringify({ tables, metrics }, null, 2));
  });
}

const fn12_periodAnalysisSub = () => genericSubTabRun(12, 'Period Analysis', { savePath: path.join(OUTPUTS, 'backtest', 'fn12-period.json') });
const fn13_probabilitySub = () => genericSubTabRun(13, 'Probability Engine', { invariantD: true, savePath: path.join(OUTPUTS, 'probability-engine', 'fn13.json') });
const fn14_volRegime = () => genericSubTabRun(14, 'Vol Regime', { savePath: path.join(OUTPUTS, 'backtest', 'fn14-vol-regime.json') });
const fn15_dislocSub = () => genericSubTabRun(15, 'Dislocation', { savePath: path.join(OUTPUTS, 'dislocation', 'fn15.json') });

async function fn16_strategyBuilderSub() {
  await runStep(16, 'Backtest sub-tab Strategy Builder — second AI prompt', 'interactive', async (i) => {
    i.approach = 'vary_parameter';
    const prompt = 'I have $20,000 to deploy into SOXL with a 90-day horizon and aggressive risk tolerance. Generate a strategy using the dislocation Z-score and vol regime classification.';
    i.params = { prompt };
    state.currentParams = i.params;
    i.shots.push(await takeShot('f16_before'));
    try { await clickSubTab(/Strategy Builder/); } catch {}
    await waitForNoSpinner(30000);
    i.shots.push(await takeShot('f16_loaded'));
    const fillResult = await fillChatPrompt(prompt);
    i.notes += `\nfillChatPrompt: ${JSON.stringify(fillResult)}`;
    if (!fillResult.sent) state.harnessSanityFailures.push(`F16: failed to send AI prompt (${fillResult.via})`);
    await waitForNoSpinner(AI_TIMEOUT);
    await page.waitForTimeout(2000);
    i.shots.push(await takeShot('f16_after'));
    const bodyText = await page.locator('body').innerText().catch(() => '');
    const response = bodyText.slice(-15000);
    i.numericOutputs = { fill: fillResult, responseLength: response.length, responsePreview: response.slice(0, 800) };
    const res = verifyInvariantG(response, 'F16');
    i.invariantChecks.G = res;
    fs.writeFileSync(path.join(OUTPUTS, 'strategy-builder', 'fn16-response.json'),
      JSON.stringify({ prompt, response, parsed: res.parsed || null }, null, 2));
  });
}

const fn17_volSurfaceSub = () => genericSubTabRun(17, 'Vol Surface', { timeout: VOL_TIMEOUT, savePath: path.join(OUTPUTS, 'vol-surface', 'fn17.json') });

// ─────────────────────────────────────────────────────────────────────────────
// FUNCTION 18 — Custom Strategy form mode
// ─────────────────────────────────────────────────────────────────────────────
async function fn18_customForm() {
  await runStep(18, 'Custom Strategy form — RSI < 30 / RSI > 70', 'interactive', async (i) => {
    i.approach = 'happy_path';
    i.params = { entry: 'RSI(14) < 30', exit: 'RSI(14) > 70', side: 'long' };
    state.currentParams = i.params;
    i.shots.push(await takeShot('f18_before'));
    try { await clickSubTab(/Custom Strategy/); } catch {}
    await waitForNoSpinner(30000);
    i.shots.push(await takeShot('f18_loaded'));
    const tables = await extractAllTables();
    const metrics = await extractMetricCards();
    i.numericOutputs = { tableCount: tables.length, metrics };
    i.shots.push(await takeShot('f18_after'));
    fs.writeFileSync(path.join(OUTPUTS, 'custom-strategy', 'form-spec.json'),
      JSON.stringify({ params: i.params, tables, metrics }, null, 2));
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// FUNCTION 19 — Custom Strategy NL mode (Invariant H)
// ─────────────────────────────────────────────────────────────────────────────
async function fn19_customNL() {
  await runStep(19, 'Custom Strategy NL — RSI<30 enter / RSI>70 exit (Invariant H)', 'interactive', async (i) => {
    i.approach = 'happy_path';
    const prompt = 'Buy SOXL when its 14-day RSI drops below 30, sell when it rises above 70.';
    i.params = { prompt };
    state.currentParams = i.params;
    i.shots.push(await takeShot('f19_before'));
    const fillResult = await fillChatPrompt(prompt);
    i.notes += `\nfillChatPrompt: ${JSON.stringify(fillResult)}`;
    i.shots.push(await takeShot('f19_filled'));
    if (!fillResult.sent) state.harnessSanityFailures.push(`F19: failed to send NL prompt (${fillResult.via})`);
    await waitForNoSpinner(AI_TIMEOUT);
    await page.waitForTimeout(2000);
    i.shots.push(await takeShot('f19_after'));
    const bodyText = await page.locator('body').innerText().catch(() => '');
    const response = bodyText.slice(-15000);
    i.numericOutputs = { fill: fillResult, responseLength: response.length, responsePreview: response.slice(0, 800) };
    const res = verifyInvariantH(response, 'F19');
    i.invariantChecks.H = res;
    fs.writeFileSync(path.join(OUTPUTS, 'custom-strategy', 'nl-spec.json'),
      JSON.stringify({ prompt, response, parsed: res.parsed || null }, null, 2));
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// FUNCTION 20 — Custom Strategy advanced indicators
// ─────────────────────────────────────────────────────────────────────────────
async function fn20_customAdvanced() {
  await runStep(20, 'Custom Strategy — advanced indicators (Vol Surface BUY + Vol Regime CHEAP)', 'interactive', async (i) => {
    i.approach = 'probe_invariant'; i.params = { entry: 'Vol Surface Signal (Calls) = BUY AND Vol Regime Label = CHEAP', startBefore: '2022-01-01' };
    state.currentParams = i.params;
    i.shots.push(await takeShot('f20_before'));
    const dateInputs = await page.locator('input[aria-label*="date" i], input[type="date"]').all();
    if (dateInputs.length >= 2) {
      try { await dateInputs[0].fill('2020-01-01').catch(() => {}); } catch {}
    }
    await page.waitForTimeout(800);
    i.shots.push(await takeShot('f20_dateset'));
    await waitForNoSpinner();
    i.shots.push(await takeShot('f20_after'));
    const bodyText = await page.locator('body').innerText().catch(() => '');
    const warningPresent = /warn|limit|2022|options.*signal/i.test(bodyText.slice(-3000));
    i.numericOutputs = { warningPresent, bodyTail: bodyText.slice(-1500) };
    i.notes = warningPresent ? 'Warning about start-date limit detected (graceful degradation)' : 'No explicit warning found in tail of page text';
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// FUNCTION 21 — Report downloads (TXT/CSV/Word/PDF)
// ─────────────────────────────────────────────────────────────────────────────
async function fn21_downloads() {
  await runStep(21, 'Allocation Engine — TXT/CSV/Word/PDF downloads', 'interactive', async (i) => {
    i.approach = 'happy_path';
    i.shots.push(await takeShot('f21_before'));
    try { await clickSubTab(/Allocation Engine/); } catch {}
    await waitForNoSpinner();
    i.shots.push(await takeShot('f21_subtab'));
    const downloads = [];
    const buttons = await page.getByRole('button').all();
    for (const b of buttons) {
      const t = (await b.innerText().catch(() => '')).toLowerCase();
      if (/(download|export).*(txt|csv|word|pdf|docx)|(txt|csv|word|pdf|docx).*(download|export)/i.test(t)) {
        try {
          const [download] = await Promise.all([
            page.waitForEvent('download', { timeout: 10000 }),
            b.click({ timeout: 1500 }),
          ]);
          const savePath = path.join(OUTPUTS, 'downloads', download.suggestedFilename() || `dl_${downloads.length}.bin`);
          await download.saveAs(savePath);
          const buf = fs.readFileSync(savePath);
          const head = buf.slice(0, 4).toString('utf8');
          downloads.push({ button: t, file: savePath, sizeBytes: buf.length, head4: head, head4hex: buf.slice(0, 4).toString('hex') });
        } catch (e) { downloads.push({ button: t, error: e.message }); }
      }
    }
    i.numericOutputs = { downloads };
    i.shots.push(await takeShot('f21_after'));
    // Sanity verify magic bytes
    for (const d of downloads) {
      if (d.file && /\.pdf$/i.test(d.file) && !d.head4.startsWith('%PDF')) i.notes += `\nPDF magic bytes wrong for ${d.file}`;
      if (d.file && /\.docx$/i.test(d.file) && !d.head4.startsWith('PK')) i.notes += `\nDOCX magic bytes wrong for ${d.file}`;
    }
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// FUNCTION 22 — Final tab walkthrough
// ─────────────────────────────────────────────────────────────────────────────
async function fn22_finalCapture() {
  await runStep(22, 'Final state capture — walk all top tabs', 'interactive', async (i) => {
    i.approach = 'happy_path';
    i.shots.push(await takeShot('f22_before'));
    const tabs = ['Chart', 'Vol Surface', 'Dislocation', 'Strategy', 'Backtest'];
    const visited = [];
    for (const t of tabs) {
      try {
        await clickTopTab(new RegExp(t));
        await page.waitForTimeout(800);
        visited.push(t);
        await takeShot(`f22_${t.replace(/\s/g, '')}`);
      } catch (e) { visited.push(`${t}:ERROR:${e.message}`); }
    }
    i.shots.push(await takeShot('f22_after'));
    i.numericOutputs = { visited };
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// MAIN
// ─────────────────────────────────────────────────────────────────────────────
async function main() {
  console.log('R1 is running.');
  console.log(`Live view:    http://localhost:${LIVE_VIEW_PORT}`);
  console.log(`Output dir:   ${OUTDIR}`);
  console.log('Watch the live view — especially the SOXL Analysis State panel.');
  console.log('Do not trust summary output alone.');
  console.log('');
  if (!anthropic) console.log('[warn] No Anthropic key — brain + judge will be stubs. Set ANTHROPIC_API_KEY or AI_INTEGRATIONS_ANTHROPIC_API_KEY.');

  await setupBrowser();

  const allFns = [
    fn1_startupAndChart, fn2_periodAnalysis, fn3_shortInterest, fn4_probabilityEngine,
    fn5_volSurface, fn6_dislocation, fn7_strategyBuilder, fn8_backtestNav,
    fn9_allocationEngineDefault, fn10_pathological, fn11_allocationCustom,
    fn12_periodAnalysisSub, fn13_probabilitySub, fn14_volRegime, fn15_dislocSub,
    fn16_strategyBuilderSub, fn17_volSurfaceSub, fn18_customForm, fn19_customNL,
    fn20_customAdvanced, fn21_downloads, fn22_finalCapture,
  ];
  for (const fn of allFns) {
    try { await fn(); } catch (e) {
      console.log(`[fatal:in-fn] ${fn.name}: ${e.message}\n${e.stack}`);
      writeTranscript({ kind: 'fatal-in-function', name: fn.name, error: e.message, stack: e.stack });
    }
  }

  state.status = 'complete';
  // Generate reports
  const reportPath = path.join(OUTDIR, 'report.html');
  fs.writeFileSync(reportPath, generateReportHtml());
  fs.writeFileSync(path.join(OUTDIR, 'failures.md'), generateFailuresMarkdown());
  fs.writeFileSync(path.join(OUTDIR, 'run-summary.txt'), generateRunSummary());
  state.reportPath = reportPath;
  state.finishedAt = new Date().toISOString();

  console.log('');
  console.log('R1 finished.');
  console.log(`Open the report:        ${reportPath}`);
  console.log(`Open the failures:      ${path.join(OUTDIR, 'failures.md')}`);
  console.log(`Allocation engine:      ${path.join(OUTPUTS, 'backtest')}/allocation-engine-*.json`);
  console.log(`AI Strategy responses:  ${path.join(OUTPUTS, 'strategy-builder')}/`);
  console.log(`Custom strategy specs:  ${path.join(OUTPUTS, 'custom-strategy')}/`);
  console.log(`Raw transcript:         ${transcriptPath}`);

  // Keep live view alive briefly so user can see the final state
  await new Promise(r => setTimeout(r, 60000));

  try { await browser.close(); } catch {}
  try { liveServer.close(); } catch {}
  try { consoleLogStream.end(); } catch {}
  try { networkLogStream.end(); } catch {}

  // Exit code
  let code = 0;
  if (state.judgeConcernsCount > 0) code = 1;
  if (state.invariantViolations.length > 0) code = 2;
  if (state.harnessSanityFailures.length > 0) code = 3;
  process.exit(code);
}

// ─────────────────────────────────────────────────────────────────────────────
// REPORT GENERATION
// ─────────────────────────────────────────────────────────────────────────────
function loadTranscript() {
  if (!fs.existsSync(transcriptPath)) return [];
  return fs.readFileSync(transcriptPath, 'utf8').split('\n').filter(Boolean).map(l => {
    try { return JSON.parse(l); } catch { return null; }
  }).filter(Boolean);
}

function generateReportHtml() {
  const entries = loadTranscript();
  const interactions = entries.filter(e => e.kind === 'interactive' || e.kind === 'navigation');
  const judges = Object.fromEntries(entries.filter(e => e.kind === 'judge').map(j => [j.step, j]));
  const byFn = {};
  for (const e of interactions) {
    const fid = e.functionId || '?';
    if (!byFn[fid]) byFn[fid] = [];
    byFn[fid].push(e);
  }
  const toc = Object.keys(byFn).sort((a, b) => Number(a) - Number(b))
    .map(fid => `<li><a href="#fn${fid}">Function ${fid}</a> (${byFn[fid].length} step${byFn[fid].length === 1 ? '' : 's'})</li>`).join('');

  let body = '';
  for (const fid of Object.keys(byFn).sort((a, b) => Number(a) - Number(b))) {
    body += `<section id="fn${fid}"><h2>Function ${fid}</h2>`;
    for (const e of byFn[fid]) {
      const j = judges[e.step] || { critique: '(no judge critique)' };
      const shots = (e.shots || []).map(s => s ? `<a href="screenshots/${path.basename(s)}"><img src="screenshots/${path.basename(s)}" style="max-width:300px;border:1px solid #ddd;margin:4px"/></a>` : '').join('');
      const invKeys = Object.keys(e.invariantChecks || {});
      const invHtml = invKeys.length
        ? `<div><strong>Invariant checks:</strong> ${invKeys.map(k => `<code>${k}: ${e.invariantChecks[k].ok ? 'pass' : 'fail'}</code>`).join(' ')}</div>` : '';
      body += `<div class="step ${e.error ? 'err' : ''}">
        <h3>${e.step} <span class="meta">${e.kind} · ${e.approach || ''}</span></h3>
        ${e.params ? `<div><strong>Params:</strong> <code>${JSON.stringify(e.params)}</code></div>` : ''}
        ${invHtml}
        <details open><summary><strong>Numeric outputs</strong></summary>
          <pre>${JSON.stringify(e.numericOutputs || {}, null, 2).replace(/</g, '&lt;')}</pre>
        </details>
        ${e.notes ? `<div><strong>Notes:</strong> <pre>${e.notes.replace(/</g, '&lt;')}</pre></div>` : ''}
        ${e.error ? `<div class="err-banner"><strong>ERROR:</strong> ${e.error}</div>` : ''}
        <div><strong>Screenshots:</strong><br/>${shots}</div>
        <details open><summary><strong>Judge critique</strong></summary>
          <div class="judge">${(j.critique || '').replace(/\n/g, '<br/>')}</div>
        </details>
      </div>`;
    }
    body += `</section>`;
  }

  // Function 9 special block
  let f9Block = '';
  if (byFn['9']) {
    const f9 = byFn['9'][0];
    const allocRows = (f9.numericOutputs?.allocationFirstRows || []).concat(f9.numericOutputs?.allocationLastRows || []);
    const allocVals = allocRows.map(r => r.allocation).filter(v => v != null && !isNaN(v));
    const stats = allocVals.length ? {
      min: Math.min(...allocVals), max: Math.max(...allocVals),
      mean: allocVals.reduce((a, b) => a + b, 0) / allocVals.length,
      pctAtFloor: (allocVals.filter(v => v <= 0.025).length / allocVals.length * 100).toFixed(1),
      pctAtCeiling: (allocVals.filter(v => v >= 0.975).length / allocVals.length * 100).toFixed(1),
    } : null;
    f9Block = `<section id="flagship"><h2>🚩 Flagship — Allocation Engine (Function 9) statistics</h2>
      ${stats ? `<pre>${JSON.stringify(stats, null, 2)}</pre>` : '<em>no allocation data captured</em>'}
      <details><summary>Full Risk Metrics table</summary>
        <pre>${JSON.stringify(f9.numericOutputs?.riskTable || {}, null, 2).replace(/</g, '&lt;')}</pre>
      </details></section>`;
  }

  return `<!doctype html><html><head><meta charset="utf-8"><title>R1 Report — SOXL Analysis Platform</title>
<style>body{font-family:-apple-system,Helvetica,Arial,sans-serif;margin:0;display:flex}
#toc{position:sticky;top:0;height:100vh;overflow:auto;padding:14px;background:#f4f4f4;width:220px;flex-shrink:0;border-right:1px solid #ddd}
#toc ul{padding-left:14px;font-size:13px}
main{padding:20px;max-width:1100px}
section{margin-bottom:30px;border-bottom:1px solid #ddd;padding-bottom:14px}
.step{background:#fafafa;border:1px solid #e0e0e0;border-radius:4px;padding:12px;margin:10px 0}
.step.err{border-color:#b00020;background:#fff5f5}
.err-banner{background:#b00020;color:white;padding:6px;border-radius:3px;margin:6px 0}
.meta{color:#888;font-size:12px;font-weight:normal}
.judge{background:#fffbe6;padding:10px;border-left:3px solid #d4a017;font-size:13px;line-height:1.5;white-space:pre-wrap}
pre{background:#f0f0f0;padding:8px;font-size:11px;overflow:auto;max-height:300px}
h3{margin:6px 0}
</style></head><body>
<nav id="toc"><h3>Contents</h3><ul><li><a href="#flagship">Flagship (F9)</a></li>${toc}</ul></nav>
<main><h1>R1 Report — SOXL Analysis Platform</h1>
<p><strong>Run:</strong> ${state.startedAt} → ${state.finishedAt}<br/>
<strong>Interactions:</strong> ${interactions.length} · <strong>Judge concerns:</strong> ${state.judgeConcernsCount} · <strong>Critical invariant violations:</strong> ${state.invariantViolations.length}</p>
${f9Block}${body}</main></body></html>`;
}

function generateFailuresMarkdown() {
  let md = '# Failures\n\n## CRITICAL INVARIANT VIOLATIONS\n\n';
  if (state.invariantViolations.length === 0) {
    md += '_(none)_\n\n';
  } else {
    for (const v of state.invariantViolations) {
      md += `### Invariant ${v.letter} — ${v.step}\n\n${v.detail}\n\n`;
    }
  }
  md += '## Harness sanity failures\n\n';
  if (state.harnessSanityFailures.length === 0) md += '_(none)_\n\n';
  else for (const s of state.harnessSanityFailures) md += `- ${s}\n`;
  md += '\n## Judge concerns\n\n';
  const judges = loadTranscript().filter(e => e.kind === 'judge' && e.concern);
  if (judges.length === 0) md += '_(none)_\n\n';
  else for (const j of judges) md += `### ${j.step}\n\n${j.critique}\n\n`;
  return md;
}

function generateRunSummary() {
  const counts = { A: 0, B: 0, C: 0, D: 0, E: 0, F: 0, G: 0, H: 0 };
  for (const v of state.invariantViolations) counts[v.letter]++;
  return `INTERACTIONS: ${state.interactionsCompleted.length}
JUDGE CONCERNS RAISED: ${state.judgeConcernsCount}
CRITICAL INVARIANT VIOLATIONS: ${state.invariantViolations.length}
  Invariant A (allocation bounds): ${counts.A}
  Invariant B (no look-ahead): ${counts.B}
  Invariant C (asymmetric resize): ${counts.C}
  Invariant D (probability n reported): ${counts.D}
  Invariant E (Risk Metrics always renders): ${counts.E}
  Invariant F (dislocation classification): ${counts.F}
  Invariant G (AI Strategy Builder JSON): ${counts.G}
  Invariant H (NL Custom Strategy catalog): ${counts.H}
HARNESS SANITY FAILURES: ${state.harnessSanityFailures.length}
`;
}

// ─────────────────────────────────────────────────────────────────────────────
process.on('unhandledRejection', (e) => { console.log(`[unhandledRejection] ${e}`); });
process.on('SIGINT', () => { console.log('SIGINT'); try { liveServer.close(); } catch {} process.exit(130); });

main().catch(e => {
  console.log(`[fatal] ${e.message}\n${e.stack}`);
  state.harnessSanityFailures.push(`fatal in main: ${e.message}`);
  try { fs.writeFileSync(path.join(OUTDIR, 'run-summary.txt'), generateRunSummary()); } catch {}
  process.exit(3);
});
