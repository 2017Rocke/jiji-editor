// Exercise the actual packaged app through a browser, including a real PDF download.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {spawn} = require('node:child_process');
const {chromium} = require('playwright');

const executable = process.argv[2];
if (!executable || process.argv.length !== 3) {
  console.error('Usage: node scripts/verify_packaged_browser.cjs <packaged executable>');
  process.exit(2);
}

const output = path.resolve('output');
fs.mkdirSync(output, {recursive: true});
const reportPath = path.join(output, 'packaged-browser-verification.json');
const screenshotPath = path.join(output, 'packaged-browser-verification.png');
for (const artifact of [reportPath, screenshotPath]) fs.rmSync(artifact, {force: true});
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'jiji-browser-test-'));
const urlPath = path.join(temporary, 'server.url');
const pause = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
const redact = value => String(value)
  .replace(/https?:\/\/(?:127\.0\.0\.1|localhost|\[::1\])[^\s"'<>]*/gi, '[local service]')
  .replace(/token(?:=|%3D|["']?\s*:\s*["']?)[A-Za-z0-9_%-]+/gi, 'token=[redacted]');
const report = {
  passed: false, homepage: false, javascript: false, stylesheet: false,
  sample: false, batchCrop: false, unselectedPageUnchanged: false,
  batchUndo: false, pdfDownload: false, pageErrors: [], consoleErrors: [],
};
let service, serviceFailure, browserServer, browser, page, deadline;

async function verify() {
  assert(fs.existsSync(path.resolve(executable)), 'Packaged executable does not exist');
  service = spawn(path.resolve(executable), ['--no-browser', '--url-file', urlPath], {
    stdio: 'ignore', windowsHide: true,
  });
  service.on('error', error => { serviceFailure = redact(error.message); });
  const readyUntil = Date.now() + 30000;
  while (!fs.existsSync(urlPath) || fs.statSync(urlPath).size === 0) {
    assert(!serviceFailure, serviceFailure);
    assert(service.exitCode === null && service.signalCode === null,
      'Packaged application exited before starting');
    assert(Date.now() < readyUntil, 'Packaged application did not start within 30 seconds');
    await pause(100);
  }
  const url = fs.readFileSync(urlPath, 'utf8').trim();
  const address = new URL(url);
  assert(address.protocol === 'http:' && ['127.0.0.1', 'localhost', '[::1]'].includes(address.hostname),
    'Packaged application must use a loopback address');
  assert(new URLSearchParams(address.hash.slice(1)).get('token'), 'Missing local access token');

  browserServer = await chromium.launchServer({
    headless: true, timeout: 30000,
    ...(process.env.JIJI_CHROME ? {executablePath: process.env.JIJI_CHROME} : {}),
  });
  browser = await chromium.connect(browserServer.wsEndpoint(), {timeout: 15000});
  const context = await browser.newContext({viewport: {width: 1440, height: 960}, acceptDownloads: true});
  context.setDefaultTimeout(15000);
  context.setDefaultNavigationTimeout(15000);
  page = await context.newPage();
  page.on('pageerror', error => report.pageErrors.push(redact(error.message)));
  page.on('console', message => {
    if (message.type() === 'error') report.consoleErrors.push(redact(message.text()));
  });
  page.on('dialog', dialog => dialog.dismiss());
  const assets = new Map();
  page.on('response', response => {
    const pathname = new URL(response.url()).pathname;
    if (pathname === '/app.js' || pathname === '/style.css') {
      assets.set(pathname, {status: response.status(), type: response.headers()['content-type'] || ''});
    }
  });
  await page.goto(url, {waitUntil: 'networkidle'});
  await page.locator('body.is-home #welcome').waitFor({state: 'visible'});
  report.homepage = true;
  assert.equal(assets.get('/app.js')?.status, 200, 'Application script did not load');
  assert.match(assets.get('/app.js').type, /^(?:text|application)\/javascript\b/);
  assert(await page.evaluate(() => typeof state === 'object' && typeof api === 'function'),
    'Application script did not execute');
  report.javascript = true;
  assert.equal(assets.get('/style.css')?.status, 200, 'Stylesheet did not load');
  assert.match(assets.get('/style.css').type, /^text\/css\b/);
  assert(await page.evaluate(() => [...document.styleSheets].some(sheet =>
    sheet.href?.endsWith('/style.css') && sheet.cssRules.length > 0)), 'Stylesheet was not applied');
  report.stylesheet = true;

  await page.locator('#sampleBtn').click();
  await page.waitForFunction(() => state.pages.length === 3);
  await page.locator('#busy').waitFor({state: 'hidden'});
  await page.waitForFunction(() => document.querySelector('#pageImage').naturalWidth > 0);
  assert.equal(await page.locator('.thumb').count(), 3);
  report.sample = true;
  const sizes = () => page.evaluate(() => state.pages.map(item => [item.width, item.height]));
  const before = await sizes();
  await page.locator('.tool[data-tool="crop"]').click();
  await page.getByRole('checkbox', {name: '选择第 1 页', exact: true}).check();
  await page.getByRole('checkbox', {name: '选择第 2 页', exact: true}).uncheck();
  await page.getByRole('checkbox', {name: '选择第 3 页', exact: true}).check();
  await page.locator('.thumb[data-page="1"]').click();
  assert.equal(await page.locator('#selectedCount').textContent(), '选中 2 页');
  await page.locator('[data-crop="0.1"]').click();
  assert.equal(await page.locator('#applyBtn').textContent(), '裁剪选中的 2 页');
  await page.locator('#applyBtn').click();
  await page.locator('#busy').waitFor({state: 'hidden'});
  const cropped = await sizes();
  for (const index of [0, 2]) {
    for (const axis of [0, 1]) {
      assert(Math.abs(cropped[index][axis] - before[index][axis] * .8) < .11,
        `Selected page ${index + 1} was not cropped correctly`);
    }
  }
  report.batchCrop = true;
  assert.deepEqual(cropped[1], before[1], 'Unselected page was changed');
  report.unselectedPageUnchanged = true;
  await page.locator('#toast').waitFor({state: 'hidden'});
  await page.screenshot({path: screenshotPath, fullPage: true});
  await page.locator('#undoBtn').click();
  await page.locator('#busy').waitFor({state: 'hidden'});
  assert.deepEqual(await sizes(), before, 'Undo did not restore the whole crop operation');
  report.batchUndo = true;

  const downloading = page.waitForEvent('download');
  await page.locator('#exportBtn').click();
  const download = await downloading;
  const pdfPath = path.join(temporary, 'export.pdf');
  await download.saveAs(pdfPath);
  assert.equal(await download.failure(), null);
  const pdf = fs.readFileSync(pdfPath);
  assert(pdf.length > 1000 && pdf.subarray(0, 5).toString('ascii') === '%PDF-' &&
    pdf.subarray(-1024).includes(Buffer.from('%%EOF')), 'Downloaded file is not a complete PDF');
  report.pdfDownload = true;
  assert.deepEqual(report.pageErrors, [], 'Browser reported uncaught script errors');
  assert.deepEqual(report.consoleErrors, [], 'Browser reported console errors');
  report.passed = true;
}

async function stopProcess(processHandle) {
  if (!processHandle || processHandle.exitCode !== null || processHandle.signalCode !== null) return;
  processHandle.kill();
  for (let tries = 0; tries < 50 && processHandle.exitCode === null && processHandle.signalCode === null; tries++) {
    await pause(100);
  }
  if (processHandle.exitCode === null && processHandle.signalCode === null) processHandle.kill('SIGKILL');
}

(async () => {
  try {
    await Promise.race([
      verify(),
      new Promise((_, reject) => { deadline = setTimeout(() => reject(new Error('Browser verification exceeded 120 seconds')), 120000); }),
    ]);
  } catch (error) {
    report.error = redact(error.message);
    process.exitCode = 1;
  } finally {
    clearTimeout(deadline);
    if (browserServer) {
      await Promise.race([browserServer.close().catch(() => {}), pause(5000)]);
      await stopProcess(browserServer.process());
    }
    await stopProcess(service);
    fs.rmSync(temporary, {recursive: true, force: true});
    fs.writeFileSync(reportPath, JSON.stringify(report, null, 2) + '\n');
    console.log(JSON.stringify(report));
  }
})().catch(error => {
  console.error(redact(error.message));
  process.exitCode = 1;
});
