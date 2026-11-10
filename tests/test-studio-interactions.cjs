const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const page = fs.readFileSync(path.join(__dirname, '../scripts/web-ui.py'), 'utf8');
const script = page.split('<script>')[1].split('</script>')[0];

function studio() {
  const elements = new Map();
  function element(id) {
    if (!elements.has(id)) {
      const classes = new Set();
      elements.set(id, {
        style: {}, dataset: {}, disabled: false, value: '0.7', checked: false,
        listeners: {}, attributes: {}, options: [], textContent: '',
        classList: { add: (...xs) => xs.forEach(x => classes.add(x)), remove: (...xs) => xs.forEach(x => classes.delete(x)),
          toggle: (x, on) => on ? classes.add(x) : classes.delete(x), contains: x => classes.has(x) },
        addEventListener(name, fn) { this.listeners[name] = fn; },
        setAttribute(name, value) { this.attributes[name] = value; },
        appendChild() {}, click() { this.clicked = true; },
        setPointerCapture(id) { this.captured = id; },
        getBoundingClientRect: () => ({ left: 10, width: 200 })
      });
    }
    return elements.get(id);
  }
  const controls = ['btn-run', 'btn-audition', 'btn-self-improve', 'file-input'].map(element);
  const zoom = ['fit', '100', '200'].map(mode => {
    const el = element('zoom-' + mode); el.dataset.zoom = mode; return el;
  });
  let requests = [], intervals = new Set(), timerId = 0;
  const context = vm.createContext({
    document: { getElementById: element, createElement: () => element('new'),
      querySelectorAll: selector => selector === '[data-zoom]' ? zoom : controls },
    window: { addEventListener() {} },
    fetch: (url, options) => {
      requests.push({url, options});
      if (url === '/api/models') return Promise.resolve({json: async () => []});
      if (url === '/api/self-improve/status') return Promise.resolve({json: async () => ({})});
      return Promise.reject(new Error('offline'));
    },
    setInterval: () => { intervals.add(++timerId); return timerId; },
    clearInterval: id => intervals.delete(id), Date, alert() {}, confirm: () => true,
    FileReader: class {}, console
  });
  vm.runInContext(script, context);
  return {element, controls, zoom, requests, intervals,
    run: code => vm.runInContext(code, context)};
}

test('touch pointer capture, keyboard split and cancellation', () => {
  const s = studio(), slider = s.element('split-slider');
  const event = {pointerId: 4, button: 0, clientX: 60, preventDefault() {}};
  slider.listeners.pointerdown(event);
  assert.equal(slider.captured, 4);
  assert.equal(slider.attributes['aria-valuenow'], '25');
  slider.listeners.pointermove({...event, clientX: 999});
  assert.equal(slider.attributes['aria-valuenow'], '100');
  slider.listeners.pointercancel(event);
  slider.listeners.pointermove({...event, clientX: 10});
  assert.equal(slider.attributes['aria-valuenow'], '100');
  slider.listeners.keydown({key: 'Home', preventDefault() {}});
  slider.listeners.keydown({key: 'ArrowRight', preventDefault() {}});
  assert.equal(slider.attributes['aria-valuenow'], '5');
});

test('dismiss preserves operation lock and elapsed feedback; completion restores controls', () => {
  const s = studio();
  s.controls[1].disabled = true;
  s.run("beginProcessing('Restoring photo'); showLoading(false)");
  assert.equal(s.element('loading').style.display, 'none');
  assert.equal(s.element('processing-status').style.display, 'block');
  assert.equal(s.element('viewport').attributes['aria-busy'], 'true');
  assert.ok(s.controls.every(x => x.disabled));
  assert.equal(s.intervals.size, 1);
  s.run("runUpscale(); runCompare(); runAudition(); runSelfImprovement(); handleFile({}); setCompareMode('dual')");
  assert.equal(s.requests.length, 2); // Startup requests only.
  s.run('finishProcessing()');
  assert.equal(s.intervals.size, 0);
  assert.equal(s.controls[0].disabled, false);
  assert.equal(s.controls[1].disabled, true);
  assert.equal(s.element('viewport').attributes['aria-busy'], 'false');
});

test('network failure clears busy state', async () => {
  const s = studio();
  s.run("currentSourceData='data:image/png;base64,AAAA'; runUpscale()");
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(s.element('processing-status').style.display, 'none');
  assert.equal(s.controls[0].disabled, false);
  assert.equal(s.intervals.size, 0);
});

test('new source clears obsolete download and quality metrics', () => {
  const s = studio();
  s.run("currentOutputBase64='old'; currentDownloadUrl='/old'; showSourcePreview('new')");
  assert.equal(s.run('currentDownloadUrl'), null);
  assert.equal(s.element('btn-download').style.display, 'none');
  assert.equal(s.element('metrics-bar').style.display, 'none');
});

test('zoom has no dependency on implicit global event; upload keyboard works', () => {
  const s = studio();
  s.run("setZoom('200')");
  assert.ok(s.zoom[2].classList.contains('active'));
  assert.ok(s.element('viewport').classList.contains('zoom-200'));
  s.element('dropzone').listeners.keydown({key: 'Enter', preventDefault() {}});
  assert.equal(s.element('file-input').clicked, true);
});
