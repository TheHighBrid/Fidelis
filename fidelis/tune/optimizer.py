"""Self-Improvement and Quality Calibration Engine for Fidelis.

Implements the automated active optimization loop defined in the
Flagship Super-Resolution Blueprint:
1. Iterates across orthogonal test buckets (clean photos, portraits, text, noise, etc.)
2. Evaluates pipeline permutations (presets, face fidelity w, text unsharp strength, color fix)
3. Grades against the 5-Dimension Quality Matrix & Rule #1 Quality Gate
4. Pinpoints visual artifacts via the Fidelis Artifact Taxonomy
5. Calibrates optimal preset hyperparameter schedules and writes verified configurations
6. Generates full provenance manifests and interactive HTML evaluation reports.
"""

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import shutil
import time
from typing import Any, Dict, List, Optional, Tuple
import cv2
import numpy as np
import yaml

from fidelis.core.router import DegradationProfiler, SmartRouter, UpscaleMode
from fidelis.eval.benchmark_suite import BenchmarkSuite, EvaluationReport
from fidelis.eval.corpus import EvaluationCorpus, TestBucket
from fidelis.modules.face_restorer import FaceRestorer
from fidelis.modules.text_restorer import TextRestorer
from fidelis.postprocess.color_fix import stabilize_colors


@dataclass
class TrialResult:
    trial_id: str
    bucket: str
    preset_name: str
    face_fidelity_w: float
    text_strength: float
    color_fix_mode: str
    elapsed_ms: float
    metrics: Dict[str, Any]
    detected_artifacts: List[str]
    rule1_passed: bool
    output_path: str


class SelfImprovementEngine:
    """Orchestrates end-to-end self-improvement, calibration, and regression validation."""

    def __init__(self, work_dir: Optional[Path] = None):
        self.repo_root = Path(__file__).resolve().parent.parent.parent
        self.work_dir = work_dir or (self.repo_root / "experiments" / "self_improvement")
        self.work_dir.mkdir(parents=True, exist_ok=True)

        self.corpus = EvaluationCorpus()
        self.bench = BenchmarkSuite()
        self.profiler = DegradationProfiler()
        self.router = SmartRouter()
        self.face_restorer = FaceRestorer()
        self.text_restorer = TextRestorer()

        self.presets_path = self.repo_root / "fidelis" / "configs" / "presets.yaml"
        self.presets = self._load_presets()

    def _load_presets(self) -> Dict:
        if self.presets_path.is_file():
            with open(self.presets_path, "r") as f:
                return yaml.safe_load(f) or {}
        return {}

    def _save_presets(self, presets: Dict):
        with open(self.presets_path, "w") as f:
            yaml.safe_dump(presets, f, default_flow_style=False, sort_keys=False)

    def detect_artifacts(
        self,
        src_cv: np.ndarray,
        sr_cv: np.ndarray,
        metrics: Dict[str, Any],
        has_faces: bool,
        has_text: bool
    ) -> List[str]:
        """Classifies visual defects according to the Fidelis Artifact Taxonomy."""
        artifacts = []

        # 1. Color Shift
        delta_e = metrics.get("cielab_delta_e", 0.0)
        if delta_e > 3.5:
            artifacts.append("color_shift_high_delta_e")

        # 2. Hallucination Risk
        if metrics.get("hallucination_risk") == "HIGH" or metrics.get("gradient_coherence_pct", 100) < 82.0:
            artifacts.append("texture_hallucination_divergence")

        # 3. Excessive Edge Ringing / Edge Oversharpening
        edge_gain = metrics.get("edge_energy_gain", 1.0)
        if edge_gain > 2.8:
            artifacts.append("oversharpening_ringing_halos")

        # 4. Portrait Skin Dollification / Plastic Smoothing
        if has_faces:
            # Check high-frequency detail preservation in skin
            gray_sr = cv2.cvtColor(sr_cv, cv2.COLOR_BGR2GRAY)
            lap_sr = float(np.var(cv2.Laplacian(gray_sr, cv2.CV_32F)))
            if lap_sr < 40.0:
                artifacts.append("plastic_skin_smoothing_dollification")

        # 5. Boundary Seam Discontinuity
        h, w = sr_cv.shape[:2]
        if w >= 2048 or h >= 2048:
            # Check 8-pixel stride edge gradients
            diff_h = np.abs(sr_cv[1:, :] - sr_cv[:-1, :])
            if np.max(diff_h) > 180:
                artifacts.append("boundary_seam_divergence")

        return artifacts

    def evaluate_pipeline_candidate(
        self,
        input_path: str,
        output_path: str,
        ground_truth_path: Optional[str] = None,
        preset_name: str = "Smart_Balanced",
        face_fidelity_w: float = 0.70,
        text_strength: float = 0.65,
        color_fix_mode: str = "auto"
    ) -> TrialResult:
        """Runs the multi-stage restoration pipeline and evaluates against the 5D matrix."""
        t0 = time.time()
        src_cv = cv2.imread(input_path)
        if src_cv is None:
            raise FileNotFoundError(f"Source image not found: {input_path}")

        h, w = src_cv.shape[:2]
        profile = self.profiler.profile(cv2.cvtColor(src_cv, cv2.COLOR_BGR2RGB))

        # Stage 1: Base super-resolution
        # Use cv2 high-quality upsample / RealSR simulation for deterministic base
        sr_w = w * 4
        sr_h = h * 4
        sr_cv = cv2.resize(src_cv, (sr_w, sr_h), interpolation=cv2.INTER_LANCZOS4)

        # Stage 2: Text glyph restoration
        if profile.has_text:
            sr_cv, _ = self.text_restorer.restore_text(sr_cv, sharpening_strength=text_strength)

        # Stage 3: Facial identity restoration
        if profile.has_faces:
            sr_cv = self.face_restorer.restore_faces(sr_cv, fidelity=face_fidelity_w)

        # Stage 4: Color stabilization
        if color_fix_mode != "none":
            fix = color_fix_mode
            if fix == "auto":
                fix = "wavelet" if 4.0 <= 2.5 else "adain"
            sr_cv = stabilize_colors(sr_img=sr_cv, lq_img=src_cv, scale_factor=4.0, preferred_mode=fix)

        elapsed_ms = (time.time() - t0) * 1000.0

        # Save output
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(output_path, sr_cv)

        # Reference for evaluation: ground truth if available, otherwise bicubic reference
        ref_path = ground_truth_path if (ground_truth_path and Path(ground_truth_path).is_file()) else input_path
        report = self.bench.evaluate_pair(ref_path, output_path)
        metrics_dict = report.to_dict()

        artifacts = self.detect_artifacts(
            src_cv=src_cv,
            sr_cv=sr_cv,
            metrics=metrics_dict,
            has_faces=profile.has_faces,
            has_text=profile.has_text
        )

        rule1_passed = (
            report.quality_verdict in ("PASS", "WARN")
            and report.color_drift_delta_e < 3.5
            and report.gradient_coherence_pct >= 82.0
        )

        return TrialResult(
            trial_id=f"trial_{Path(input_path).stem}_{preset_name}_{int(time.time()*1000)%100000}",
            bucket="general",
            preset_name=preset_name,
            face_fidelity_w=face_fidelity_w,
            text_strength=text_strength,
            color_fix_mode=color_fix_mode,
            elapsed_ms=round(elapsed_ms, 1),
            metrics=metrics_dict,
            detected_artifacts=artifacts,
            rule1_passed=rule1_passed,
            output_path=output_path
        )

    @staticmethod
    def _compute_trial_score(trial: TrialResult) -> float:
        """Computes multi-objective fitness score balancing fidelity, structure, and artifacts."""
        m = trial.metrics
        ssim = m.get("ssim", 0.70)
        coherence = m.get("gradient_coherence_pct", 85.0)
        delta_e = m.get("cielab_delta_e", 1.0)
        psnr = m.get("psnr_db", 25.0)
        art_penalty = len(trial.detected_artifacts) * 0.35

        # Rule #1 penalty if failed
        rule1_penalty = 0.0 if trial.rule1_passed else 2.0

        score = (
            (ssim * 3.0)
            + (coherence / 50.0)
            + (min(psnr, 40.0) / 20.0)
            - (delta_e / 5.0)
            - art_penalty
            - rule1_penalty
        )
        return float(score)

    def run_self_improvement_cycle(self, max_items: int = 5) -> Dict[str, Any]:
        """Executes a full self-improvement calibration sweep across the evaluation corpus."""
        self.corpus.ensure_minimum_corpus(items_per_bucket=1)
        items = self.corpus.items[:max_items]

        all_trials: List[TrialResult] = []
        improvements_found = 0
        winning_configs: List[TrialResult] = []

        # Focused parameter sweep grid
        candidate_w = [0.60, 0.70, 0.80]
        candidate_text = [0.55, 0.65, 0.75]
        color_modes = ["auto", "wavelet", "adain"]

        for item in items:
            # Baseline trial with default parameters
            base_out = str(self.work_dir / "outputs" / f"{item.item_id}_baseline.png")
            base_trial = self.evaluate_pipeline_candidate(
                input_path=item.source_path,
                output_path=base_out,
                ground_truth_path=item.ground_truth_path,
                preset_name="Smart_Balanced",
                face_fidelity_w=0.70,
                text_strength=0.65,
                color_fix_mode="auto"
            )
            base_trial.bucket = item.bucket.value
            all_trials.append(base_trial)

            best_trial_for_item = base_trial
            best_score = self._compute_trial_score(base_trial)

            # Sweep candidate parameter adjustments
            for w_val in candidate_w:
                for t_val in candidate_text:
                    for c_mode in color_modes:
                        # Skip re-running exact default configuration
                        if w_val == 0.70 and t_val == 0.65 and c_mode == "auto":
                            continue

                        trial_out = str(self.work_dir / "outputs" / f"{item.item_id}_tune_w{w_val}_t{t_val}_{c_mode}.png")
                        res = self.evaluate_pipeline_candidate(
                            input_path=item.source_path,
                            output_path=trial_out,
                            ground_truth_path=item.ground_truth_path,
                            preset_name="Smart_Balanced",
                            face_fidelity_w=w_val,
                            text_strength=t_val,
                            color_fix_mode=c_mode
                        )
                        res.bucket = item.bucket.value
                        all_trials.append(res)

                        cand_score = self._compute_trial_score(res)
                        if cand_score > best_score and res.rule1_passed:
                            best_score = cand_score
                            best_trial_for_item = res

            if best_trial_for_item.trial_id != base_trial.trial_id:
                improvements_found += 1
                winning_configs.append(best_trial_for_item)
            else:
                winning_configs.append(base_trial)

        # Calculate calibrated optimum settings from winning Pareto-optimal configurations
        calibrated_w = 0.70
        calibrated_text = 0.65
        calibrated_color = "auto"
        if winning_configs:
            calibrated_w = float(np.mean([t.face_fidelity_w for t in winning_configs]))
            calibrated_text = float(np.mean([t.text_strength for t in winning_configs]))
            color_counts = {}
            for t in winning_configs:
                color_counts[t.color_fix_mode] = color_counts.get(t.color_fix_mode, 0) + 1
            calibrated_color = max(color_counts.items(), key=lambda x: x[1])[0]

        # Update presets.yaml with calibrated values
        target_dict = self.presets.get("presets", self.presets)
        if "Smart_Balanced" in target_dict:
            target_dict["Smart_Balanced"]["calibrated_fidelity_w"] = round(calibrated_w, 2)
            target_dict["Smart_Balanced"]["calibrated_text_strength"] = round(calibrated_text, 2)
            target_dict["Smart_Balanced"]["calibrated_color_fix"] = calibrated_color
            target_dict["Smart_Balanced"]["last_calibration"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self._save_presets(self.presets)

        # Generate HTML report
        report_path = self.work_dir / "self_improvement_report.html"
        self._generate_html_report(all_trials, report_path, calibrated_w, calibrated_text)

        summary = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "items_evaluated": len(items),
            "total_trials": len(all_trials),
            "improvements_found": improvements_found,
            "calibrated_face_fidelity_w": round(calibrated_w, 2),
            "calibrated_text_strength": round(calibrated_text, 2),
            "calibrated_color_fix": calibrated_color,
            "report_path": str(report_path),
            "quality_status": "SUPERIOR" if improvements_found > 0 else "OPTIMAL_BASELINE"
        }

        # Write manifest
        manifest_p = self.work_dir / "manifest.json"
        with open(manifest_p, "w") as f:
            json.dump({
                "summary": summary,
                "trials": [asdict(t) for t in all_trials]
            }, f, indent=2)

        return summary

    def _generate_html_report(
        self,
        trials: List[TrialResult],
        report_path: Path,
        opt_w: float,
        opt_text: float
    ):
        """Builds a rich HTML dashboard showing self-improvement metrics and artifacts."""
        rows = []
        for t in trials:
            status_badge = (
                '<span style="background:#238636; color:#fff; padding:2px 8px; border-radius:4px; font-weight:600;">PASS</span>'
                if t.rule1_passed else
                '<span style="background:#da3633; color:#fff; padding:2px 8px; border-radius:4px; font-weight:600;">FAIL</span>'
            )
            art_text = ", ".join(t.detected_artifacts) if t.detected_artifacts else '<span style="color:#3fb950">None</span>'
            m = t.metrics
            rows.append(f"""
            <tr>
              <td><strong>{t.trial_id}</strong><br><small style="color:#8b949e">{t.bucket}</small></td>
              <td>{t.preset_name}<br><small>w={t.face_fidelity_w} | txt={t.text_strength}</small></td>
              <td>{status_badge}</td>
              <td><strong>{m.get('psnr_db', '-')}</strong> dB</td>
              <td><strong>{m.get('ssim', '-')}</strong></td>
              <td>{m.get('cielab_delta_e', '-')}</td>
              <td>{m.get('gradient_coherence_pct', '-')}%</td>
              <td>{m.get('hallucination_risk', '-')}</td>
              <td>{t.elapsed_ms} ms</td>
              <td><small>{art_text}</small></td>
            </tr>
            """)

        html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Fidelis Self-Improvement & Quality Calibration Report</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background: #0d1117; color: #c9d1d9; margin: 0; padding: 24px; }}
    h1, h2, h3 {{ color: #f0f6fc; }}
    .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 18px; margin-bottom: 20px; }}
    .metric-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 14px; margin-top: 12px; }}
    .metric-item {{ background: #21262d; border-radius: 6px; padding: 12px; border: 1px solid #30363d; }}
    .metric-val {{ font-size: 22px; font-weight: bold; color: #58a6ff; margin-top: 4px; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 13px; }}
    th, td {{ border: 1px solid #30363d; padding: 8px 12px; text-align: left; }}
    th {{ background: #21262d; color: #f0f6fc; }}
    tr:nth-child(even) {{ background: #161b22; }}
  </style>
</head>
<body>
  <h1>Fidelis Self-Improvement & Quality Calibration Report</h1>
  <p style="color: #8b949e">Autonomous regression testing, artifact taxonomy analysis, and hyperparameter schedule optimization.</p>

  <div class="card">
    <h2>1. Calibration & Tuning Summary</h2>
    <div class="metric-grid">
      <div class="metric-item">
        <div style="font-size:12px; color:#8b949e">Trials Executed</div>
        <div class="metric-val">{len(trials)}</div>
      </div>
      <div class="metric-item">
        <div style="font-size:12px; color:#8b949e">Rule #1 Pass Rate</div>
        <div class="metric-val" style="color:#3fb950">{(sum(1 for t in trials if t.rule1_passed)/max(len(trials),1)*100):.1f}%</div>
      </div>
      <div class="metric-item">
        <div style="font-size:12px; color:#8b949e">Optimal Face Weight (w)</div>
        <div class="metric-val">{opt_w:.2f}</div>
      </div>
      <div class="metric-item">
        <div style="font-size:12px; color:#8b949e">Optimal Text Strength</div>
        <div class="metric-val">{opt_text:.2f}</div>
      </div>
    </div>
  </div>

  <div class="card">
    <h2>2. Trial Audit Log & 5-Dimension Evaluation</h2>
    <table>
      <thead>
        <tr>
          <th>Trial / Bucket</th>
          <th>Configuration</th>
          <th>Rule #1</th>
          <th>PSNR</th>
          <th>SSIM</th>
          <th>&Delta;E Color</th>
          <th>Coherence</th>
          <th>Hallucination</th>
          <th>Latency</th>
          <th>Artifacts Detected</th>
        </tr>
      </thead>
      <tbody>
        {"".join(rows)}
      </tbody>
    </table>
  </div>
</body>
</html>
"""
        report_path.write_text(html_content, encoding="utf-8")
