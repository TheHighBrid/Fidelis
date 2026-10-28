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
import traceback
import uuid
from urllib.parse import parse_qs, urlparse
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / ".cache" / "web_outputs"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Ensure REPO_ROOT is in sys.path
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

try:
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

try:
    import cv2
    import numpy as np
    import fidelis
    from fidelis.core.router import SmartRouter, UpscaleMode
    from fidelis.engine.diffusion_sr import DiffusionPresetsEngine
    from fidelis.modules.face_restorer import FaceRestorer
    from fidelis.modules.text_restorer import TextRestorer
    from fidelis.postprocess.color_fix import stabilize_colors
    from fidelis.eval.benchmark_suite import BenchmarkSuite
    HAS_FIDELIS = True
except Exception as e:
    HAS_FIDELIS = False

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
    -webkit-touch-callout: default;
  }
  .split-container img {
    display: block;
    max-width: 100%;
    height: auto;
    -webkit-touch-callout: default;
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
        <button class="btn" onclick="loadSample('user_test_blonde.png')">Blonde Portrait (1022x1024)</button>
        <button class="btn" onclick="loadSample('user_test_darkhair.png')">Dark Hair Portrait (1024x1024)</button>
        <button class="btn" onclick="loadSample('portrait_skin_real.png')">Portrait Skin Crop (150x150)</button>
        <button class="btn" onclick="loadSample('fashion_fabric_real.png')">Fashion Fabric Weave (200x200)</button>
        <button class="btn" onclick="loadSample('product_edges_real.png')">Product Metal Hardware (250x250)</button>
      </div>
    </div>

    <!-- Live Degradation & Semantics Profiler Panel -->
    <div class="panel" id="profiler-panel" style="display:none; background: #161b22; border: 1px solid var(--border); margin-top: 12px;">
      <h3 style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
        <span>Degradation Profiler</span>
        <span id="prof-mode-badge" class="badge" style="background: #1f6feb; font-size: 11px;">ROUTED</span>
      </h3>
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 6px; font-size: 11px; color: var(--text-muted);">
        <div>Resolution: <strong id="prof-dim" style="color: var(--text);">-</strong></div>
        <div>Blur Score: <strong id="prof-blur" style="color: var(--text);">-</strong></div>
        <div>Noise Var: <strong id="prof-noise" style="color: var(--text);">-</strong></div>
        <div>JPEG Grid: <strong id="prof-jpeg" style="color: var(--text);">-</strong></div>
        <div>Faces Detected: <strong id="prof-faces" style="color: var(--text);">-</strong></div>
        <div>Text Regions: <strong id="prof-text" style="color: var(--text);">-</strong></div>
      </div>
      <div style="margin-top: 8px; font-size: 11px; padding: 6px; background: #0d1117; border-radius: 4px; border: 1px solid var(--border);">
        Recommended Preset: <strong id="prof-rec" style="color: var(--accent);">-</strong>
      </div>
    </div>

    <div class="panel">
      <h3>2. Mode & Settings</h3>
      <div style="display: flex; gap: 8px; margin-bottom: 12px;">
        <button id="mode-single-btn" class="tool-btn active" style="flex: 1; text-align: center; padding: 6px;" onclick="setCompareMode('single')">Source vs Model</button>
        <button id="mode-dual-btn" class="tool-btn" style="flex: 1; text-align: center; padding: 6px;" onclick="setCompareMode('dual')">Model vs Model</button>
      </div>

      <div style="margin-bottom: 10px;">
        <label style="font-size: 12px; color: var(--text-muted);">Fidelis Flagship Preset:</label>
        <select id="preset-select" onchange="onPresetChange()">
          <option value="Smart_Balanced" selected>Smart_Balanced (1-Step Distilled - Default)</option>
          <option value="Fast_Fidelity">Fast_Fidelity (Deterministic RAESR/HAT - 0 Hallucination)</option>
          <option value="Photo_Restore">Photo_Restore (Generative Skin & Texture Rebuild)</option>
          <option value="LowLight_Denoise">LowLight_Denoise (Sensor Grain & High-ISO Fix)</option>
          <option value="Archival_BW">Archival_BW (Historical Scans & Damaged Photos)</option>
          <option value="Ultra_Redefine">Ultra_Redefine (Magnific-Grade Creative Scale)</option>
        </select>
      </div>

      <div id="single-model-box">
        <label style="font-size: 12px; color: var(--text-muted);">Restoration Candidate:</label>
        <select id="model-select"></select>
      </div>

      <div id="dual-model-box" style="display:none;">
        <label style="font-size: 12px; color: var(--text-muted);">Model A (Left):</label>
        <select id="model-a-select"></select>
        <label style="font-size: 12px; color: var(--text-muted); margin-top: 6px; display: block;">Model B (Right):</label>
        <select id="model-b-select"></select>
      </div>

      <!-- Diffusion & Creativity Controls -->
      <div id="diffusion-controls" style="margin-top: 10px; padding: 8px; background: rgba(255,255,255,0.03); border-radius: 6px; border: 1px solid var(--border);">
        <div style="display: flex; justify-content: space-between; font-size: 11px; color: var(--text-muted);">
          <span>Creativity (Denoising Guidance):</span>
          <strong id="creativity-val" style="color: var(--text);">0.50</strong>
        </div>
        <input type="range" id="creativity-slider" min="0.0" max="1.0" step="0.05" value="0.50" style="width: 100%; cursor: pointer;" oninput="document.getElementById('creativity-val').textContent = parseFloat(this.value).toFixed(2)">

        <div style="display: flex; justify-content: space-between; font-size: 11px; color: var(--text-muted); margin-top: 6px;">
          <span>Resemblance (Structural Anchor):</span>
          <strong id="resemblance-val" style="color: var(--text);">0.70</strong>
        </div>
        <input type="range" id="resemblance-slider" min="0.20" max="1.0" step="0.05" value="0.70" style="width: 100%; cursor: pointer;" oninput="document.getElementById('resemblance-val').textContent = parseFloat(this.value).toFixed(2)">
      </div>

      <!-- Portrait Face Engine -->
      <div style="margin-top: 10px; padding: 10px; background: rgba(88, 166, 255, 0.08); border: 1px solid rgba(88, 166, 255, 0.25); border-radius: 6px;">
        <label style="display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 600; cursor: pointer; color: #58a6ff;">
          <input type="checkbox" id="portrait-check" checked onchange="togglePortraitOpts()"> Portrait Pore Engine (Anti-Dollification)
        </label>
        <div id="portrait-opts" style="margin-top: 8px;">
          <div style="display: flex; justify-content: space-between; font-size: 11px; color: var(--text-muted); margin-bottom: 4px;">
            <span>Face Fidelity Weight (w):</span>
            <strong id="fidelity-val" style="color: var(--text);">0.70</strong>
          </div>
          <input type="range" id="fidelity-slider" min="0.30" max="0.95" step="0.05" value="0.70" style="width: 100%; cursor: pointer;" oninput="document.getElementById('fidelity-val').textContent = parseFloat(this.value).toFixed(2)">
          <div style="font-size: 10px; color: var(--text-muted); margin-top: 4px; line-height: 1.3;">
            0.40: High synthesis | <strong>0.70: Balanced (Zero dollification)</strong> | 0.90: Strict source
          </div>
        </div>
      </div>

      <!-- Text & Logo Preservation -->
      <label style="display: flex; align-items: center; gap: 8px; font-size: 13px; cursor: pointer; margin-top: 10px;">
        <input type="checkbox" id="text-check" checked> Text & Logo Guard (TiGeSR / DualTSR)
      </label>

      <!-- Color Stabilization -->
      <div style="margin-top: 10px;">
        <label style="font-size: 11px; color: var(--text-muted);">Color Stabilization:</label>
        <select id="color-fix-select">
          <option value="auto" selected>Auto (Wavelet <=2x, AdaIN >=4x)</option>
          <option value="wavelet">Stationary Wavelet (J=5)</option>
          <option value="adain">AdaIN Color Normalization</option>
          <option value="none">Direct / Uncompensated</option>
        </select>
      </div>

      <label style="display: flex; align-items: center; gap: 8px; font-size: 13px; cursor: pointer; margin-top: 10px;">
        <input type="checkbox" id="tiled-check"> Enable MultiDiffusion Tiling
      </label>
      <div id="tile-opts" style="display:none; margin-top: 8px;">
        <label style="font-size: 11px; color: var(--text-muted);">Tile Size (px):</label>
        <input type="number" id="tile-size" value="256" min="64" max="1024" step="64">
      </div>

      <button class="btn btn-primary" id="btn-run" style="width: 100%; margin-top: 14px;" onclick="runAction()">
        Upscale 4x
      </button>
      <button class="btn" id="btn-audition" style="width: 100%; margin-top: 8px; text-align: center;" onclick="runAudition()">
        Audition All Models
      </button>
    </div>
  </div>

  <div class="viewer-panel">
    <div class="viewer-toolbar">
      <div style="font-size: 13px; display: flex; align-items: center; gap: 8px;">
        <span id="view-title">Split Comparison: <strong>Source vs Upscaled</strong></span>
        <span id="badge-left" class="badge" style="background:#21262d; border:1px solid var(--border); font-size:11px; display:none;">Left: Source</span>
        <span id="badge-right" class="badge" style="background:#21262d; border:1px solid var(--border); font-size:11px; display:none;">Right: Output</span>
      </div>
      <div style="display: flex; gap: 6px; flex-wrap: wrap;">
        <button class="tool-btn active" onclick="setZoom('fit')">Fit</button>
        <button class="tool-btn" onclick="setZoom('100')">100%</button>
        <button class="tool-btn" onclick="setZoom('200')">200% Grid</button>
        <button id="btn-download" class="tool-btn" style="display:none; background:#238636; color:#ffffff; font-weight:600; cursor:pointer;" onclick="downloadResultImage()">Download PNG</button>
        <a id="btn-open-tab" class="tool-btn" style="display:none; text-decoration: none; color: inherit;" target="_blank">View Full Image</a>
      </div>
    </div>

    <div class="viewport" id="viewport">
      <div class="loading-overlay" id="loading">
        <div class="spinner"></div>
        <p style="margin-top: 14px; font-size: 14px; text-align: center; max-width: 80%;" id="loading-text">Upscaling with native GPU engine...</p>
        <button class="tool-btn" style="margin-top: 14px; background: #21262d; border: 1px solid var(--border);" onclick="showLoading(false)">Dismiss Overlay</button>
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

    <div class="metrics-box" id="metrics-bar" style="display:none; flex-wrap: wrap;">
      <div class="metric-item">Preset/Model: <strong id="m-model">-</strong></div>
      <div class="metric-item">Latency: <strong id="m-time">-</strong></div>
      <div class="metric-item">Rule #1: <span id="m-drift-status" class="status-pill status-pass">-</span></div>
      <div class="metric-item">Hallucination: <strong id="m-risk" style="color:var(--success)">LOW</strong></div>
      <div class="metric-item">Coherence: <strong id="m-coherence">-</strong></div>
      <div class="metric-item">SSIM: <strong id="m-ssim" style="color:var(--success)">-</strong></div>
      <div class="metric-item">PSNR: <strong id="m-psnr">-</strong></div>
      <div class="metric-item">CIELAB &Delta;E: <strong id="m-drift">-</strong></div>
      <div class="metric-item">Edge Energy: <strong id="m-bg">-</strong></div>
    </div>
  </div>
</div>

<script>
let currentSourceData = null;
let currentSourceFile = null;
let isDraggingSlider = false;
let currentCompareMode = 'single';

function setCompareMode(mode) {
  currentCompareMode = mode;
  document.getElementById('mode-single-btn').classList.toggle('active', mode === 'single');
  document.getElementById('mode-dual-btn').classList.toggle('active', mode === 'dual');
  document.getElementById('single-model-box').style.display = mode === 'single' ? 'block' : 'none';
  document.getElementById('dual-model-box').style.display = mode === 'dual' ? 'block' : 'none';
  document.getElementById('btn-run').textContent = mode === 'single' ? 'Upscale 4x' : 'Compare Models 4x (A vs B)';
  document.getElementById('badge-left').style.display = mode === 'dual' ? 'inline-block' : 'none';
  document.getElementById('badge-right').style.display = mode === 'dual' ? 'inline-block' : 'none';
}

function runAction() {
  if (currentCompareMode === 'single') {
    runUpscale();
  } else {
    runCompare();
  }
}

document.getElementById('tiled-check').addEventListener('change', e => {
  document.getElementById('tile-opts').style.display = e.target.checked ? 'block' : 'none';
});

// Setup models
fetch('/api/models').then(r => r.json()).then(models => {
  ['model-select', 'model-a-select', 'model-b-select'].forEach(id => {
    const sel = document.getElementById(id);
    if (!sel) return;
    sel.innerHTML = '';
    models.forEach(m => {
      const opt = document.createElement('option');
      opt.value = m;
      opt.textContent = m + (m === 'RealeSR-general-v3' ? ' (Promoted Target)' : '');
      sel.appendChild(opt);
    });
  });
  const selB = document.getElementById('model-b-select');
  if (selB && selB.options.length > 1) selB.selectedIndex = 1;
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
    profileImage(currentSourceData);
  };
  reader.readAsDataURL(file);
}

function profileImage(dataUrl) {
  fetch('/api/profile', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ image: dataUrl })
  })
  .then(r => r.json())
  .then(data => {
    if (data.width) {
      document.getElementById('profiler-panel').style.display = 'block';
      document.getElementById('prof-dim').textContent = `${data.width}x${data.height} px`;
      document.getElementById('prof-blur').textContent = data.blur_score;
      document.getElementById('prof-noise').textContent = data.noise_variance;
      document.getElementById('prof-jpeg').textContent = data.jpeg_blockiness;
      document.getElementById('prof-faces').textContent = data.face_count;
      document.getElementById('prof-text').textContent = data.text_count;
      document.getElementById('prof-rec').textContent = data.recommended_model;
      document.getElementById('prof-mode-badge').textContent = data.recommended_mode.toUpperCase();

      if (data.face_count > 0) {
        document.getElementById('portrait-check').checked = true;
        togglePortraitOpts();
      }
      if (data.text_count > 0) {
        document.getElementById('text-check').checked = true;
      }
    }
  })
  .catch(() => {});
}

function onPresetChange() {
  const p = document.getElementById('preset-select').value;
  if (p === 'Fast_Fidelity') {
    document.getElementById('creativity-slider').value = 0.0;
    document.getElementById('creativity-val').textContent = '0.00';
    document.getElementById('resemblance-slider').value = 1.0;
    document.getElementById('resemblance-val').textContent = '1.00';
    document.getElementById('portrait-check').checked = false;
    togglePortraitOpts();
  } else if (p === 'Smart_Balanced') {
    document.getElementById('creativity-slider').value = 0.50;
    document.getElementById('creativity-val').textContent = '0.50';
    document.getElementById('resemblance-slider').value = 0.70;
    document.getElementById('resemblance-val').textContent = '0.70';
    document.getElementById('portrait-check').checked = true;
    togglePortraitOpts();
  } else if (p === 'Photo_Restore') {
    document.getElementById('creativity-slider').value = 0.65;
    document.getElementById('creativity-val').textContent = '0.65';
    document.getElementById('resemblance-slider').value = 0.60;
    document.getElementById('resemblance-val').textContent = '0.60';
    document.getElementById('fidelity-slider').value = 0.50;
    document.getElementById('fidelity-val').textContent = '0.50';
    document.getElementById('portrait-check').checked = true;
    togglePortraitOpts();
  } else if (p === 'Ultra_Redefine') {
    document.getElementById('creativity-slider').value = 0.85;
    document.getElementById('creativity-val').textContent = '0.85';
    document.getElementById('resemblance-slider').value = 0.50;
    document.getElementById('resemblance-val').textContent = '0.50';
  }
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

function togglePortraitOpts() {
  const chk = document.getElementById('portrait-check');
  const opts = document.getElementById('portrait-opts');
  if (opts) opts.style.display = chk.checked ? 'block' : 'none';
}

let currentDownloadUrl = null;
let currentOutputBase64 = null;
let currentViewUrl = null;

function downloadResultImage() {
  if (!currentOutputBase64 && !currentDownloadUrl) {
    return alert('No upscaled image available to download.');
  }

  // 1. Native Android App Bridge (saves directly into device Pictures/Fidelis)
  if (window.AndroidApp) {
    if (typeof window.AndroidApp.saveImage === 'function' && currentOutputBase64) {
      window.AndroidApp.saveImage(currentOutputBase64, 'fidelis_upscaled.png');
      return;
    }
    if (typeof window.AndroidApp.downloadFromUrl === 'function' && currentDownloadUrl) {
      const fullUrl = window.location.origin + currentDownloadUrl;
      window.AndroidApp.downloadFromUrl(fullUrl, 'fidelis_upscaled.png');
      return;
    }
  }

  // 2. HTTP Server-Side Download (Fastest, avoids base64 URL limitations)
  if (currentDownloadUrl) {
    const a = document.createElement('a');
    a.href = currentDownloadUrl;
    a.download = 'fidelis_upscaled.png';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    return;
  }

  // 3. Blob URL Fallback
  try {
    const parts = currentOutputBase64.split(',');
    const byteString = atob(parts[1]);
    const mimeString = parts[0].split(':')[1].split(';')[0];
    const ab = new ArrayBuffer(byteString.length);
    const ia = new Uint8Array(ab);
    for (let i = 0; i < byteString.length; i++) {
      ia[i] = byteString.charCodeAt(i);
    }
    const blob = new Blob([ia], { type: mimeString });
    const blobUrl = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = blobUrl;
    a.download = 'fidelis_upscaled.png';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(blobUrl), 30000);
  } catch (err) {
    // 4. Fallback: open in new window
    window.open(currentOutputBase64, '_blank');
  }
}

function runUpscale() {
  if (!currentSourceData) return alert('Please load an image first.');
  const preset = document.getElementById('preset-select').value;
  const model = document.getElementById('model-select').value;
  const creativity = parseFloat(document.getElementById('creativity-slider').value);
  const resemblance = parseFloat(document.getElementById('resemblance-slider').value);
  const textPreserve = document.getElementById('text-check').checked;
  const colorFix = document.getElementById('color-fix-select').value;
  const tiled = document.getElementById('tiled-check').checked;
  const tileSize = document.getElementById('tile-size').value;
  const portrait = document.getElementById('portrait-check').checked;
  const fidelity = parseFloat(document.getElementById('fidelity-slider').value);

  const loadText = portrait
    ? `Flagship ${preset}: Restoring skin pores & facial fidelity (w=${fidelity.toFixed(2)})...`
    : `Flagship ${preset}: Enhancing via ${model}...`;
  showLoading(true, loadText);
  fetch('/api/upscale', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      image: currentSourceData,
      preset: preset,
      model: model,
      creativity: creativity,
      resemblance: resemblance,
      text_preserve: textPreserve,
      color_fix: colorFix,
      tiled: tiled,
      tile_size: parseInt(tileSize),
      portrait: portrait,
      fidelity: fidelity
    })
  }).then(async r => {
    const data = await r.json().catch(() => ({ error: 'Server error (HTTP ' + r.status + ')' }));
    showLoading(false);
    if (!r.ok || data.error) return alert('Upscale failed: ' + (data.error || 'Unknown error'));

    const titlePrefix = portrait ? `Portrait Pore Engine (${preset})` : `${preset} - ${model}`;
    document.getElementById('view-title').innerHTML = `Split Comparison: <strong>Source vs ${titlePrefix}</strong>`;
    document.getElementById('badge-left').style.display = 'none';
    document.getElementById('badge-right').style.display = 'none';

    currentOutputBase64 = data.output_image;
    currentDownloadUrl = data.download_url;
    currentViewUrl = data.view_url;

    document.getElementById('img-after').src = data.output_image;
    document.getElementById('btn-download').style.display = 'inline-block';
    if (data.view_url) {
      const openBtn = document.getElementById('btn-open-tab');
      openBtn.href = data.view_url;
      openBtn.style.display = 'inline-block';
    }
    setSplitPosition(50);

    // Update 5-dimension metrics HUD
    document.getElementById('metrics-bar').style.display = 'flex';
    document.getElementById('m-model').textContent = portrait ? `${preset}+CodeFormer(w=${fidelity.toFixed(2)})` : `${preset} (${model})`;
    document.getElementById('m-time').textContent = data.elapsed_ms + ' ms';
    if (data.metrics) {
      document.getElementById('m-ssim').textContent = data.metrics.ssim != null ? data.metrics.ssim : '-';
      document.getElementById('m-psnr').textContent = (data.metrics.psnr_db != null ? data.metrics.psnr_db : '-') + ' dB';
      document.getElementById('m-drift').textContent = data.metrics.cielab_delta_e != null ? data.metrics.cielab_delta_e : (data.metrics.color_drift ?? '-');
      document.getElementById('m-bg').textContent = data.metrics.edge_energy_gain_pct != null ? data.metrics.edge_energy_gain_pct + '%' : (data.metrics.bg_noise_restraint ?? '-');
      if (data.metrics.gradient_coherence_pct != null) {
        document.getElementById('m-coherence').textContent = data.metrics.gradient_coherence_pct + '%';
      }
      if (data.metrics.hallucination_risk) {
        const hr = document.getElementById('m-risk');
        hr.textContent = data.metrics.hallucination_risk;
        hr.style.color = data.metrics.hallucination_risk === 'LOW' ? 'var(--success)' : (data.metrics.hallucination_risk === 'MODERATE' ? 'var(--warning)' : 'var(--danger)');
      }
      if (data.metrics.rule1_status) {
        const ds = document.getElementById('m-drift-status');
        const st = data.metrics.rule1_status;
        ds.textContent = st;
        ds.className = 'status-pill ' + (st.includes('PASS') ? 'status-pass' : (st.includes('WARN') ? 'status-warn' : 'status-fail'));
      }
    }
    if (data.drift && !data.metrics?.rule1_status) {
      const ds = document.getElementById('m-drift-status');
      const st = data.drift.status || 'UNKNOWN';
      ds.textContent = st;
      ds.className = 'status-pill ' + (st.includes('PASS') ? 'status-pass' : (st.includes('WARN') ? 'status-warn' : 'status-fail'));
      if (data.drift.gradient_coherence_pct != null) {
        document.getElementById('m-coherence').textContent = data.drift.gradient_coherence_pct + '%';
      }
    }
  }).catch(err => {
    showLoading(false);
    alert('Network error connecting to Fidelis server: ' + err.message);
  });
}

function runCompare() {
  if (!currentSourceData) return alert('Please load an image first.');
  const preset = document.getElementById('preset-select').value;
  const modelA = document.getElementById('model-a-select').value;
  const modelB = document.getElementById('model-b-select').value;
  const creativity = parseFloat(document.getElementById('creativity-slider').value);
  const resemblance = parseFloat(document.getElementById('resemblance-slider').value);
  const textPreserve = document.getElementById('text-check').checked;
  const colorFix = document.getElementById('color-fix-select').value;
  const tiled = document.getElementById('tiled-check').checked;
  const tileSize = document.getElementById('tile-size').value;
  const portrait = document.getElementById('portrait-check').checked;
  const fidelity = parseFloat(document.getElementById('fidelity-slider').value);

  const loadText = portrait
    ? `Comparing ${modelA} vs ${modelB} with pore restoration...`
    : `Comparing ${modelA} vs ${modelB}...`;
  showLoading(true, loadText);
  fetch('/api/compare', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      image: currentSourceData,
      preset: preset,
      model_a: modelA,
      model_b: modelB,
      creativity: creativity,
      resemblance: resemblance,
      text_preserve: textPreserve,
      color_fix: colorFix,
      tiled: tiled,
      tile_size: parseInt(tileSize),
      portrait: portrait,
      fidelity: fidelity
    })
  }).then(async r => {
    const data = await r.json().catch(() => ({ error: 'Server error (HTTP ' + r.status + ')' }));
    showLoading(false);
    if (!r.ok || data.error) return alert('Comparison failed: ' + (data.error || 'Unknown error'));

    document.getElementById('img-before').src = data.output_a;
    document.getElementById('img-after').src = data.output_b;
    currentOutputBase64 = data.output_b;
    currentDownloadUrl = data.download_url_b;
    currentViewUrl = data.view_url_b;
    document.getElementById('btn-download').style.display = 'inline-block';
    if (data.view_url_b) {
      const openBtn = document.getElementById('btn-open-tab');
      openBtn.href = data.view_url_b;
      openBtn.style.display = 'inline-block';
    }
    setSplitPosition(50);

    document.getElementById('view-title').innerHTML = `Split: <strong>${data.model_a} (Left) vs ${data.model_b} (Right)</strong>`;
    document.getElementById('badge-left').textContent = `Left: ${data.model_a}`;
    document.getElementById('badge-right').textContent = `Right: ${data.model_b}`;
    document.getElementById('badge-left').style.display = 'inline-block';
    document.getElementById('badge-right').style.display = 'inline-block';

    // Update metrics HUD
    document.getElementById('metrics-bar').style.display = 'flex';
    document.getElementById('m-model').textContent = `${data.model_a} vs ${data.model_b}`;
    document.getElementById('m-time').textContent = `${data.elapsed_ms_a}ms / ${data.elapsed_ms_b}ms`;

    const ssimA = data.metrics_a?.ssim ?? '-';
    const ssimB = data.metrics_b?.ssim ?? '-';
    document.getElementById('m-ssim').textContent = `${ssimA} / ${ssimB}`;

    const psnrA = data.metrics_a?.psnr_db ?? '-';
    const psnrB = data.metrics_b?.psnr_db ?? '-';
    document.getElementById('m-psnr').textContent = `${psnrA} / ${psnrB} dB`;

    const drA = data.metrics_a?.cielab_delta_e ?? (data.metrics_a?.color_drift ?? '-');
    const drB = data.metrics_b?.cielab_delta_e ?? (data.metrics_b?.color_drift ?? '-');
    document.getElementById('m-drift').textContent = `${drA} / ${drB}`;

    const bgA = data.metrics_a?.edge_energy_gain_pct != null ? data.metrics_a.edge_energy_gain_pct + '%' : (data.metrics_a?.bg_noise_restraint ?? '-');
    const bgB = data.metrics_b?.edge_energy_gain_pct != null ? data.metrics_b.edge_energy_gain_pct + '%' : (data.metrics_b?.bg_noise_restraint ?? '-');
    document.getElementById('m-bg').textContent = `${bgA} / ${bgB}`;

    const rA = data.metrics_a?.hallucination_risk ?? '-';
    const rB = data.metrics_b?.hallucination_risk ?? '-';
    document.getElementById('m-risk').textContent = `${rA} / ${rB}`;

    const cohA = (data.metrics_a?.gradient_coherence_pct != null ? data.metrics_a.gradient_coherence_pct + '%' : (data.drift_a?.gradient_coherence_pct != null ? data.drift_a.gradient_coherence_pct + '%' : '-'));
    const cohB = (data.metrics_b?.gradient_coherence_pct != null ? data.metrics_b.gradient_coherence_pct + '%' : (data.drift_b?.gradient_coherence_pct != null ? data.drift_b.gradient_coherence_pct + '%' : '-'));
    document.getElementById('m-coherence').textContent = `${cohA} / ${cohB}`;

    const stA = data.metrics_a?.rule1_status || data.drift_a?.status || 'UNKNOWN';
    const stB = data.metrics_b?.rule1_status || data.drift_b?.status || 'UNKNOWN';
    const ds = document.getElementById('m-drift-status');
    ds.textContent = `A:${stA.split(' ')[0]} | B:${stB.split(' ')[0]}`;
    ds.className = 'status-pill ' + (stA.includes('PASS') && stB.includes('PASS') ? 'status-pass' : (stA.includes('FAIL') || stB.includes('FAIL') ? 'status-fail' : 'status-warn'));
  }).catch(err => {
    showLoading(false);
    alert('Comparison network error: ' + err.message);
  });
}

function runAudition() {
  if (!currentSourceData) return alert('Please load an image first.');
  const confirmed = confirm(
    "Auditioning all 4 models will process this entire image across 4 different AI architectures sequentially.\n\n" +
    "On high-resolution camera photos, this can take a few minutes.\n\n" +
    "Tip: For instant (~3.7s) single-model enhancement, use the green 'Upscale 4x' button instead.\n\n" +
    "Do you want to proceed with full audition?"
  );
  if (!confirmed) return;
  showLoading(true, 'Auditioning all candidate models... You can dismiss this overlay while it processes.');
  fetch('/api/audition', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ image: currentSourceData })
  }).then(async r => {
    const data = await r.json().catch(() => ({ error: 'Server error (HTTP ' + r.status + ')' }));
    showLoading(false);
    if (!r.ok || data.error) return alert('Audition failed: ' + (data.error || 'Unknown error'));

    if (data.report_url) {
      if (confirm('Audition complete! Open full comparison report?')) {
        window.location.href = data.report_url;
      }
    } else {
      alert('Audition complete.');
    }
  }).catch(err => {
    showLoading(false);
    alert('Audition network error: ' + err.message);
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

def execute_restoration(cli, in_p, out_p, model, tiled=False, tile_size=256, portrait=False, fidelity=0.70,
                        text_preserve=True, color_fix="auto", preset="Smart_Balanced",
                        creativity=0.50, resemblance=0.70):
    t0 = time.time()
    with tempfile.TemporaryDirectory(prefix="fidelis_step_") as step_tmp:
        curr_in = in_p
        with Image.open(in_p) as im:
            w, h = im.size

        # Stage 1: Base Super-Resolution / Tiling
        up_target = Path(step_tmp) / "step1_upscaled.png"
        if tiled:
            cmd = [
                sys.executable,
                str(REPO_ROOT / "scripts/tiled-upscale.py"),
                str(curr_in),
                str(up_target),
                "-m", model,
                "-t", str(tile_size)
            ]
        else:
            cmd = [cli, "upscale", str(curr_in), str(up_target), "--model", model]

        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            err_msg = res.stderr.strip() or res.stdout.strip()
            raise RuntimeError(f"Upscaling failed ({res.returncode}): {err_msg}")

        curr_step = up_target

        # Stage 2: Text-First Glyph Restoration (TiGeSR / DualTSR with strict empty-text guard)
        if text_preserve and HAS_FIDELIS:
            try:
                sr_cv = cv2.imread(str(curr_step))
                if sr_cv is not None:
                    txt_restorer = TextRestorer()
                    restored_cv, count = txt_restorer.restore_text(sr_cv, sharpening_strength=0.65)
                    if count > 0:
                        text_target = Path(step_tmp) / "step2_text.png"
                        cv2.imwrite(str(text_target), restored_cv)
                        curr_step = text_target
            except Exception as e:
                print("Text restoration warning:", e)

        # Stage 3: Facial Identity & Authentic Pore Restoration (CodeFormer w=fidelity)
        if portrait:
            port_target = Path(step_tmp) / "step3_portrait.png"
            port_cmd = [cli, "portrait", str(curr_step), str(port_target), "-w", str(fidelity)]
            res = subprocess.run(port_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if res.returncode == 0 and port_target.is_file():
                curr_step = port_target
            else:
                err_msg = res.stderr.strip() or res.stdout.strip()
                print(f"Portrait step warning ({res.returncode}): {err_msg}")

        # Stage 4: Color Drift Stabilization (Stationary Wavelet J=5 or AdaIN)
        if color_fix != "none" and HAS_FIDELIS:
            try:
                src_cv = cv2.imread(str(in_p))
                sr_cv = cv2.imread(str(curr_step))
                if src_cv is not None and sr_cv is not None:
                    fix_mode = color_fix
                    if fix_mode == "auto":
                        fix_mode = "wavelet" if (sr_cv.shape[1] / max(src_cv.shape[1], 1)) <= 2.5 else "adain"
                    stabilized = stabilize_colors(sr_img=sr_cv, lq_img=src_cv, scale_factor=4.0, preferred_mode=fix_mode)
                    color_target = Path(step_tmp) / "step4_color.png"
                    cv2.imwrite(str(color_target), stabilized)
                    curr_step = color_target
            except Exception as e:
                print("Color stabilization warning:", e)

        # Final delivery
        shutil.copyfile(str(curr_step), str(out_p))

    return int((time.time() - t0) * 1000)


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
        elif url.path == "/api/download":
            query = parse_qs(url.query)
            file_id = query.get("id", [""])[0]
            filename = query.get("filename", ["fidelis_upscaled.png"])[0]
            safe_id = os.path.basename(file_id)
            safe_name = os.path.basename(filename) or "fidelis_upscaled.png"
            target = (CACHE_DIR / f"{safe_id}.png").resolve()
            if safe_id and target.is_file() and str(target).startswith(str(CACHE_DIR.resolve())):
                data = target.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Disposition", f'attachment; filename="{safe_name}"')
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_response(404)
                self.end_headers()
        elif url.path == "/api/view":
            query = parse_qs(url.query)
            file_id = query.get("id", [""])[0]
            safe_id = os.path.basename(file_id)
            target = (CACHE_DIR / f"{safe_id}.png").resolve()
            if safe_id and target.is_file() and str(target).startswith(str(CACHE_DIR.resolve())):
                data = target.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Disposition", "inline")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_response(404)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        url = urlparse(self.path)
        try:
            content_len = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_len)
            cli = str(REPO_ROOT / "bin/fidelis") if (REPO_ROOT / "bin/fidelis").is_file() else (shutil.which("fidelis") or "fidelis")

            if url.path == "/api/profile":
                data = json.loads(body.decode("utf-8"))
                raw_b64 = data.get("image", "").split(",")[-1]
                img_bytes = base64.b64decode(raw_b64)
                arr = cv2.imdecode(np.frombuffer(img_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
                if arr is None:
                    raise ValueError("Failed to decode uploaded image for profiling")

                router = SmartRouter()
                route_res = router.route(arr, requested_mode=UpscaleMode.AUTO)
                prof = route_res["profile"]

                resp = {
                    "width": prof.width,
                    "height": prof.height,
                    "blur_score": prof.blur_score,
                    "noise_variance": prof.noise_variance,
                    "jpeg_blockiness": prof.jpeg_blockiness,
                    "face_count": prof.face_count,
                    "text_count": prof.text_count,
                    "recommended_mode": prof.recommended_mode,
                    "recommended_model": prof.recommended_model,
                    "tier": route_res["tier"],
                    "actions": route_res["actions"]
                }
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(resp).encode("utf-8"))

            elif url.path == "/api/upscale":
                data = json.loads(body.decode("utf-8"))
                raw_b64 = data.get("image", "").split(",")[-1]
                preset = data.get("preset", "Smart_Balanced")
                model = data.get("model", "RealeSR-general-v3")
                creativity = float(data.get("creativity", 0.50))
                resemblance = float(data.get("resemblance", 0.70))
                text_preserve = bool(data.get("text_preserve", True))
                color_fix = data.get("color_fix", "auto")
                tiled = data.get("tiled", False)
                tile_size = data.get("tile_size", 256)
                portrait = data.get("portrait", False)
                fidelity = float(data.get("fidelity", 0.70))

                with tempfile.TemporaryDirectory(prefix="fidelis_web_") as tmp:
                    in_p = Path(tmp) / "input.png"
                    out_p = Path(tmp) / "output.png"
                    in_p.write_bytes(base64.b64decode(raw_b64))

                    elapsed_ms = execute_restoration(
                        cli, in_p, out_p, model,
                        tiled=tiled, tile_size=tile_size,
                        portrait=portrait, fidelity=fidelity,
                        text_preserve=text_preserve, color_fix=color_fix,
                        preset=preset, creativity=creativity, resemblance=resemblance
                    )

                    metrics = {}
                    drift = {}
                    if out_p.is_file():
                        try:
                            if HAS_FIDELIS:
                                bench = BenchmarkSuite()
                                metrics = bench.evaluate_pair(in_p, out_p).to_dict()
                            elif HAS_METRICS:
                                with Image.open(in_p) as sim, Image.open(out_p) as oim:
                                    metrics = eval_metrics.evaluate_pair(sim, oim)
                            if HAS_DRIFT:
                                with Image.open(in_p) as sim, Image.open(out_p) as oim:
                                    drift = detect_drift.compute_drift(sim, oim)
                        except Exception as e:
                            print("Fidelity analysis error:", e)

                    raw_out_bytes = out_p.read_bytes()
                    out_b64 = "data:image/png;base64," + base64.b64encode(raw_out_bytes).decode("ascii")

                    token = f"fidelis_{int(time.time())}_{uuid.uuid4().hex[:6]}"
                    (CACHE_DIR / f"{token}.png").write_bytes(raw_out_bytes)
                    model_slug = "portrait" if portrait else model.replace(" ", "_")
                    download_url = f"/api/download?id={token}&filename=fidelis_{model_slug}.png"
                    view_url = f"/api/view?id={token}"

                    resp = {
                        "output_image": out_b64,
                        "download_url": download_url,
                        "view_url": view_url,
                        "elapsed_ms": elapsed_ms,
                        "metrics": metrics,
                        "drift": drift
                    }
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps(resp).encode("utf-8"))

            elif url.path == "/api/compare":
                data = json.loads(body.decode("utf-8"))
                raw_b64 = data.get("image", "").split(",")[-1]
                preset = data.get("preset", "Smart_Balanced")
                model_a = data.get("model_a", "RealeSR-general-v3")
                model_b = data.get("model_b", "DF2K")
                creativity = float(data.get("creativity", 0.50))
                resemblance = float(data.get("resemblance", 0.70))
                text_preserve = bool(data.get("text_preserve", True))
                color_fix = data.get("color_fix", "auto")
                tiled = data.get("tiled", False)
                tile_size = data.get("tile_size", 256)
                portrait = data.get("portrait", False)
                fidelity = float(data.get("fidelity", 0.70))

                with tempfile.TemporaryDirectory(prefix="fidelis_cmp_") as tmp:
                    in_p = Path(tmp) / "input.png"
                    out_a = Path(tmp) / "out_a.png"
                    out_b = Path(tmp) / "out_b.png"
                    in_p.write_bytes(base64.b64decode(raw_b64))

                    elapsed_a = execute_restoration(
                        cli, in_p, out_a, model_a,
                        tiled=tiled, tile_size=tile_size,
                        portrait=portrait, fidelity=fidelity,
                        text_preserve=text_preserve, color_fix=color_fix,
                        preset=preset, creativity=creativity, resemblance=resemblance
                    )
                    elapsed_b = execute_restoration(
                        cli, in_p, out_b, model_b,
                        tiled=tiled, tile_size=tile_size,
                        portrait=portrait, fidelity=fidelity,
                        text_preserve=text_preserve, color_fix=color_fix,
                        preset=preset, creativity=creativity, resemblance=resemblance
                    )

                    metrics_a, drift_a = {}, {}
                    metrics_b, drift_b = {}, {}

                    if HAS_FIDELIS:
                        bench = BenchmarkSuite()
                        if out_a.is_file():
                            metrics_a = bench.evaluate_pair(in_p, out_a).to_dict()
                        if out_b.is_file():
                            metrics_b = bench.evaluate_pair(in_p, out_b).to_dict()
                    elif HAS_METRICS:
                        with Image.open(in_p) as sim:
                            if out_a.is_file():
                                with Image.open(out_a) as oim:
                                    metrics_a = eval_metrics.evaluate_pair(sim, oim)
                            if out_b.is_file():
                                with Image.open(out_b) as oim:
                                    metrics_b = eval_metrics.evaluate_pair(sim, oim)

                    if HAS_DRIFT:
                        with Image.open(in_p) as sim:
                            if out_a.is_file():
                                with Image.open(out_a) as oim:
                                    drift_a = detect_drift.compute_drift(sim, oim)
                            if out_b.is_file():
                                with Image.open(out_b) as oim:
                                    drift_b = detect_drift.compute_drift(sim, oim)

                    bytes_a = out_a.read_bytes()
                    bytes_b = out_b.read_bytes()

                    token_a = f"fidelis_cmp_a_{int(time.time())}_{uuid.uuid4().hex[:6]}"
                    token_b = f"fidelis_cmp_b_{int(time.time())}_{uuid.uuid4().hex[:6]}"
                    (CACHE_DIR / f"{token_a}.png").write_bytes(bytes_a)
                    (CACHE_DIR / f"{token_b}.png").write_bytes(bytes_b)

                    resp = {
                        "output_a": "data:image/png;base64," + base64.b64encode(bytes_a).decode("ascii"),
                        "output_b": "data:image/png;base64," + base64.b64encode(bytes_b).decode("ascii"),
                        "download_url_a": f"/api/download?id={token_a}&filename=fidelis_{model_a}.png",
                        "download_url_b": f"/api/download?id={token_b}&filename=fidelis_{model_b}.png",
                        "view_url_a": f"/api/view?id={token_a}",
                        "view_url_b": f"/api/view?id={token_b}",
                        "model_a": model_a,
                        "model_b": model_b,
                        "elapsed_ms_a": elapsed_a,
                        "elapsed_ms_b": elapsed_b,
                        "metrics_a": metrics_a,
                        "metrics_b": metrics_b,
                        "drift_a": drift_a,
                        "drift_b": drift_b
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

                cmd = [cli, "audition", str(in_p), str(aud_dir)]
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                if res.returncode != 0:
                    err_msg = res.stderr.strip() or res.stdout.strip()
                    raise RuntimeError(f"Audition failed ({res.returncode}): {err_msg}")

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
            else:
                self.send_response(404)
                self.end_headers()
        except Exception as e:
            traceback.print_exc()
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))

def run_server(port: int = 8765, host: str = "0.0.0.0"):
    handler = FidelisRequestHandler
    # Allow port reuse
    socketserver.TCPServer.allow_reuse_address = True

    current_port = port
    httpd = None
    for attempt in range(30):
        try:
            httpd = socketserver.TCPServer((host, current_port), handler)
            break
        except OSError as e:
            if getattr(e, "errno", None) in (48, 98):  # EADDRINUSE on macOS/Linux
                print(f"[notice] Port {current_port} is already in use by another process. Trying {current_port + 1}...")
                current_port += 1
            else:
                raise

    if not httpd:
        raise OSError(f"Could not find an open port starting from {port}")

    with httpd:
        display_host = "127.0.0.1" if host in ("0.0.0.0", "") else host
        print(f"\n=======================================================")
        print(f" Fidelis Studio Web UI is running at:")
        print(f" http://{display_host}:{current_port} (all interfaces: {host})")
        print(f"=======================================================\n")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down server.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Fidelis Web UI.")
    parser.add_argument("-b", "--bind", "--host", default=os.environ.get("HOST", "0.0.0.0"), help="Host interface to bind (default: 0.0.0.0)")
    parser.add_argument("-p", "--port", type=int, default=8765, help="Port to bind (default: 8765)")
    args = parser.parse_args()
    run_server(port=args.port, host=args.bind)
