#!/usr/bin/env python3
"""Interactive Drag-and-Drop Local Web UI for Fidelis photographic restoration.

Zero external web dependencies (uses Python standard library http.server).
Features:
- Drag-and-drop image upload
- Quick load of canonical test crops (Portrait, Fabric, Product)
- Single-model upscale or multi-model auditioning
- Interactive before/after split comparison slider
- 100% / 200% native pixel zoom inspection
- Real-time objective fidelity metrics (PSNR, SSIM, Color Drift, BG Restraint)
"""

import argparse
import base64
import html
import http.server
import io
import json
import os
from pathlib import Path
import shutil
import socketserver
import subprocess
import sys
import tempfile
import time
from urllib.parse import parse_qs, urlparse
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent

# Import metric evaluator and drift detector if available
try:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import importlib.util
    spec = importlib.util.spec_from_file_location("eval_metrics", str(REPO_ROOT / "scripts/evaluate-fidelity-metrics.py"))
    eval_metrics = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(eval_metrics)
    HAS_METRICS = True
except Exception:
    HAS_METRICS = False

try:
    spec_drift = importlib.util.spec_from_file_location("detect_drift", str(REPO_ROOT / "scripts/detect-drift.py"))
    detect_drift = importlib.util.module_from_spec(spec_drift)
    spec_drift.loader.exec_module(detect_drift)
    HAS_DRIFT = True
except Exception:
    HAS_DRIFT = False

def get_installed_models():
    cli = shutil.which("fidelis") or str(REPO_ROOT / "bin/fidelis")
    try:
        out = subprocess.check_output([cli, "models"], text=True)
        models = [m.strip() for m in out.strip().splitlines() if m.strip()]
        return models if models else ["RealeSR-general-v3", "DF2K"]
    except Exception:
        return ["RealeSR-general-v3", "DF2K"]

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Fidelis Studio - Photographic Restoration</title>
<style>
  :root {
    --bg: #0d1117;
    --card: #161b22;
    --card-alt: #21262d;
    --text: #c9d1d9;
    --text-bright: #f0f6fc;
    --text-muted: #8b949e;
    --accent: #58a6ff;
    --success: #3fb950;
    --border: #30363d;
  }
  * { box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    background: var(--bg);
    color: var(--text);
    margin: 0;
    padding: 20px;
    display: flex;
    flex-direction: column;
    min-height: 100vh;
  }
  .header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid var(--border);
    padding-bottom: 16px;
    margin-bottom: 20px;
  }
  .header h1 { margin: 0; font-size: 22px; color: var(--text-bright); }
  .badge {
    background: #238636;
    color: #fff;
    padding: 4px 10px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 600;
  }
  .workspace {
    display: grid;
    grid-template-columns: 320px 1fr;
    gap: 20px;
    flex: 1;
  }
  @media (max-width: 900px) {
    .workspace { grid-template-columns: 1fr; }
  }
  .sidebar {
    display: flex;
    flex-direction: column;
    gap: 16px;
  }
  .panel {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
  }
  .panel h3 { margin-top: 0; margin-bottom: 12px; font-size: 14px; text-transform: uppercase; color: var(--text-muted); }
  .dropzone {
    border: 2px dashed var(--border);
    border-radius: 8px;
    padding: 24px;
    text-align: center;
    cursor: pointer;
    background: var(--card-alt);
    transition: border-color 0.2s, background 0.2s;
  }
  .dropzone:hover, .dropzone.dragover {
    border-color: var(--accent);
    background: rgba(88, 166, 255, 0.05);
  }
  .dropzone p { margin: 6px 0; font-size: 13px; color: var(--text-muted); }
  .sample-btns { display: flex; flex-direction: column; gap: 6px; margin-top: 10px; }
  .btn {
    background: var(--card-alt);
    color: var(--text);
    border: 1px solid var(--border);
    padding: 8px 14px;
    border-radius: 6px;
    cursor: pointer;
    font-size: 13px;
    font-weight: 500;
    transition: all 0.15s;
    text-align: left;
  }
  .btn:hover { background: #30363d; color: var(--text-bright); }
  .btn-primary {
    background: #238636;
    color: #fff;
    border-color: rgba(240,246,252,0.1);
    font-weight: 600;
    text-align: center;
    padding: 10px;
  }
  .btn-primary:hover { background: #2ea043; }
  .btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
  select, input[type="number"] {
    width: 100%;
    background: var(--card-alt);
    border: 1px solid var(--border);
    color: var(--text-bright);
    padding: 8px 10px;
    border-radius: 6px;
    font-size: 13px;
    margin-bottom: 10px;
  }
  .viewer-panel {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 8px;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  .viewer-toolbar {
    padding: 10px 16px;
    border-bottom: 1px solid var(--border);
    display: flex;
    justify-content: space-between;
    align-items: center;
    background: #161b22;
  }
  .tool-btn {
    background: var(--card-alt);
    border: 1px solid var(--border);
    color: var(--text);
    padding: 4px 10px;
    border-radius: 4px;
    font-size: 12px;
    cursor: pointer;
  }
  .tool-btn.active { background: var(--accent); color: #fff; border-color: var(--accent); }
  .viewport {
    flex: 1;
    min-height: 480px;
    background: #05070a;
    display: flex;
    align-items: center;
    justify-content: center;
    position: relative;
    overflow: auto;
  }
  .split-container {
    position: relative;
    display: inline-block;
    max-width: 100%;
    max-height: 100%;
    user-select: none;
  }
  .split-container img {
    display: block;
    max-width: 100%;
    height: auto;
  }
  .zoom-100 .split-container img { max-width: none; transform: scale(1.0); }
  .zoom-200 .split-container img { max-width: none; transform: scale(2.0); image-rendering: pixelated; }
  .split-before {
    position: absolute;
    top: 0;
    left: 0;
    height: 100%;
    overflow: hidden;
    border-right: 2px solid var(--accent);
  }
  .split-slider {
    position: absolute;
    top: 0;
    bottom: 0;
    width: 4px;
    background: var(--accent);
    cursor: ew-resize;
  }
  .split-handle {
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    width: 28px;
    height: 28px;
    background: var(--accent);
    color: #fff;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 10px;
    box-shadow: 0 0 8px rgba(0,0,0,0.5);
  }
  .metrics-box {
    padding: 12px 16px;
    border-top: 1px solid var(--border);
    background: #161b22;
    display: flex;
    gap: 16px;
    flex-wrap: wrap;
    font-size: 12px;
  }
  .metric-item {
    font-family: ui-monospace, monospace;
    background: var(--card-alt);
    padding: 4px 10px;
    border-radius: 4px;
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
  .status-pill {
    padding: 2px 8px;
    border-radius: 10px;
    font-size: 11px;
    font-weight: 600;
  }
  .status-pass { background: #238636; color: #fff; }
  .status-warn { background: #d29922; color: #000; }
  .status-fail { background: #da3633; color: #fff; }
  .loading-overlay {
    position: absolute;
    top:0; left:0; right:0; bottom:0;
    background: rgba(13, 17, 23, 0.8);
    display: none;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    z-index: 100;
  }
  .spinner {
    width: 36px;
    height: 36px;
    border: 3px solid rgba(88, 166, 255, 0.2);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
</style>
</head>
<body>

<div class="header">
  <div>
    <h1>Fidelis Photographic Restoration Studio</h1>
    <div style="color: var(--text-muted); font-size: 13px;">Native NCNN & Vulkan inference with interactive split comparison</div>
  </div>
  <div class="badge">Local Engine Active</div>
</div>

<div class="workspace">
  <div class="sidebar">
    <div class="panel">
      <h3>1. Select Source Photo</h3>
      <div class="dropzone" id="dropzone" onclick="document.getElementById('file-input').click()">
        <strong>Click or drop photo here</strong>
        <p>JPG, PNG, WebP (high or low-res)</p>
      </div>
      <input type="file" id="file-input" style="display:none;" accept="image/*">
      
      <div style="margin-top: 12px; font-size: 12px; color: var(--text-muted);">Or load standard evaluation crop:</div>
      <div class="sample-btns">
        <button class="btn" onclick="loadSample('portrait_skin_real.png')">Portrait Skin Crop (150x150)</button>
        <button class="btn" onclick="loadSample('fashion_fabric_real.png')">Fashion Fabric Weave (200x200)</button>
        <button class="btn" onclick="loadSample('product_edges_real.png')">Product Metal Hardware (250x250)</button>
      </div>
    </div>

    <div class="panel">
      <h3>2. Model & Settings</h3>
      <label style="font-size: 12px; color: var(--text-muted);">Restoration Candidate:</label>
      <select id="model-select"></select>

      <label style="display: flex; align-items: center; gap: 8px; font-size: 13px; cursor: pointer; margin-top: 6px;">
        <input type="checkbox" id="tiled-check"> Enable Seamless Tiled Upscaling
      </label>
      <div id="tile-opts" style="display:none; margin-top: 8px;">
        <label style="font-size: 11px; color: var(--text-muted);">Tile Size (px):</label>
        <input type="number" id="tile-size" value="256" min="64" max="1024" step="64">
      </div>

      <button class="btn btn-primary" id="btn-upscale" style="width: 100%; margin-top: 14px;" onclick="runUpscale()">
        Upscale 4x
      </button>
      <button class="btn" id="btn-audition" style="width: 100%; margin-top: 8px; text-align: center;" onclick="runAudition()">
        Audition All Models
      </button>
    </div>
  </div>

  <div class="viewer-panel">
    <div class="viewer-toolbar">
      <div style="font-size: 13px;">
        <span id="view-title">Split Comparison: <strong>Source vs Upscaled</strong></span>
      </div>
      <div style="display: flex; gap: 6px;">
        <button class="tool-btn active" onclick="setZoom('fit')">Fit</button>
        <button class="tool-btn" onclick="setZoom('100')">100%</button>
        <button class="tool-btn" onclick="setZoom('200')">200% Grid</button>
        <a id="btn-download" class="tool-btn" style="display:none; text-decoration: none; color: inherit;" download="fidelis_upscaled.png">Download PNG</a>
      </div>
    </div>

    <div class="viewport" id="viewport">
      <div class="loading-overlay" id="loading">
        <div class="spinner"></div>
        <p style="margin-top: 14px; font-size: 14px;" id="loading-text">Upscaling with native GPU engine...</p>
      </div>
      
      <div id="empty-state" style="color: var(--text-muted); font-size: 14px; text-align: center;">
        No image loaded yet.<br>Drag and drop a photo or click a test crop on the left.
      </div>

      <div class="split-container" id="split-box" style="display:none;">
        <img id="img-after" alt="Upscaled">
        <div class="split-before" id="split-before">
          <img id="img-before" alt="Source">
        </div>
        <div class="split-slider" id="split-slider">
          <div class="split-handle">&#8646;</div>
        </div>
      </div>
    </div>

    <div class="metrics-box" id="metrics-bar" style="display:none;">
      <div class="metric-item">Model: <strong id="m-model">-</strong></div>
      <div class="metric-item">Time: <strong id="m-time">-</strong></div>
      <div class="metric-item">Rule #1: <span id="m-drift-status" class="status-pill status-pass">-</span></div>
      <div class="metric-item">Coherence: <strong id="m-coherence">-</strong></div>
      <div class="metric-item">Edge Shift: <strong id="m-shift">-</strong></div>
      <div class="metric-item">SSIM: <strong id="m-ssim" style="color:var(--success)">-</strong></div>
      <div class="metric-item">PSNR: <strong id="m-psnr">-</strong></div>
      <div class="metric-item">Color Drift: <strong id="m-drift">-</strong></div>
      <div class="metric-item">BG Noise: <strong id="m-bg">-</strong></div>
    </div>
  </div>
</div>

<script>
let currentSourceData = null;
let currentSourceFile = null;
let isDraggingSlider = false;

document.getElementById('tiled-check').addEventListener('change', e => {
  document.getElementById('tile-opts').style.display = e.target.checked ? 'block' : 'none';
});

// Setup models
fetch('/api/models').then(r => r.json()).then(models => {
  const sel = document.getElementById('model-select');
  models.forEach(m => {
    const opt = document.createElement('option');
    opt.value = m;
    opt.textContent = m + (m === 'RealeSR-general-v3' ? ' (Promoted Target)' : '');
    sel.appendChild(opt);
  });
});

// Drag and drop
const dropzone = document.getElementById('dropzone');
['dragenter', 'dragover'].forEach(name => {
  dropzone.addEventListener(name, e => { e.preventDefault(); dropzone.classList.add('dragover'); });
});
['dragleave', 'drop'].forEach(name => {
  dropzone.addEventListener(name, e => { e.preventDefault(); dropzone.classList.remove('dragover'); });
});
dropzone.addEventListener('drop', e => {
  if (e.dataTransfer.files && e.dataTransfer.files[0]) {
    handleFile(e.dataTransfer.files[0]);
  }
});
document.getElementById('file-input').addEventListener('change', e => {
  if (e.target.files && e.target.files[0]) handleFile(e.target.files[0]);
});

function handleFile(file) {
  currentSourceFile = file;
  const reader = new FileReader();
  reader.onload = ev => {
    currentSourceData = ev.target.result;
    showSourcePreview(currentSourceData);
  };
  reader.readAsDataURL(file);
}

function loadSample(sampleName) {
  fetch('/api/sample/' + sampleName).then(r => r.blob()).then(blob => {
    handleFile(new File([blob], sampleName, { type: "image/png" }));
  });
}

function showSourcePreview(b64) {
  document.getElementById('empty-state').style.display = 'none';
  const box = document.getElementById('split-box');
  box.style.display = 'inline-block';
  document.getElementById('img-before').src = b64;
  document.getElementById('img-after').src = b64;
  setSplitPosition(50);
}

function runUpscale() {
  if (!currentSourceData) return alert('Please load an image first.');
  const model = document.getElementById('model-select').value;
  const tiled = document.getElementById('tiled-check').checked;
  const tileSize = document.getElementById('tile-size').value;

  showLoading(true, `Upscaling 4x via ${model}...`);
  fetch('/api/upscale', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      image: currentSourceData,
      model: model,
      tiled: tiled,
      tile_size: parseInt(tileSize)
    })
  }).then(r => r.json()).then(data => {
    showLoading(false);
    if (data.error) return alert('Upscale failed: ' + data.error);

    document.getElementById('img-after').src = data.output_image;
    document.getElementById('btn-download').href = data.output_image;
    document.getElementById('btn-download').style.display = 'inline-block';
    setSplitPosition(50);

    // Update metrics & drift HUD
    document.getElementById('metrics-bar').style.display = 'flex';
    document.getElementById('m-model').textContent = model;
    document.getElementById('m-time').textContent = data.elapsed_ms + ' ms';
    if (data.metrics) {
      document.getElementById('m-ssim').textContent = data.metrics.ssim ?? '-';
      document.getElementById('m-psnr').textContent = (data.metrics.psnr_db ?? '-') + ' dB';
      document.getElementById('m-drift').textContent = data.metrics.color_drift ?? '-';
      document.getElementById('m-bg').textContent = data.metrics.bg_noise_restraint ?? '-';
    }
    if (data.drift) {
      const ds = document.getElementById('m-drift-status');
      const st = data.drift.status || 'UNKNOWN';
      ds.textContent = st;
      ds.className = 'status-pill ' + (st.includes('PASS') ? 'status-pass' : (st.includes('WARN') ? 'status-warn' : 'status-fail'));
      document.getElementById('m-coherence').textContent = (data.drift.gradient_coherence_pct != null ? data.drift.gradient_coherence_pct + '%' : '-');
      document.getElementById('m-shift').textContent = (data.drift.mean_edge_shift_px != null ? data.drift.mean_edge_shift_px + ' px' : '-');
    }
  }).catch(err => {
    showLoading(false);
    alert('Error: ' + err);
  });
}

function runAudition() {
  if (!currentSourceData) return alert('Please load an image first.');
  showLoading(true, 'Running full multi-model audition on local GPU...');
  fetch('/api/audition', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ image: currentSourceData })
  }).then(r => r.json()).then(data => {
    showLoading(false);
    if (data.report_url) {
      window.open(data.report_url, '_blank');
    } else {
      alert('Audition complete.');
    }
  }).catch(err => {
    showLoading(false);
    alert('Audition error: ' + err);
  });
}

function showLoading(show, text) {
  const el = document.getElementById('loading');
  el.style.display = show ? 'flex' : 'none';
  if (text) document.getElementById('loading-text').textContent = text;
}

// Split slider logic
const splitBox = document.getElementById('split-box');
const splitBefore = document.getElementById('split-before');
const splitSlider = document.getElementById('split-slider');

function setSplitPosition(pct) {
  splitBefore.style.width = pct + '%';
  splitSlider.style.left = pct + '%';
}

splitSlider.addEventListener('mousedown', () => isDraggingSlider = true);
window.addEventListener('mouseup', () => isDraggingSlider = false);
window.addEventListener('mousemove', e => {
  if (!isDraggingSlider) return;
  const rect = splitBox.getBoundingClientRect();
  let x = e.clientX - rect.left;
  let pct = Math.max(0, Math.min(100, (x / rect.width) * 100));
  setSplitPosition(pct);
});

function setZoom(mode) {
  document.querySelectorAll('.viewer-toolbar .tool-btn').forEach(b => b.classList.remove('active'));
  event.target.classList.add('active');
  const vp = document.getElementById('viewport');
  vp.classList.remove('zoom-100', 'zoom-200');
  if (mode === '100') vp.classList.add('zoom-100');
  if (mode === '200') vp.classList.add('zoom-200');
}
</script>
</body>
</html>
"""

class FidelisRequestHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Quiet logs

    def do_GET(self):
        url = urlparse(self.path)
        if url.path in ["/", "/index.html"]:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode("utf-8"))
        elif url.path == "/api/models":
            models = get_installed_models()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(models).encode("utf-8"))
        elif url.path.startswith("/api/sample/"):
            name = Path(url.path).name
            sample_file = REPO_ROOT / "experiments/eval_crops" / name
            if not sample_file.is_file():
                sample_file = REPO_ROOT / "tests/fixtures" / name
            if sample_file.is_file():
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.end_headers()
                self.wfile.write(sample_file.read_bytes())
            else:
                self.send_response(404)
                self.end_headers()
        elif url.path.startswith("/results/"):
            # Serve local HTML reports
            rel_path = url.path.replace("/results/", "")
            target = (REPO_ROOT / rel_path).resolve()
            if target.is_file() and str(target).startswith(str(REPO_ROOT)):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(target.read_bytes())
            else:
                self.send_response(404)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        url = urlparse(self.path)
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len)

        if url.path == "/api/upscale":
            data = json.loads(body.decode("utf-8"))
            raw_b64 = data.get("image", "").split(",")[-1]
            model = data.get("model", "RealeSR-general-v3")
            tiled = data.get("tiled", False)
            tile_size = data.get("tile_size", 256)

            with tempfile.TemporaryDirectory(prefix="fidelis_web_") as tmp:
                in_p = Path(tmp) / "input.png"
                out_p = Path(tmp) / "output.png"
                in_p.write_bytes(base64.b64decode(raw_b64))

                start = time.time()
                cli = shutil.which("fidelis") or str(REPO_ROOT / "bin/fidelis")
                if tiled:
                    cmd = [
                        sys.executable,
                        str(REPO_ROOT / "scripts/tiled-upscale.py"),
                        str(in_p),
                        str(out_p),
                        "-m", model,
                        "-t", str(tile_size)
                    ]
                else:
                    cmd = [cli, "upscale", str(in_p), str(out_p), "--model", model]

                subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                elapsed_ms = int((time.time() - start) * 1000)

                metrics = {}
                drift = {}
                if out_p.is_file():
                    try:
                        with Image.open(in_p) as sim, Image.open(out_p) as oim:
                            if HAS_METRICS:
                                metrics = eval_metrics.evaluate_pair(sim, oim)
                            if HAS_DRIFT:
                                drift = detect_drift.compute_drift(sim, oim)
                    except Exception as e:
                        print("Fidelity analysis error:", e)

                out_b64 = "data:image/png;base64," + base64.b64encode(out_p.read_bytes()).decode("ascii")

                resp = {
                    "output_image": out_b64,
                    "elapsed_ms": elapsed_ms,
                    "metrics": metrics,
                    "drift": drift
                }
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(resp).encode("utf-8"))

        elif url.path == "/api/audition":
            data = json.loads(body.decode("utf-8"))
            raw_b64 = data.get("image", "").split(",")[-1]

            aud_dir = REPO_ROOT / "experiments/eval_crops/web_audition"
            shutil.rmtree(aud_dir, ignore_errors=True)
            aud_dir.mkdir(parents=True, exist_ok=True)

            in_p = aud_dir / "web_input.png"
            in_p.write_bytes(base64.b64decode(raw_b64))

            cli = shutil.which("fidelis") or str(REPO_ROOT / "bin/fidelis")
            cmd = [cli, "audition", str(in_p), str(aud_dir)]
            subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            # Evaluate metrics & report
            if HAS_METRICS:
                try:
                    eval_metrics.evaluate_directory(aud_dir)
                except Exception:
                    pass

            report_script = REPO_ROOT / "scripts/generate-audition-report.py"
            subprocess.check_call([sys.executable, str(report_script), str(aud_dir)])

            resp = {"report_url": "/results/experiments/eval_crops/web_audition/report.html"}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(resp).encode("utf-8"))

def run_server(port: int = 8765):
    handler = FidelisRequestHandler
    # Allow port reuse
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", port), handler) as httpd:
        print(f"\n=======================================================")
        print(f" Fidelis Studio Web UI is running at:")
        print(f" http://127.0.0.1:{port}")
        print(f"=======================================================\n")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down server.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Fidelis Web UI.")
    parser.add_argument("-p", "--port", type=int, default=8765, help="Port to bind (default: 8765)")
    args = parser.parse_args()
    run_server(args.port)
