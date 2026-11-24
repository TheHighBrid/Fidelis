/* Display and review-interaction helpers. These do not modify mask values,
   blend weights, crop bytes or saved revisions. */
((root) => {
  const CHANNELS = ['skin', 'hair', 'fabric', 'protected'];
  const COLORS = {
    skin: [239, 90, 90],
    hair: [241, 196, 80],
    fabric: [91, 202, 132],
    protected: [92, 145, 255],
  };

  function clampStrength(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return 0.6;
    return Math.min(1, Math.max(0, number));
  }

  function normalizeVisibility(input) {
    const visibility = {};
    for (const name of CHANNELS) visibility[name] = input?.[name] !== false;
    return visibility;
  }

  function toggleVisibility(current, name) {
    if (!CHANNELS.includes(name)) throw new Error('Unknown mask channel');
    const visibility = normalizeVisibility(current);
    visibility[name] = !visibility[name];
    return visibility;
  }

  function soloVisibility(current, name) {
    if (!CHANNELS.includes(name)) throw new Error('Unknown mask channel');
    const visibility = normalizeVisibility(current);
    const alreadySolo = CHANNELS.every((key) => (key === name ? visibility[key] : !visibility[key]));
    const next = {};
    for (const key of CHANNELS) next[key] = alreadySolo ? true : key === name;
    return next;
  }

  function compositeOverlay(layers, width, height, options = {}) {
    if (!Number.isSafeInteger(width) || !Number.isSafeInteger(height) || width < 1 || height < 1) {
      throw new Error('Overlay size must be a positive integer.');
    }
    const count = width * height;
    const strength = clampStrength(options.strength === undefined ? 0.6 : options.strength);
    const visible = normalizeVisibility(options.visible);
    const rgba = new Uint8ClampedArray(count * 4);
    for (let i = 0; i < count; i++) {
      let r = 0;
      let g = 0;
      let b = 0;
      let a = 0;
      for (const name of CHANNELS) {
        if (!visible[name]) continue;
        const source = layers?.[name];
        const value = source && i < source.length ? source[i] : 0;
        if (!(value > 0)) continue;
        let gain = strength;
        if (name === 'protected') {
          const x = i % width;
          const y = Math.floor(i / width);
          gain = Math.min(1, strength * ((x + y) % 8 < 2 ? 1.5 : 0.75));
        }
        const alpha = Math.min(1, value * gain);
        const color = COLORS[name];
        r = r * (1 - alpha) + color[0] * alpha;
        g = g * (1 - alpha) + color[1] * alpha;
        b = b * (1 - alpha) + color[2] * alpha;
        a += (1 - a) * alpha;
      }
      if (a) {
        rgba[i * 4] = r / a;
        rgba[i * 4 + 1] = g / a;
        rgba[i * 4 + 2] = b / a;
        rgba[i * 4 + 3] = a * 255;
      }
    }
    return rgba;
  }

  function nudgeCenter(dimensions, center, key, step) {
    const deltas = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
    const delta = deltas[key];
    const [width, height] = dimensions;
    const [x, y] = center;
    const distance = step === undefined ? 1 : step;
    if (!delta || ![width, height, x, y, distance].every(Number.isSafeInteger) || width < 1 || height < 1 || distance < 1 || x < 0 || y < 0 || x >= width || y >= height) {
      throw new Error('Crop nudge needs an in-image integer centre and a positive step.');
    }
    return [
      Math.max(0, Math.min(width - 1, x + delta[0] * distance)),
      Math.max(0, Math.min(height - 1, y + delta[1] * distance)),
    ];
  }

  function nudgeStep(side, coarse) {
    const size = Number(side);
    if (!Number.isSafeInteger(size) || size < 1) throw new Error('Crop side must be a positive integer.');
    return coarse ? Math.max(8, Math.floor(size / 4)) : 1;
  }

  function clampBrushDiameter(value, delta = 0) {
    const base = Number(value);
    const step = Number(delta);
    const start = Number.isFinite(base) ? base : 48;
    const move = Number.isFinite(step) ? step : 0;
    return Math.max(4, Math.min(200, Math.round(start + move)));
  }

  function layoutMode(width) {
    const size = Number(width);
    if (!Number.isFinite(size) || size <= 0) throw new Error('Viewport width must be positive.');
    if (size <= 780) return 'stack';
    if (size < 1100) return 'tablet';
    return 'desk';
  }

  function inspectorPlacement(width, docked, open) {
    if (!open) return 'closed';
    if (!docked) return 'below';
    return layoutMode(width) === 'desk' ? 'side' : 'sheet';
  }

  /* Source order of the rail, then the review stage. Narrow CSS pulls the stage
     and paint section ahead of import without moving wide-layout columns. */
  const NARROW_SOURCE = ['savedWork', 'importPasses', 'paintRegions', 'suggestions', 'generation', 'balance', 'main'];
  const NARROW_CSS_ORDER = { main: -2, paintRegions: -1 };

  function stackReadingOrder(sourceOrder = NARROW_SOURCE, cssOrder = NARROW_CSS_ORDER) {
    return sourceOrder
      .map((id, index) => ({ id, index, order: Object.hasOwn(cssOrder, id) ? cssOrder[id] : 0 }))
      .sort((a, b) => a.order - b.order || a.index - b.index)
      .map((item) => item.id);
  }

  function narrowReadingOrder() {
    return stackReadingOrder();
  }

  function isTextField(state) {
    if (state.editable) return true;
    const tag = String(state.targetTag || '').toUpperCase();
    const type = String(state.targetType || 'text').toLowerCase();
    return tag === 'TEXTAREA' || (tag === 'INPUT' && /^(text|search|url|tel|email|password|number)$/.test(type));
  }

  function isControl(state) {
    const tag = String(state.targetTag || '').toUpperCase();
    return tag === 'SELECT' || tag === 'BUTTON' || tag === 'A' || tag === 'INPUT' || tag === 'TEXTAREA';
  }

  function keyboardAction(state) {
    const key = String(state.key || '');
    if (state.ctrl || state.meta) {
      if (!state.alt && key.toLowerCase() === 'z' && !isTextField(state)) return { type: 'history', redo: !!state.shift };
      return null;
    }
    if (isTextField(state) || isControl(state)) return null;
    if (key === 'ArrowLeft' || key === 'ArrowRight' || key === 'ArrowUp' || key === 'ArrowDown') {
      if (state.panelOpen && state.paintMode === 'off' && !state.alt) return { type: 'nudge', key, coarse: !!state.shift };
      return null;
    }
    if (state.alt) return null;
    const tools = { v: 'off', b: 'paint', e: 'erase' };
    const tool = tools[key.toLowerCase()];
    if (tool && key.length === 1) return { type: 'tool', mode: tool };
    const layers = { 1: 'protected', 2: 'skin', 3: 'hair', 4: 'fabric' };
    if (layers[key]) return { type: 'layer', layer: layers[key] };
    if (key === '[' || key === ']') return { type: 'brush', delta: key === '[' ? -4 : 4 };
    if (key === '\\') return { type: 'overlay' };
    return null;
  }

  function cropPixel(rect, scale, localX, localY) {
    if (![1, 2].includes(scale)) throw new Error('Native scale must be 100% or 200%.');
    if (!rect || ![rect.x, rect.y, rect.width, rect.height].every(Number.isSafeInteger) || rect.width < 1 || rect.height < 1) {
      throw new Error('Crop is not loaded.');
    }
    const x = Number(localX);
    const y = Number(localY);
    if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
    if (x < 0 || y < 0 || x >= rect.width * scale || y >= rect.height * scale) return null;
    const localPixelX = Math.min(rect.width - 1, Math.floor(x / scale));
    const localPixelY = Math.min(rect.height - 1, Math.floor(y / scale));
    return { imageX: rect.x + localPixelX, imageY: rect.y + localPixelY, localX: localPixelX, localY: localPixelY };
  }

  function rgbaAt(imageData, x, y) {
    if (!imageData?.data || !Number.isSafeInteger(imageData.width) || !Number.isSafeInteger(imageData.height) || !Number.isSafeInteger(x) || !Number.isSafeInteger(y)) return null;
    if (x < 0 || y < 0 || x >= imageData.width || y >= imageData.height) return null;
    const index = (y * imageData.width + x) * 4;
    const data = imageData.data;
    return [data[index], data[index + 1], data[index + 2], data[index + 3]];
  }

  function channelText(pixel) {
    return pixel ? `${pixel[0]} ${pixel[1]} ${pixel[2]}` : 'unreadable';
  }

  function formatPixelReadout(sample) {
    return `Native crop pixel x ${sample.imageX}, y ${sample.imageY} · base RGB ${channelText(sample.base)} · ${sample.resultLabel} RGB ${channelText(sample.result)}. Browser-decoded from the loaded crop, not preview zoom.`;
  }

  function centreReadout(rect, base, result, resultLabel) {
    const hit = cropPixel(rect, 1, Math.floor((rect.width - 1) / 2), Math.floor((rect.height - 1) / 2));
    return formatPixelReadout({
      imageX: hit.imageX,
      imageY: hit.imageY,
      base: rgbaAt(base, hit.localX, hit.localY),
      result: rgbaAt(result, hit.localX, hit.localY),
      resultLabel: resultLabel || 'result',
    });
  }

  function describePointer(input) {
    const hit = cropPixel(input.rect, input.scale, input.localX, input.localY);
    if (!hit) return null;
    return formatPixelReadout({
      imageX: hit.imageX,
      imageY: hit.imageY,
      base: rgbaAt(input.base, hit.localX, hit.localY),
      result: rgbaAt(input.result, hit.localX, hit.localY),
      resultLabel: input.resultLabel,
    });
  }

  function jobContext(job, dirty) {
    if (!job) return 'No saved job open';
    const revision = Number.isSafeInteger(job.revision) ? String(job.revision) : '?';
    const dimensions = Array.isArray(job.dimensions) ? job.dimensions.join(' × ') : '?';
    return `${job.label || 'Untitled'} · revision ${revision} · ${dimensions} px${dirty ? ' · unsaved edits' : ''}`;
  }

  const NATIVE_SIDES = [16, 32, 64, 128, 256, 512];

  function proposalCenterAndSide(rectangle) {
    if (!Array.isArray(rectangle) || rectangle.length !== 4 || !rectangle.every(Number.isSafeInteger)) {
      throw new Error('Proposed ROI must be an integer [x, y, width, height] rectangle.');
    }
    const [x, y, width, height] = rectangle;
    if (x < 0 || y < 0 || width < 1 || height < 1) {
      throw new Error('Proposed ROI coordinates must be non-negative with positive size.');
    }
    const maxDim = Math.max(width, height);
    const side = NATIVE_SIDES.find((candidate) => candidate >= maxDim) || 512;
    return {
      centerX: x + Math.floor(width / 2),
      centerY: y + Math.floor(height / 2),
      side,
    };
  }

  function formatProposalSummary(proposal, index = 0) {
    if (!proposal || !Array.isArray(proposal.rectangle) || proposal.rectangle.length !== 4) {
      throw new Error('Proposal record must include a rectangle.');
    }
    const [x, y, width, height] = proposal.rectangle;
    if (![x, y, width, height].every(Number.isSafeInteger) || x < 0 || y < 0 || width < 1 || height < 1) {
      throw new Error('Proposal rectangle must contain valid pixel bounds.');
    }
    const parts = [
      `#${Number.isSafeInteger(index) && index >= 0 ? index + 1 : 1}`,
      `x ${x}–${x + width - 1}, y ${y}–${y + height - 1} (${width} × ${height} px)`,
    ];
    if (Number.isSafeInteger(proposal.strong_edges)) {
      parts.push(`${proposal.strong_edges.toLocaleString()} edges`);
    }
    if (Number.isSafeInteger(proposal.changed_pixels) && Number.isSafeInteger(proposal.strong_edge_disagreements)) {
      parts.push(`${proposal.changed_pixels.toLocaleString()} changed px · ${proposal.strong_edge_disagreements.toLocaleString()} edge diffs`);
    }
    return parts.join(' · ');
  }

  const api = {
    CHANNELS,
    COLORS,
    clampStrength,
    normalizeVisibility,
    toggleVisibility,
    soloVisibility,
    compositeOverlay,
    nudgeCenter,
    nudgeStep,
    clampBrushDiameter,
    layoutMode,
    inspectorPlacement,
    stackReadingOrder,
    narrowReadingOrder,
    keyboardAction,
    cropPixel,
    rgbaAt,
    formatPixelReadout,
    centreReadout,
    describePointer,
    jobContext,
    proposalCenterAndSide,
    formatProposalSummary,
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.FidelisReview = api;
})(typeof window === 'undefined' ? this : window);
