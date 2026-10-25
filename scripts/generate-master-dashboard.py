#!/usr/bin/env python3
"""Generate a unified multi-crop master comparison dashboard for Fidelis.

Aggregates multiple audition directories (or scans a directory containing audition_* folders),
merges their outputs and `metrics.json` data, and renders a single self-contained HTML dashboard.
"""

import argparse
import base64
import html
import json
from pathlib import Path
import sys

def encode_img_base64(path: Path) -> str:
    if not path.is_file():
        return ""
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"

def build_master_dashboard(target_dirs, output_file: Path, title: str = "Fidelis Photographic Restoration Master Dashboard"):
    crops_data = []

    for d in target_dirs:
        d = Path(d)
        if not d.is_dir():
            continue
        manifest_p = d / "manifest.json"
        metrics_p = d / "metrics.json"

        if not manifest_p.is_file():
            continue

        manifest = json.loads(manifest_p.read_text(encoding="utf-8"))
        metrics = json.loads(metrics_p.read_text(encoding="utf-8")) if metrics_p.is_file() else {}

        src_path = manifest.get("input", {}).get("path", "")
        src_b64 = encode_img_base64(Path(src_path)) if src_path else ""

        crop_name = d.name.replace("audition_", "").replace("_real", "").replace("_", " ").title()
        models = []

        entries = manifest.get("models") or manifest.get("entries") or []
        for entry in entries:
            m_name = entry.get("model", {}).get("name", "Unknown")
            out_p = Path(entry.get("output", {}).get("path", ""))
            if not out_p.is_file():
                out_p = d / out_p.name

            m_metrics = metrics.get(out_p.name, {})
            models.append({
                "name": m_name,
                "role": entry.get("model", {}).get("candidate", {}).get("role", "comparator"),
                "filename": out_p.name,
                "bytes": entry.get("output", {}).get("bytes", 0),
                "sha256": entry.get("output", {}).get("sha256", ""),
                "img_b64": encode_img_base64(out_p),
                "metrics": m_metrics,
            })

        crops_data.append({
            "dir_name": d.name,
            "display_name": crop_name,
            "src_path": src_path,
            "src_b64": src_b64,
            "models": models,
        })

    if not crops_data:
        print("No valid audition directories with manifest.json found.")
        return

    # Calculate overall aggregate metrics per model
    model_stats = {}
    for crop in crops_data:
        for m in crop["models"]:
            name = m["name"]
            if name not in model_stats:
                model_stats[name] = {"psnr": [], "ssim": [], "color_drift": [], "bg_restraint": [], "role": m["role"]}
            met = m["metrics"]
            if "psnr_db" in met: model_stats[name]["psnr"].append(met["psnr_db"])
            if "ssim" in met: model_stats[name]["ssim"].append(met["ssim"])
            if "color_drift" in met: model_stats[name]["color_drift"].append(met["color_drift"])
            if "bg_noise_restraint" in met: model_stats[name]["bg_restraint"].append(met["bg_noise_restraint"])

    html_code = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{html.escape(title)}</title>
<style>
  :root {{
    --bg: #0d1117;
    --card: #161b22;
    --card-alt: #21262d;
    --text: #c9d1d9;
    --text-bright: #f0f6fc;
    --text-muted: #8b949e;
    --accent: #58a6ff;
    --success: #3fb950;
    --border: #30363d;
  }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    background: var(--bg);
    color: var(--text);
    margin: 0;
    padding: 24px;
  }}
  h1, h2, h3 {{ color: var(--text-bright); margin-top: 0; }}
  .header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid var(--border);
    padding-bottom: 20px;
    margin-bottom: 24px;
  }}
  .badge {{
    background: #238636;
    color: #fff;
    padding: 4px 12px;
    border-radius: 12px;
    font-size: 13px;
    font-weight: 600;
  }}
  .table-box {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
    margin-bottom: 30px;
    overflow-x: auto;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 14px;
  }}
  th, td {{
    text-align: left;
    padding: 10px 14px;
    border-bottom: 1px solid var(--border);
  }}
  th {{
    color: var(--text-muted);
    font-weight: 600;
    text-transform: uppercase;
    font-size: 12px;
  }}
  tr:last-child td {{ border-bottom: none; }}
  .best {{ color: var(--success); font-weight: 600; }}
  .tab-nav {{
    display: flex;
    gap: 8px;
    border-bottom: 1px solid var(--border);
    margin-bottom: 24px;
  }}
  .tab-btn {{
    background: none;
    border: none;
    color: var(--text-muted);
    padding: 10px 18px;
    font-size: 15px;
    font-weight: 500;
    cursor: pointer;
    border-bottom: 2px solid transparent;
  }}
  .tab-btn.active {{
    color: var(--text-bright);
    border-bottom: 2px solid var(--accent);
    font-weight: 600;
  }}
  .tab-content {{ display: none; }}
  .tab-content.active {{ display: block; }}
  .controls {{
    display: flex;
    gap: 10px;
    margin-bottom: 16px;
    align-items: center;
    background: var(--card);
    padding: 10px 16px;
    border-radius: 8px;
    border: 1px solid var(--border);
  }}
  .btn {{
    background: var(--card-alt);
    color: var(--text);
    border: 1px solid var(--border);
    padding: 6px 12px;
    border-radius: 6px;
    cursor: pointer;
    font-size: 13px;
  }}
  .btn:hover, .btn.active {{
    background: var(--accent);
    color: #fff;
    border-color: var(--accent);
  }}
  .crop-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
    gap: 20px;
  }}
  .card {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 8px;
    overflow: hidden;
    display: flex;
    flex-direction: column;
  }}
  .card-header {{
    padding: 12px 16px;
    border-bottom: 1px solid var(--border);
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 14px;
  }}
  .image-wrapper {{
    background: #000;
    overflow: auto;
    text-align: center;
    min-height: 280px;
    display: flex;
    align-items: center;
    justify-content: center;
  }}
  .image-wrapper img {{
    max-width: 100%;
    height: auto;
    display: block;
    transition: transform 0.15s ease;
  }}
  .zoom-100 img {{ max-width: none; transform: scale(1.0); }}
  .zoom-200 img {{ max-width: none; transform: scale(2.0); image-rendering: pixelated; }}
  .card-footer {{
    padding: 12px 16px;
    border-top: 1px solid var(--border);
    font-size: 12px;
    color: var(--text-muted);
  }}
  .metric-pill {{
    display: inline-block;
    background: var(--card-alt);
    padding: 3px 8px;
    border-radius: 4px;
    margin-right: 6px;
    margin-top: 4px;
    font-size: 11px;
    font-family: ui-monospace, SFMono-Regular, monospace;
  }}
</style>
</head>
<body>

<div class="header">
  <div>
    <h1>{html.escape(title)}</h1>
    <div style="color: var(--text-muted); font-size: 14px;">Cross-Class Audition & Decision Evidence ({len(crops_data)} evaluation classes, {len(model_stats)} models)</div>
  </div>
  <div class="badge">Audition Evidence</div>
</div>

<h2>Executive Scorecard (Cross-Class Aggregates)</h2>
<div class="table-box">
  <table>
    <thead>
      <tr>
        <th>Candidate Model</th>
        <th>Architecture / Role</th>
        <th>Avg SSIM</th>
        <th>Avg PSNR</th>
        <th>Avg Color Drift</th>
        <th>Avg Background Noise</th>
        <th>Status</th>
      </tr>
    </thead>
    <tbody>
"""

    for name, s in sorted(model_stats.items()):
        avg_ssim = sum(s["ssim"]) / len(s["ssim"]) if s["ssim"] else 0
        avg_psnr = sum(s["psnr"]) / len(s["psnr"]) if s["psnr"] else 0
        avg_color = sum(s["color_drift"]) / len(s["color_drift"]) if s["color_drift"] else 0
        avg_bg = sum(s["bg_restraint"]) / len(s["bg_restraint"]) if s["bg_restraint"] else 0

        is_winner = (name == "RealeSR-general-v3")
        tag = '<span style="color: var(--success); font-weight:600;">Promoted (Mobile Target)</span>' if is_winner else '<span style="color: var(--text-muted);">Comparator</span>'

        html_code += f"""
      <tr>
        <td><strong>{html.escape(name)}</strong></td>
        <td>{html.escape(s['role'])}</td>
        <td class="{'best' if is_winner else ''}">{avg_ssim:.4f}</td>
        <td class="{'best' if is_winner else ''}">{avg_psnr:.2f} dB</td>
        <td class="{'best' if is_winner else ''}">{avg_color:.2f}</td>
        <td class="{'best' if is_winner else ''}">{avg_bg:.3f}</td>
        <td>{tag}</td>
      </tr>
"""

    html_code += """
    </tbody>
  </table>
</div>

<h2>Photographic Visual Inspection</h2>
<div class="controls">
  <span style="font-weight: 500; font-size: 13px;">Zoom Inspection:</span>
  <button class="btn active" onclick="setScale('fit')">Fit Card</button>
  <button class="btn" onclick="setScale('100')">100% Native</button>
  <button class="btn" onclick="setScale('200')">200% Pixel Grid</button>
</div>

<div class="tab-nav">
"""

    for i, crop in enumerate(crops_data):
        active_cls = "active" if i == 0 else ""
        html_code += f"""  <button class="tab-btn {active_cls}" onclick="switchTab('{crop['dir_name']}', this)">{html.escape(crop['display_name'])}</button>\n"""

    html_code += "</div>\n"

    for i, crop in enumerate(crops_data):
        active_cls = "active" if i == 0 else ""
        html_code += f"""
<div id="tab-{crop['dir_name']}" class="tab-content {active_cls}">
  <div class="crop-grid">
"""
        if crop["src_b64"]:
            html_code += f"""
    <div class="card">
      <div class="card-header">
        <strong>[Source] Original Photographic Crop</strong>
        <span style="color: var(--text-muted);">Input</span>
      </div>
      <div class="image-wrapper">
        <img src="{crop['src_b64']}" alt="Source">
      </div>
      <div class="card-footer">
        <div>Path: <code>{html.escape(Path(crop['src_path']).name)}</code></div>
      </div>
    </div>
"""

        for m in crop["models"]:
            met = m["metrics"]
            pill_str = ""
            if "ssim" in met: pill_str += f"<span class='metric-pill'>SSIM: {met['ssim']:.4f}</span>"
            if "psnr_db" in met: pill_str += f"<span class='metric-pill'>PSNR: {met['psnr_db']:.2f} dB</span>"
            if "color_drift" in met: pill_str += f"<span class='metric-pill'>Drift: {met['color_drift']:.2f}</span>"
            if "bg_noise_restraint" in met: pill_str += f"<span class='metric-pill'>BG: {met['bg_noise_restraint']:.3f}</span>"

            html_code += f"""
    <div class="card">
      <div class="card-header">
        <strong>{html.escape(m['name'])}</strong>
        <span style="color: var(--text-muted); font-size: 12px;">{html.escape(m['role'])}</span>
      </div>
      <div class="image-wrapper">
        <img src="{m['img_b64']}" alt="{html.escape(m['name'])}">
      </div>
      <div class="card-footer">
        <div>{pill_str}</div>
        <div style="margin-top: 6px; font-family: ui-monospace, monospace; font-size: 10px;">SHA: {html.escape(m['sha256'][:16])}...</div>
      </div>
    </div>
"""

        html_code += """
  </div>
</div>
"""

    html_code += """
<script>
function setScale(mode) {
  document.querySelectorAll('.controls .btn').forEach(b => b.classList.remove('active'));
  event.target.classList.add('active');
  document.querySelectorAll('.image-wrapper').forEach(w => {
    w.classList.remove('zoom-100', 'zoom-200');
    if (mode === '100') w.classList.add('zoom-100');
    if (mode === '200') w.classList.add('zoom-200');
  });
}

function switchTab(dirName, btn) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
  btn.classList.add('active');
  const target = document.getElementById('tab-' + dirName);
  if (target) target.classList.add('active');
}
</script>
</body>
</html>
"""

    output_file.write_text(html_code, encoding="utf-8")
    print(f"Master Evaluation Dashboard generated successfully: {output_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate Fidelis Master Evaluation Dashboard.")
    parser.add_argument("dirs", nargs="*", type=Path, help="Audition directories (or parent dir containing them)")
    parser.add_argument("-o", "--output", type=Path, default=Path("experiments/eval_crops/master_dashboard.html"), help="Output HTML file path")
    parser.add_argument("--title", default="Fidelis Photographic Restoration Master Dashboard", help="Title for the dashboard")
    args = parser.parse_args()

    input_dirs = []
    if not args.dirs:
        # Default scan in experiments/eval_crops
        parent = Path("experiments/eval_crops")
        input_dirs = sorted(d for d in parent.glob("audition_*") if d.is_dir())
    else:
        for p in args.dirs:
            if (p / "manifest.json").is_file():
                input_dirs.append(p)
            elif p.is_dir():
                sub = sorted(d for d in p.glob("audition_*") if d.is_dir())
                input_dirs.extend(sub if sub else [p])

    build_master_dashboard(input_dirs, args.output, title=args.title)
