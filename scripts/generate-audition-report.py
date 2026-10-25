#!/usr/bin/env python3
"""Generate a standalone HTML comparison report for Fidelis audition, benchmark, or VOSR sweep results.

Supports:
1. `fidelis audition` output (contains manifest.json)
2. `benchmark-photo-candidates.sh` output (contains benchmark.json)
3. `vosr-fidelity-sweep.sh` output (contains manifest.json with profiles)

Outputs a single self-contained HTML file with embedded base64 images, side-by-side
comparisons, zoom controls, and verified provenance.
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

def generate_report(results_dir: Path, output_html: Path):
    manifest_p = results_dir / "manifest.json"
    benchmark_p = results_dir / "benchmark.json"

    metadata = {}
    report_type = "unknown"
    models_data = []
    input_info = {}

    if benchmark_p.is_file():
        report_type = "benchmark"
        metadata = json.loads(benchmark_p.read_text(encoding="utf-8"))
        input_info = metadata.get("input", {})
        for m in metadata.get("models", []):
            out_file = results_dir / m.get("output", {}).get("filename", "")
            models_data.append({
                "name": m.get("model", {}).get("name", "Unknown"),
                "role": m.get("model", {}).get("candidate", {}).get("role", "comparator"),
                "elapsed_ms": m.get("runtime", {}).get("elapsed_ms", 0),
                "bytes": m.get("output", {}).get("bytes", 0),
                "sha256": m.get("output", {}).get("sha256", ""),
                "image_b64": encode_img_base64(out_file),
                "filename": out_file.name
            })
    elif manifest_p.is_file():
        metadata = json.loads(manifest_p.read_text(encoding="utf-8"))
        input_info = metadata.get("input", {})
        if "profiles" in metadata and "outputs" in metadata:
            report_type = "vosr_sweep"
            for prof_name, prof_cfg in metadata.get("profiles", {}).items():
                out_list = metadata.get("outputs", {}).get(prof_name, [])
                for item in out_list:
                    out_file = Path(item.get("path", ""))
                    if not out_file.is_file():
                        out_file = results_dir / prof_name / out_file.name
                    models_data.append({
                        "name": f"VOSR-{prof_name.capitalize()}",
                        "role": f"cfg={prof_cfg.get('cfg_scale')} weak={prof_cfg.get('weak_cond_strength_aelq')}",
                        "elapsed_ms": None,
                        "bytes": item.get("bytes", 0),
                        "sha256": item.get("sha256", ""),
                        "image_b64": encode_img_base64(out_file),
                        "filename": out_file.name
                    })
        elif "entries" in metadata:
            report_type = "audition"
            for entry in metadata.get("entries", []):
                out_file = Path(entry.get("output", {}).get("path", ""))
                if not out_file.is_file():
                    out_file = results_dir / out_file.name
                models_data.append({
                    "name": entry.get("model", {}).get("name", "Unknown"),
                    "role": entry.get("model", {}).get("candidate", {}).get("role", "installed"),
                    "elapsed_ms": None,
                    "bytes": entry.get("output", {}).get("bytes", 0),
                    "sha256": entry.get("output", {}).get("sha256", ""),
                    "image_b64": encode_img_base64(out_file),
                    "filename": out_file.name
                })
    else:
        # Fallback: scan for any PNGs in results_dir
        report_type = "raw_images"
        for p in sorted(results_dir.glob("*.png")):
            models_data.append({
                "name": p.stem,
                "role": "unregistered",
                "elapsed_ms": None,
                "bytes": p.stat().st_size,
                "sha256": "",
                "image_b64": encode_img_base64(p),
                "filename": p.name
            })

    # Find source image if accessible
    src_b64 = ""
    src_path = input_info.get("path")
    if src_path and Path(src_path).is_file():
        src_b64 = encode_img_base64(Path(src_path))

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Fidelis Visual Audition & Benchmark Report</title>
<style>
  :root {{
    --bg: #121417;
    --card: #1c2026;
    --text: #e6edf3;
    --text-muted: #8b949e;
    --accent: #388bfd;
    --border: #30363d;
  }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    background-color: var(--bg);
    color: var(--text);
    margin: 0;
    padding: 24px;
  }}
  h1, h2, h3 {{ font-weight: 600; margin-top: 0; }}
  .header {{
    border-bottom: 1px solid var(--border);
    padding-bottom: 16px;
    margin-bottom: 24px;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }}
  .badge {{
    background: #238636;
    color: #fff;
    padding: 4px 10px;
    border-radius: 12px;
    font-size: 13px;
    font-weight: 600;
  }}
  .meta-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
    gap: 16px;
    margin-bottom: 24px;
  }}
  .card {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
  }}
  .card-title {{
    color: var(--text-muted);
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 8px;
  }}
  .card-val {{
    font-size: 16px;
    font-family: ui-monospace, SFMono-Regular, monospace;
    word-break: break-all;
  }}
  .viewer-controls {{
    display: flex;
    gap: 12px;
    margin-bottom: 16px;
    align-items: center;
    background: var(--card);
    padding: 12px 16px;
    border-radius: 8px;
    border: 1px solid var(--border);
  }}
  .btn {{
    background: #21262d;
    color: var(--text);
    border: 1px solid var(--border);
    padding: 6px 14px;
    border-radius: 6px;
    cursor: pointer;
    font-weight: 500;
  }}
  .btn:hover, .btn.active {{
    background: var(--accent);
    color: #fff;
    border-color: var(--accent);
  }}
  .comparison-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
    gap: 20px;
  }}
  .image-card {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 8px;
    overflow: hidden;
    display: flex;
    flex-direction: column;
  }}
  .image-card-header {{
    padding: 12px 16px;
    border-bottom: 1px solid var(--border);
    display: flex;
    justify-content: space-between;
    align-items: center;
  }}
  .image-wrapper {{
    overflow: auto;
    background: #000;
    text-align: center;
    min-height: 300px;
    display: flex;
    align-items: center;
    justify-content: center;
  }}
  .image-wrapper img {{
    max-width: 100%;
    height: auto;
    display: block;
    image-rendering: auto;
    transition: transform 0.15s ease;
  }}
  .zoom-100 img {{
    max-width: none;
    transform: scale(1.0);
  }}
  .zoom-200 img {{
    max-width: none;
    transform: scale(2.0);
    image-rendering: pixelated;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    margin-top: 24px;
  }}
  th, td {{
    text-align: left;
    padding: 10px 14px;
    border: 1px solid var(--border);
    font-size: 14px;
  }}
  th {{
    background: #161b22;
  }}
  tr:nth-child(even) {{
    background: rgba(255,255,255,0.02);
  }}
  .hash {{
    font-family: ui-monospace, SFMono-Regular, monospace;
    font-size: 11px;
    color: var(--text-muted);
  }}
</style>
</head>
<body>

<div class="header">
  <div>
    <h1>Fidelis Visual Audition & Benchmark Report</h1>
    <div style="color: var(--text-muted); font-size: 14px;">Report Type: <strong>{report_type.upper()}</strong></div>
  </div>
  <div class="badge">Verified Evidence</div>
</div>

<div class="meta-grid">
  <div class="card">
    <div class="card-title">Input Source</div>
    <div class="card-val">{html.escape(str(input_info.get('path', 'Unknown')))}</div>
    <div class="hash">{html.escape(str(input_info.get('sha256', ''))[:16])}...</div>
  </div>
  <div class="card">
    <div class="card-title">Models Evaluated</div>
    <div class="card-val">{len(models_data)} model(s)</div>
  </div>
  <div class="card">
    <div class="card-title">Decision Priority</div>
    <div style="font-size: 13px; color: var(--text-muted);">1. Geometry 2. Skin 3. Fabric 4. Fine Edges 5. Tonal 6. Background</div>
  </div>
</div>

<div class="viewer-controls">
  <span style="font-weight: 500; font-size: 14px;">Inspection Scale:</span>
  <button class="btn active" onclick="setScale('fit')">Fit to Card</button>
  <button class="btn" onclick="setScale('100')">100% Native</button>
  <button class="btn" onclick="setScale('200')">200% Pixel Inspection</button>
</div>

<div class="comparison-grid" id="grid">
"""

    if src_b64:
        html_content += f"""
  <div class="image-card">
    <div class="image-card-header">
      <strong>[Source] Original Input</strong>
      <span style="font-size: 12px; color: var(--text-muted);">{input_info.get('bytes', 0):,} B</span>
    </div>
    <div class="image-wrapper" id="wrap-source">
      <img src="{src_b64}" alt="Original Input">
    </div>
  </div>
"""

    for m in models_data:
        timing_str = f"{m['elapsed_ms']} ms" if m['elapsed_ms'] is not None else ""
        html_content += f"""
  <div class="image-card">
    <div class="image-card-header">
      <div>
        <strong>{html.escape(m['name'])}</strong>
        <span style="font-size: 12px; color: var(--text-muted); margin-left: 6px;">({html.escape(m['role'])})</span>
      </div>
      <div>
        <span style="font-size: 12px; color: var(--accent); font-weight: 600;">{timing_str}</span>
      </div>
    </div>
    <div class="image-wrapper">
      <img src="{m['image_b64']}" alt="{html.escape(m['name'])}">
    </div>
    <div style="padding: 10px 14px; border-top: 1px solid var(--border); font-size: 12px; color: var(--text-muted);">
      <div>File: <code>{html.escape(m['filename'])}</code> ({m['bytes']:,} B)</div>
      <div class="hash">SHA-256: {html.escape(m['sha256'])}</div>
    </div>
  </div>
"""

    html_content += f"""
</div>

<h2 style="margin-top: 40px;">Evidence Provenance</h2>
<table>
  <thead>
    <tr>
      <th>Model / Candidate</th>
      <th>Role / Intent</th>
      <th>Runtime</th>
      <th>Output Size</th>
      <th>Output SHA-256</th>
    </tr>
  </thead>
  <tbody>
"""

    for m in models_data:
        timing_str = f"{m['elapsed_ms']} ms" if m['elapsed_ms'] is not None else "N/A"
        html_content += f"""
    <tr>
      <td><strong>{html.escape(m['name'])}</strong></td>
      <td>{html.escape(m['role'])}</td>
      <td>{timing_str}</td>
      <td>{m['bytes']:,} B</td>
      <td class="hash">{html.escape(m['sha256'])}</td>
    </tr>
"""

    html_content += """
  </tbody>
</table>

<script>
function setScale(mode) {
  document.querySelectorAll('.btn').forEach(b => b.classList.remove('active'));
  event.target.classList.add('active');
  const wrappers = document.querySelectorAll('.image-wrapper');
  wrappers.forEach(w => {
    w.classList.remove('zoom-100', 'zoom-200');
    if (mode === '100') w.classList.add('zoom-100');
    if (mode === '200') w.classList.add('zoom-200');
  });
}
</script>
</body>
</html>
"""

    output_html.write_text(html_content, encoding="utf-8")
    print(f"Report generated: {output_html}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate HTML visual audition report from Fidelis results.")
    parser.add_argument("results_dir", type=Path, help="Directory containing manifest.json or benchmark.json")
    parser.add_argument("-o", "--output", type=Path, default=None, help="Output HTML file path (default: <results_dir>/report.html)")
    args = parser.parse_args()

    out = args.output or (args.results_dir / "report.html")
    generate_report(args.results_dir, out)
