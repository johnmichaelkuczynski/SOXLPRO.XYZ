// Fresh-process benchmark on an isolated port, without stopping the live preview.
const {spawn} = require('node:child_process');
const fs = require('node:fs');
const {chromium} = require('playwright');
const {performance} = require('node:perf_hooks');

(async () => {
  const port = Number(process.env.PROBE_PORT || 5001);
  const browser = await chromium.launch({
    executablePath: '/repl/tools/bin/chromium', headless: true, args: ['--no-sandbox']
  });
  const page = await browser.newPage();
  const began = performance.now();
  const child = spawn('python', ['-c',
    `from pathlib import Path\np=Path('seo_server.py').resolve()\ns=p.read_text().replace('"server.port": 5000', '"server.port": ${port}').replace('serve(port=5000)', 'serve(port=${port})')\nexec(compile(s,str(p),'exec'),{'__name__':'__main__','__file__':str(p)})`
  ], {env: {...process.env}});
  const log = fs.createWriteStream('/tmp/soxl-cold-start-probe.log');
  child.stdout.pipe(log); child.stderr.pipe(log);
  const result = {label: process.argv[2] || 'probe', environment: 'fresh workspace process; existing provider disk caches retained'};
  const elapsed = () => (performance.now() - began) / 1000;
  try {
    while (true) {
      try {
        const health = await fetch(`http://127.0.0.1:${port}/_stcore/health`);
        if (health.ok) break;
      } catch {}
      if (child.exitCode !== null || elapsed() > 120) throw Error('Server failed to bind');
      await new Promise(r => setTimeout(r, 25));
    }
    result.port_and_health_seconds = elapsed();
    await page.goto(`http://127.0.0.1:${port}/`, {waitUntil:'domcontentloaded'});
    result.html_seconds = elapsed();
    await page.getByText('SOXL Market Snapshot', {exact:true}).waitFor({timeout:120000});
    result.snapshot_seconds = elapsed();
    await page.getByText('SOXL Daily Signal', {exact:true}).waitFor({timeout:120000});
    result.signals_seconds = elapsed();
    result.page_errors = await page.locator('[data-testid="stException"]').allTextContents();
    console.log(JSON.stringify(result, null, 2));
  } finally {
    child.kill('SIGTERM');
    await browser.close();
  }
})().catch(e => {console.error(e); process.exit(1);});
