// Pure review-UI contracts. This does not render a browser or accept a device.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const review = require('../fidelis/studio/review-ui.js');

function layers(width, height, fill = {}) {
  const count = width * height;
  const fields = {};
  for (const name of review.CHANNELS) fields[name] = new Float32Array(count);
  for (const [name, value] of Object.entries(fill)) fields[name].fill(value);
  return fields;
}

const skin = layers(1, 1, { skin: 1 });
const before = Float32Array.from(skin.skin);
const painted = review.compositeOverlay(skin, 1, 1, { strength: 0.6 });
assert.deepEqual(Array.from(skin.skin), Array.from(before));
assert.deepEqual([painted[0], painted[1], painted[2], painted[3]], [239, 90, 90, 153]);

const hidden = review.compositeOverlay(skin, 1, 1, { strength: 0.6, visible: { skin: false } });
assert.equal(hidden[3], 0);

const protect = layers(8, 1, { protected: 1 });
const hatch = review.compositeOverlay(protect, 8, 1, { strength: 0.6 });
assert.deepEqual([hatch[0], hatch[1], hatch[2]], [92, 145, 255]);
assert.deepEqual([hatch[8], hatch[9], hatch[10]], [92, 145, 255]);
assert.ok(hatch[3] > hatch[11], 'protection stripes stay darker than the gaps');
assert.ok(hatch[3] < 255 && hatch[11] > 0);

const both = layers(1, 1, { skin: 1, protected: 1 });
const stacked = review.compositeOverlay(both, 1, 1, { strength: 0.6 });
assert.notDeepEqual([stacked[0], stacked[1], stacked[2]], [239, 90, 90]);
assert.throws(() => review.compositeOverlay(skin, 0, 1));

const visibility = { protected: true, skin: true, hair: false, fabric: true };
const toggled = review.toggleVisibility(visibility, 'skin');
assert.equal(visibility.skin, true);
assert.equal(toggled.skin, false);
assert.equal(toggled.hair, false);
const solo = review.soloVisibility(toggled, 'hair');
assert.deepEqual(solo, { skin: false, hair: true, fabric: false, protected: false });
assert.deepEqual(review.soloVisibility(solo, 'hair'), { skin: true, hair: true, fabric: true, protected: true });
assert.throws(() => review.toggleVisibility(visibility, 'logo'));

assert.deepEqual(review.nudgeCenter([12, 8], [0, 4], 'ArrowLeft', 3), [0, 4]);
assert.deepEqual(review.nudgeCenter([12, 8], [11, 7], 'ArrowRight', 4), [11, 7]);
assert.deepEqual(review.nudgeCenter([8001, 6003], [4000, 3000], 'ArrowUp', 1), [4000, 2999]);
assert.equal(review.nudgeStep(256, false), 1);
assert.equal(review.nudgeStep(256, true), 64);
assert.equal(review.nudgeStep(16, true), 8);
assert.throws(() => review.nudgeCenter([12, 8], [1.5, 0], 'ArrowRight', 1));
assert.equal(review.clampBrushDiameter(48, 4), 52);
assert.equal(review.clampBrushDiameter(3, -8), 4);
assert.equal(review.clampBrushDiameter(199, 8), 200);

assert.equal(review.layoutMode(780), 'stack');
assert.equal(review.layoutMode(781), 'tablet');
assert.equal(review.layoutMode(1099), 'tablet');
assert.equal(review.layoutMode(1100), 'desk');
assert.equal(review.inspectorPlacement(1440, true, true), 'side');
assert.equal(review.inspectorPlacement(900, true, true), 'sheet');
assert.equal(review.inspectorPlacement(1440, false, true), 'below');
assert.equal(review.inspectorPlacement(1440, true, false), 'closed');

const baseKeys = { ctrl: false, meta: false, alt: false, shift: false, editable: false, targetTag: 'DIV', targetType: '', paintMode: 'off', panelOpen: true };
assert.deepEqual(review.keyboardAction({ ...baseKeys, key: 'ArrowRight' }), { type: 'nudge', key: 'ArrowRight', coarse: false });
assert.deepEqual(review.keyboardAction({ ...baseKeys, key: 'ArrowUp', shift: true }), { type: 'nudge', key: 'ArrowUp', coarse: true });
assert.equal(review.keyboardAction({ ...baseKeys, key: 'ArrowRight', paintMode: 'paint' }), null);
assert.equal(review.keyboardAction({ ...baseKeys, key: 'ArrowRight', panelOpen: false }), null);
assert.equal(review.keyboardAction({ ...baseKeys, key: 'ArrowRight', targetTag: 'SELECT' }), null);
assert.equal(review.keyboardAction({ ...baseKeys, key: 'ArrowRight', targetTag: 'INPUT', targetType: 'number' }), null);
assert.deepEqual(review.keyboardAction({ ...baseKeys, key: 'z', ctrl: true, targetTag: 'SELECT' }), { type: 'history', redo: false });
assert.deepEqual(review.keyboardAction({ ...baseKeys, key: 'Z', ctrl: true, shift: true, targetTag: 'INPUT', targetType: 'range' }), { type: 'history', redo: true });
assert.equal(review.keyboardAction({ ...baseKeys, key: 'z', ctrl: true, targetTag: 'INPUT', targetType: 'number' }), null);
assert.deepEqual(review.keyboardAction({ ...baseKeys, key: 'b' }), { type: 'tool', mode: 'paint' });
assert.deepEqual(review.keyboardAction({ ...baseKeys, key: '1' }), { type: 'layer', layer: 'protected' });
assert.deepEqual(review.keyboardAction({ ...baseKeys, key: '4' }), { type: 'layer', layer: 'fabric' });
assert.deepEqual(review.keyboardAction({ ...baseKeys, key: ']' }), { type: 'brush', delta: 4 });
assert.deepEqual(review.keyboardAction({ ...baseKeys, key: '\\' }), { type: 'overlay' });
assert.equal(review.keyboardAction({ ...baseKeys, key: 'b', targetTag: 'BUTTON' }), null);

const rect = { x: 10, y: 20, width: 4, height: 2 };
assert.deepEqual(review.cropPixel(rect, 2, 3, 1), { imageX: 11, imageY: 20, localX: 1, localY: 0 });
assert.equal(review.cropPixel(rect, 2, 8, 0), null);
const image = { width: 4, height: 2, data: new Uint8ClampedArray(32) };
image.data.set([9, 8, 7, 255], 4);
assert.deepEqual(review.rgbaAt(image, 1, 0), [9, 8, 7, 255]);
const readout = review.describePointer({ rect, scale: 2, localX: 3, localY: 1, base: image, result: image, resultLabel: 'saved final' });
assert.match(readout, /Native crop pixel x 11, y 20/);
assert.match(readout, /base RGB 9 8 7/);
assert.match(readout, /saved final RGB 9 8 7/);
assert.match(readout, /not preview zoom/);
assert.match(review.centreReadout(rect, null, null, 'raw candidate'), /unreadable/);
assert.match(review.centreReadout(rect, null, null, 'raw candidate'), /not preview zoom/);

assert.equal(review.jobContext(null, true), 'No saved job open');
assert.equal(review.jobContext({ label: 'Coat', revision: 4, dimensions: [12, 8] }, true), 'Coat · revision 4 · 12 × 8 px · unsaved edits');

const html = fs.readFileSync(require('node:path').join(__dirname, '../fidelis/studio/studio.html'), 'utf8');
assert.match(html, /\/api\/regions\/review-ui\.js/);
assert.match(html, /id="channelProtected"/);
assert.match(html, /id="overlayOpacity"/);
assert.match(html, /id="dockNative"/);
assert.match(html, /id="jobChip"/);
assert.match(html, /id="readNativePixel"/);
assert.match(html, /Preview zoom scales the reduced overview\. It is not native pixel inspection\./);
assert.match(html, /min-width:781px\) and \(max-width:1099px\)/);
assert.match(html, /data-inspector="side"/);

console.log('Review UI helper contracts passed: overlay, nudge, layout, keys, readout and markup.');
