#!/usr/bin/env node
import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const suites = [
  { id: 'structure', command: '.venv/bin/python', args: ['scripts/check-project.py'], browser_required: false },
  { id: 'python', command: '.venv/bin/python', args: ['-m', 'unittest', 'discover', '-s', 'tests', '-v'], browser_required: false },
  { id: 'model', command: process.execPath, args: ['--test', 'tests/map-model.test.mjs'], browser_required: false },
  { id: 'map', command: process.execPath, args: ['scripts/verify-map.mjs'], browser_required: true },
  { id: 'wheel', command: process.execPath, args: ['scripts/verify-wheel.mjs'], browser_required: true },
  { id: 'refresh', command: process.execPath, args: ['scripts/verify-auto-sync.mjs'], browser_required: true },
];
let selection = 'all', output, doctorOnly = false;
for (let index = 2; index < process.argv.length; index++) {
  const argument = process.argv[index];
  if (argument === '--doctor') doctorOnly = true;
  else if (argument === '--suite' && process.argv[index + 1]) selection = process.argv[++index];
  else if (argument === '--output' && process.argv[index + 1]) output = path.resolve(process.argv[++index]);
  else if (argument === '--help') {
    console.log('node scripts/verify.mjs [--doctor] [--suite all|smoke|structure|python|model|map|wheel|refresh] [--output DIRECTORY]');
    process.exit(0);
  } else throw new Error(`Unknown or incomplete option: ${argument}`);
}
const selected = selection === 'all' ? suites : suites.filter(suite => selection === 'smoke' ? ['structure', 'refresh'].includes(suite.id) : suite.id === selection);
if (!selected.length) throw new Error(`Unknown suite: ${selection}`);
async function doctor(checkBrowser) {
  const python = spawnSync(path.join(root, '.venv/bin/python'), ['-c', 'import sys, cryptography, PIL; print(sys.version.split()[0])'], { cwd: root, encoding: 'utf8', timeout: 10000 });
  const checks = [{ id: 'python-dependencies', passed: python.status === 0, detail: python.status === 0 ? python.stdout.trim() : 'Run ./scripts/setup.sh to install the locked Python dependencies.' }];
  checks.push({ id: 'node', passed: Number(process.versions.node.split('.')[0]) >= 18, detail: process.version });
  if (!checkBrowser) return { passed: checks.every(check => check.passed), checks };
  try {
    const { chromium } = await import('playwright');
    const channel = process.env.PLAYWRIGHT_CHANNEL || 'chrome';
    if (!['chrome', 'chromium'].includes(channel)) throw new Error('Unsupported browser channel');
    const chrome = process.platform === 'darwin' ? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' : process.platform === 'win32' ? path.join(process.env.PROGRAMFILES || 'C:\\Program Files', 'Google/Chrome/Application/chrome.exe') : '/opt/google/chrome/chrome';
    const executable = channel === 'chromium' ? chromium.executablePath() : chrome;
    checks.push({ id: 'playwright', passed: true, detail: 'Dependency loaded from this checkout.' });
    await fs.access(executable, fs.constants.X_OK);
    checks.push({ id: 'browser', passed: true, detail: `${channel}: ${executable}` });
  } catch {
    checks.push({ id: 'browser', passed: false, detail: 'Run npm ci; install Chrome locally, or npx playwright install chromium with PLAYWRIGHT_CHANNEL=chromium.' });
  }
  return { passed: checks.every(check => check.passed), checks };
}
const readiness = await doctor(doctorOnly || selected.some(suite => suite.browser_required));
if (doctorOnly) { console.log(JSON.stringify(readiness, null, 2)); process.exit(readiness.passed ? 0 : 1); }
output ||= path.join(root, 'work/verification', `${new Date().toISOString().replace(/[:.]/g, '-')}-${process.pid}`);
await fs.mkdir(output, { recursive: true });
const report = { started_at: new Date().toISOString(), source: 'synthetic-local-verification', selection, doctor: readiness, evidence_directory: output, suites: [], passed: false };
await fs.writeFile(path.join(output, 'report.json'), JSON.stringify(report, null, 2) + '\n');
if (!readiness.passed) {
  console.error(`Verification environment is not ready. Evidence: ${path.join(output, 'report.json')}`);
  process.exit(1);
}
let active;
let interrupted;
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => { interrupted = signal; stopActive(); });
function stopActive(signal = 'SIGTERM') {
  if (active && active.exitCode === null && active.signalCode === null) {
    try { process.kill(process.platform === 'win32' ? active.pid : -active.pid, signal); } catch (error) { if (error.code !== 'ESRCH') throw error; }
  }
}
for (const suite of selected) {
  const directory = path.join(output, suite.id);
  await fs.mkdir(directory, { recursive: true });
  const logPath = path.join(directory, 'output.log');
  console.log(`Verifying ${suite.id}…`);
  const started = Date.now();
  let timedOut = false;
  const result = await new Promise(resolve => {
    active = spawn(suite.command, suite.args, { cwd: root, detached: process.platform !== 'win32', env: { ...process.env, VERIFICATION_OUTPUT: directory, MAP_SCREENSHOTS: directory } });
    const logs = [], stdout = [], stderr = [];
    let error;
    active.stdout.on('data', chunk => { logs.push(chunk); stdout.push(chunk); });
    active.stderr.on('data', chunk => { logs.push(chunk); stderr.push(chunk); });
    active.on('error', value => { error = value.message; });
    let killTimer;
    const timeout = setTimeout(() => { timedOut = true; stopActive(); killTimer = setTimeout(() => stopActive('SIGKILL'), 5000); }, 180000);
    active.on('close', async (code, signal) => {
      clearTimeout(timeout); clearTimeout(killTimer);
      if (error) { const detail = Buffer.from(error + '\n'); logs.push(detail); stderr.push(detail); }
      await fs.writeFile(logPath, Buffer.concat(logs));
      const stdoutLog = path.join(directory, 'stdout.log'), stderrLog = path.join(directory, 'stderr.log');
      await fs.writeFile(stdoutLog, Buffer.concat(stdout));
      await fs.writeFile(stderrLog, Buffer.concat(stderr));
      resolve({ ...suite, exit_code: code, signal, timed_out: timedOut, error, duration_ms: Date.now() - started, log: logPath, stdout_log: stdoutLog, stderr_log: stderrLog, evidence_directory: directory, passed: code === 0 && !timedOut && !error });
    });
  });
  report.suites.push(result);
  report.passed = report.suites.every(suite => suite.passed);
  report.finished_at = new Date().toISOString();
  await fs.writeFile(path.join(output, 'report.json'), JSON.stringify(report, null, 2) + '\n');
  console.log(`${suite.id}: ${result.passed ? 'PASS' : 'FAIL'} (${result.duration_ms} ms); ${logPath}`);
  if (interrupted) break;
}
console.log(`Evidence: ${path.join(output, 'report.json')}`);
process.exitCode = report.passed && !interrupted ? 0 : 1;
