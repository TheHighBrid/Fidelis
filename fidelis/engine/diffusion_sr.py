"""Production Presets and Diffusion Super-Resolution Engine for Fidelis.

Translates high-level user conditioning (Creativity, Resemblance) into
formal EDM diffusion sampling schedules, Linear CFG, and stochastic churn.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional
import yaml

CONFIG_PATH = Path(__file__).resolve().parent.parent / "configs/presets.yaml"


@dataclass
class DiffusionSchedule:
    preset_name: str
    steps: int
    guidance_scale: float
    linear_cfg: bool
    s_noise: float
    s_churn: float
    resemblance_weight: float
    color_correction: str
    positive_prompt: str
    negative_prompt: str


class DiffusionPresetsEngine:
    """Loads and modulates production diffusion schedules for Fidelis."""

    def __init__(self, config_file: Optional[Path] = None):
        cfg_path = config_file or CONFIG_PATH
        if cfg_path.is_file():
            with open(cfg_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                self.presets = data.get("presets", {})
        else:
            self.presets = {}

    def get_preset(self, name: str) -> Dict:
        return self.presets.get(name, self.presets.get("Smart_Balanced", {}))

    def build_schedule(
        self,
        preset_name: str = "Smart_Balanced",
        creativity: float = 0.50,
        resemblance: float = 0.70
    ) -> DiffusionSchedule:
        """Map user UI sliders (Creativity: 0.0-1.0, Resemblance: 0.0-1.0) to diffusion parameters."""
        raw = self.get_preset(preset_name)

        base_steps = raw.get("diffusion_steps", 1)
        base_guidance = raw.get("guidance_scale", 1.0)
        linear_cfg = raw.get("linear_cfg", False)
        s_noise = raw.get("s_noise", 1.0)
        s_churn = raw.get("s_churn", 0.0)

        # In multi-step presets, Creativity dynamically scales steps and guidance
        if base_steps > 1:
            steps = int(40 + creativity * 60)  # 40 to 100 steps
            guidance = 7.0 + creativity * 5.0  # 7.0 to 12.0
        else:
            steps = 1
            guidance = 1.0

        # Resemblance modulates ZeroSFT / ControlNet tile conditioning weight
        resemblance_weight = max(0.2, min(1.0, resemblance))

        return DiffusionSchedule(
            preset_name=preset_name,
            steps=steps,
            guidance_scale=round(guidance, 2),
            linear_cfg=linear_cfg,
            s_noise=s_noise,
            s_churn=s_churn,
            resemblance_weight=round(resemblance_weight, 2),
            color_correction=raw.get("color_correction", "adain"),
            positive_prompt=raw.get("positive_prompt", ""),
            negative_prompt=raw.get("negative_prompt", "")
        )
