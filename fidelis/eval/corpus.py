"""Evaluation Corpus Manager for Fidelis.

Organizes benchmark images into the 11 orthogonal test buckets defined in the
Fidelis Flagship Blueprint:
1. Clean Photography
2. Low-Resolution Phone/Web
3. JPEG / Social Media Compression
4. Portraits and Group Photos (Skin / Face ID)
5. Fashion / Apparel / Fabric Weave
6. Architecture & Repeated Geometry
7. Typography / Screenshots / UI (Glyphs)
8. Illustration / Anime / Vector Art
9. Old / Scanned / Archival Photography
10. Low-Light / High-Noise Sensors
11. Severe Degradation (Creative Stress Test)
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import cv2

from fidelis.data.degradation import DegradationGenerator


class TestBucket(str, Enum):
    CLEAN_PHOTO = "clean_photography"
    LOW_RES_WEB = "low_res_web"
    JPEG_COMPRESSION = "jpeg_compression"
    PORTRAIT_SKIN = "portrait_skin"
    FASHION_FABRIC = "fashion_fabric"
    ARCHITECTURE = "architecture"
    TYPOGRAPHY_UI = "typography_ui"
    ILLUSTRATION = "illustration"
    ARCHIVAL_SCANNED = "archival_scanned"
    LOW_LIGHT_NOISE = "low_light_noise"
    SEVERE_DEGRADATION = "severe_degradation"


@dataclass
class CorpusItem:
    item_id: str
    bucket: TestBucket
    source_path: str
    ground_truth_path: str | None = None
    width: int = 0
    height: int = 0
    is_paired: bool = False
    metadata: dict = field(default_factory=dict)


class EvaluationCorpus:
    """Manages local and synthetic evaluation test sets across the 11 buckets."""

    def __init__(self, corpus_dir: Path | None = None):
        self.corpus_dir = corpus_dir or (Path(__file__).resolve().parent.parent.parent / "experiments" / "eval_corpus")
        self.corpus_dir.mkdir(parents=True, exist_ok=True)
        self.items: list[CorpusItem] = []
        self._discover_items()

    def _discover_items(self):
        """Scans the repository for available test assets and categorizes them."""
        repo_root = Path(__file__).resolve().parent.parent.parent
        fixtures_dir = repo_root / "tests" / "fixtures"
        crops_dir = repo_root / "experiments" / "eval_crops"

        discovered = []

        # Map known fixture items
        mapping = {
            "portrait_skin.png": TestBucket.PORTRAIT_SKIN,
            "portrait_skin_real.png": TestBucket.PORTRAIT_SKIN,
            "user_test_blonde.png": TestBucket.PORTRAIT_SKIN,
            "user_test_darkhair.png": TestBucket.PORTRAIT_SKIN,
            "fabric_weave.png": TestBucket.FASHION_FABRIC,
            "fashion_fabric_real.png": TestBucket.FASHION_FABRIC,
            "product_hard_edges.png": TestBucket.ARCHITECTURE,
            "product_edges_real.png": TestBucket.ARCHITECTURE,
        }

        scan_dirs = [fixtures_dir, crops_dir, self.corpus_dir]
        seen_paths = set()

        for s_dir in scan_dirs:
            if not s_dir.is_dir():
                continue
            for img_p in s_dir.glob("*.png"):
                if img_p in seen_paths:
                    continue
                seen_paths.add(img_p)

                name = img_p.name
                bucket = mapping.get(name)

                # Heuristic categorization if not in fixed mapping
                if bucket is None:
                    n_lower = name.lower()
                    if "face" in n_lower or "portrait" in n_lower or "person" in n_lower:
                        bucket = TestBucket.PORTRAIT_SKIN
                    elif "fabric" in n_lower or "weave" in n_lower or "cloth" in n_lower:
                        bucket = TestBucket.FASHION_FABRIC
                    elif "text" in n_lower or "logo" in n_lower or "ui" in n_lower:
                        bucket = TestBucket.TYPOGRAPHY_UI
                    elif "archival" in n_lower or "scan" in n_lower or "bw" in n_lower:
                        bucket = TestBucket.ARCHIVAL_SCANNED
                    elif "noise" in n_lower or "night" in n_lower or "lowlight" in n_lower:
                        bucket = TestBucket.LOW_LIGHT_NOISE
                    else:
                        bucket = TestBucket.CLEAN_PHOTO

                im = cv2.imread(str(img_p))
                if im is not None:
                    h, w = im.shape[:2]
                    discovered.append(
                        CorpusItem(
                            item_id=img_p.stem,
                            bucket=bucket,
                            source_path=str(img_p),
                            width=w,
                            height=h,
                            is_paired=False
                        )
                    )

        self.items = discovered

    def ensure_minimum_corpus(self, items_per_bucket: int = 1) -> list[CorpusItem]:
        """Add an aligned 4x synthetic pair to each bucket below the threshold.

        Small inputs remain available as unpaired samples.
        """
        scale = 4
        # The first- and second-order degradations use a 16-pixel LR floor.
        min_seed_side = 16 * scale
        for item in self.items:
            if item.is_paired:
                continue
            seed_cv = cv2.imread(item.source_path)
            if seed_cv is None or min(seed_cv.shape[:2]) < min_seed_side:
                continue
            height, width = seed_cv.shape[:2]
            lr_height, lr_width = height // scale, width // scale
            reference = seed_cv[:lr_height * scale, :lr_width * scale]
            break
        else:
            return self.items

        gen = DegradationGenerator(scale=scale, seed=42)
        for bucket in TestBucket:
            count = sum(1 for item in self.items if item.bucket == bucket)
            if count < items_per_bucket:
                bucket_dir = self.corpus_dir / bucket.value
                bucket_dir.mkdir(parents=True, exist_ok=True)

                out_lr = bucket_dir / "syn_lr.png"
                out_hr = bucket_dir / "syn_hr.png"

                # Tailor degradation to bucket intent
                degraded = reference.copy()
                if bucket == TestBucket.JPEG_COMPRESSION:
                    degraded = gen.random_compression(degraded, quality_range=(20, 45))
                    degraded = gen.random_resize(degraded, lr_width, lr_height)
                elif bucket == TestBucket.LOW_LIGHT_NOISE:
                    degraded = gen.random_noise(degraded, gaussian_sigma_range=(15, 30))
                    degraded = gen.random_resize(degraded, lr_width, lr_height)
                elif bucket == TestBucket.SEVERE_DEGRADATION:
                    degraded = gen.apply_second_order(degraded)
                else:
                    degraded = gen.apply_first_order(degraded)

                cv2.imwrite(str(out_lr), degraded)
                cv2.imwrite(str(out_hr), reference)

                h, w = degraded.shape[:2]
                new_item = CorpusItem(
                    item_id=f"syn_{bucket.value}",
                    bucket=bucket,
                    source_path=str(out_lr),
                    ground_truth_path=str(out_hr),
                    width=w,
                    height=h,
                    is_paired=True,
                    metadata={"synthetic": True}
                )
                self.items.append(new_item)

        return self.items

    def get_bucket_items(self, bucket: TestBucket) -> list[CorpusItem]:
        return [it for it in self.items if it.bucket == bucket]

    def list_summary(self) -> dict[str, int]:
        summary = {}
        for b in TestBucket:
            summary[b.value] = sum(1 for it in self.items if it.bucket == b)
        return summary
