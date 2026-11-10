"""Rights, hash, split, and critical-ROI manifest validator for F12-A / MEL-79.

Distinguishes cleared 60-case benchmark corpus slots (30 calibration / 30 held-out
across five categories) from tracked regression fixtures/crops, failing closed on
uncleared rights, missing assets, split leakage, path traversal, or checksum mismatch.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

SCHEMA_VERSION = 1

CORPUS_CATEGORIES: Dict[str, Dict[str, Any]] = {
    "portraits": {
        "label": "Portraits (diverse skin tones & lighting)",
        "target_count": 12,
        "calibration_count": 6,
        "held_out_count": 6,
    },
    "apparel_model": {
        "label": "Model + apparel frames",
        "target_count": 12,
        "calibration_count": 6,
        "held_out_count": 6,
    },
    "textiles": {
        "label": "Textiles & macro weaves",
        "target_count": 12,
        "calibration_count": 6,
        "held_out_count": 6,
    },
    "macros": {
        "label": "Hardware, zipper, logo & seam macros",
        "target_count": 12,
        "calibration_count": 6,
        "held_out_count": 6,
    },
    "packshot_edge": {
        "label": "Packshots, background restraint, alpha & low-light edge cases",
        "target_count": 12,
        "calibration_count": 6,
        "held_out_count": 6,
    },
}

VALID_SPLITS = ("calibration", "held_out")
VALID_AVAILABILITY = ("available", "missing", "excluded")
VALID_ROI_TYPES = (
    "identity_landmark",
    "skin_zone",
    "hair_edge",
    "garment_fit",
    "textile_weave",
    "logo",
    "text",
    "zipper",
    "stitch",
    "hardware",
    "care_label",
    "background_edge",
    "alpha_edge",
    "shadow_rolloff",
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

_CATEGORY_PLANNED_SLOTS: Dict[str, List[Tuple[str, str, bool, List[str], List[Dict[str, Any]]]]] = {
    "portraits": [
        ("por_deep_skin_studio", "Studio portrait, deep skin tone, natural pores and catchlights", True, [], [{"roi_id": "eyes_mouth", "label": "Eyes, iris catchlights, teeth", "roi_type": "identity_landmark", "must_lock_base": True, "bbox_norm": None}]),
        ("por_medium_skin_daylight", "Daylight editorial portrait, medium skin tone and flyaway hair", True, [], [{"roi_id": "hairline", "label": "Soft hairline and stray strands", "roi_type": "hair_edge", "must_lock_base": False, "bbox_norm": None}]),
        ("por_fair_freckles_closeup", "Close-up portrait, fair skin tone with freckles and moles", True, [], [{"roi_id": "facial_marks", "label": "Moles and fine cheek texture", "roi_type": "identity_landmark", "must_lock_base": True, "bbox_norm": None}]),
        ("por_olive_shallow_dof", "Editorial portrait with shallow depth-of-field bokeh behind head", True, [], [{"roi_id": "bokeh_bg", "label": "Out-of-focus background gradient", "roi_type": "background_edge", "must_lock_base": True, "bbox_norm": None}]),
        ("por_elderly_character_lines", "Mature subject portrait with periorbital creases and beard stubble", True, [], [{"roi_id": "eye_lines", "label": "Preserved expression lines and gaze", "roi_type": "identity_landmark", "must_lock_base": True, "bbox_norm": None}]),
        ("por_warm_mixed_tungsten", "Warm indoor tungsten portrait retaining subtle amber cast", True, [], [{"roi_id": "skin_tone", "label": "Cheek skin reflectance without cool shift", "roi_type": "skin_zone", "must_lock_base": False, "bbox_norm": None}]),
        ("por_held_rich_melanin_rim", "Rim-lit portrait with specular forehead highlights and braids", True, [], [{"roi_id": "eyes_landmarks", "label": "Facial landmarks and catchlights", "roi_type": "identity_landmark", "must_lock_base": True, "bbox_norm": None}]),
        ("por_held_east_asian_softbox", "Softbox studio beauty crop, natural eyelid crease and lip grain", True, [], [{"roi_id": "eyelid_lips", "label": "Eyelids, lashes and lip texture", "roi_type": "identity_landmark", "must_lock_base": True, "bbox_norm": None}]),
        ("por_held_south_asian_outdoor", "Outdoor shade portrait with jewelry earrings and veil edge", True, [], [{"roi_id": "earring_metal", "label": "Gold earring prongs and stone reflections", "roi_type": "hardware", "must_lock_base": True, "bbox_norm": None}]),
        ("por_held_glasses_reflection", "Eyewear portrait testing bridge geometry and cornea reflections", True, [], [{"roi_id": "eyewear_frame", "label": "Frame hinges and temple inscription", "roi_type": "hardware", "must_lock_base": True, "bbox_norm": None}]),
        ("por_held_group_dual_focus", "Two-subject fashion frame with near/far focal plane drop-off", True, [], [{"roi_id": "background_subject", "label": "Defocused secondary face consistency", "roi_type": "identity_landmark", "must_lock_base": True, "bbox_norm": None}]),
        ("por_held_high_iso_backstage", "Backstage higher-ISO candid portrait without waxy skin smoothing", True, [], [{"roi_id": "skin_microtexture", "label": "Natural cheek grain vs smoothing", "roi_type": "skin_zone", "must_lock_base": False, "bbox_norm": None}]),
    ],
    "apparel_model": [
        ("app_tailored_wool_blazer", "Editorial lookbook wool blazer with crisp lapel roll and cuff buttons", True, [], [{"roi_id": "lapel_stitch", "label": "Pick-stitch lapel and horn buttons", "roi_type": "stitch", "must_lock_base": True, "bbox_norm": None}]),
        ("app_silk_slip_drape", "Model wearing bias-cut silk dress on seamless studio cyc", True, [], [{"roi_id": "face_id", "label": "Model facial identity region", "roi_type": "identity_landmark", "must_lock_base": True, "bbox_norm": None}]),
        ("app_graphic_tee_screenprint", "On-model heavyweight cotton tee with multi-line chest typography", True, ["MELATO MILANO"], [{"roi_id": "chest_print", "label": "Printed chest typography", "roi_type": "text", "must_lock_base": True, "bbox_norm": None}]),
        ("app_biker_jacket_hardware", "Model in cropped leather jacket with diagonal zip and snap studs", True, [], [{"roi_id": "asym_zip", "label": "Diagonal metal zipper track", "roi_type": "zipper", "must_lock_base": True, "bbox_norm": None}]),
        ("app_knit_cardigan_collar", "Half-body knit cardigan frame testing buttonholes and collar rib", True, [], [{"roi_id": "placket_buttons", "label": "Ribbed placket seams and buttons", "roi_type": "stitch", "must_lock_base": True, "bbox_norm": None}]),
        ("app_sheer_organza_overlay", "Layered translucent organza sleeve over skin forearm", True, [], [{"roi_id": "sheer_sleeve", "label": "Transparent sleeve weave over arm", "roi_type": "hair_edge", "must_lock_base": False, "bbox_norm": None}]),
        ("app_held_trench_epaulette", "Gabardine trench coat full lookbook frame with belt buckle and logo", True, ["MELATO"], [{"roi_id": "buckle_logo", "label": "Woven label and horn belt buckle", "roi_type": "logo", "must_lock_base": True, "bbox_norm": None}]),
        ("app_held_denim_selvedge", "Model denim jacket with contrast bar-tacks and shank buttons", True, [], [{"roi_id": "metal_shanks", "label": "Debossed shank buttons and pocket tacks", "roi_type": "hardware", "must_lock_base": True, "bbox_norm": None}]),
        ("app_held_pleated_skirt", "Fine accordion-pleated skirt testing silhouette and pleat geometry", True, [], [{"roi_id": "pleat_edges", "label": "Repeated knife-pleat folds", "roi_type": "garment_fit", "must_lock_base": True, "bbox_norm": None}]),
        ("app_held_athleisure_seam", "Flatlock technical knit seams and reflective chest mark on model", True, ["ATELIER"], [{"roi_id": "reflective_mark", "label": "Reflective transfer logo", "roi_type": "logo", "must_lock_base": True, "bbox_norm": None}]),
        ("app_held_sequin_evening", "Beaded/sequin bodice requiring specular glint fidelity without bokeh invention", True, [], [{"roi_id": "sequin_grid", "label": "Aligned sequin attachment grid", "roi_type": "hardware", "must_lock_base": True, "bbox_norm": None}]),
        ("app_held_herringbone_coat", "Long herringbone overcoat testing coarse weave orientation across torso", True, [], [{"roi_id": "chevron_weave", "label": "Continuous herringbone directional weave", "roi_type": "textile_weave", "must_lock_base": False, "bbox_norm": None}]),
    ],
    "textiles": [
        ("tex_charmeuse_satin", "Ivory charmeuse satin bias drape with subtle highlight roll-off", False, [], [{"roi_id": "satin_sheen", "label": "Specular fold highlight without plasticizing", "roi_type": "textile_weave", "must_lock_base": False, "bbox_norm": None}]),
        ("tex_cashmere_cable_knit", "Heathered oatmeal cashmere cable-knit swatch", False, [], [{"roi_id": "yarn_twist", "label": "Ply twist and loft halo fibers", "roi_type": "textile_weave", "must_lock_base": False, "bbox_norm": None}]),
        ("tex_cotton_twill_chino", "Sand-dyed 2/1 cotton twill weave macro crop", False, [], [{"roi_id": "diagonal_wale", "label": "Diagonal twill wale continuity", "roi_type": "textile_weave", "must_lock_base": False, "bbox_norm": None}]),
        ("tex_full_grain_leather", "Aniline black calfskin leather panel showing irregular natural grain", False, [], [{"roi_id": "grain_irregularity", "label": "Non-repeating pebble pore structure", "roi_type": "textile_weave", "must_lock_base": False, "bbox_norm": None}]),
        ("tex_raw_indigo_denim", "14oz raw indigo denim warp/weft slub texture", False, [], [{"roi_id": "slub_warp", "label": "Indigo warp and ecru weft crossings", "roi_type": "textile_weave", "must_lock_base": False, "bbox_norm": None}]),
        ("tex_boucle_tweed", "Multicolour boucle tweed fabric testing yarn color fidelity", False, [], [{"roi_id": "tweed_dye", "label": "Interwoven coloured slub yarns", "roi_type": "textile_weave", "must_lock_base": False, "bbox_norm": None}]),
        ("tex_held_linen_slub", "Unbleached heavyweight linen swatch with organic flax slubs", False, [], [{"roi_id": "flax_fibers", "label": "Irregular warp thickness transitions", "roi_type": "textile_weave", "must_lock_base": False, "bbox_norm": None}]),
        ("tex_held_suede_nap", "Deep espresso goat suede testing velvety short nap direction", False, [], [{"roi_id": "suede_pile", "label": "Fine directional brushed nap", "roi_type": "textile_weave", "must_lock_base": False, "bbox_norm": None}]),
        ("tex_held_jacquard_brocade", "Tonal floral silk jacquard testing repeating motif registration", False, [], [{"roi_id": "jacquard_motif", "label": "Woven pattern edges vs background satin", "roi_type": "stitch", "must_lock_base": True, "bbox_norm": None}]),
        ("tex_held_merino_rib", "Fine 2x2 merino jersey rib stretch transition", False, [], [{"roi_id": "rib_columns", "label": "Wale column parallelism", "roi_type": "textile_weave", "must_lock_base": False, "bbox_norm": None}]),
        ("tex_held_chantilly_lace", "Openwork Chantilly lace net over contrasting backing", False, [], [{"roi_id": "hex_mesh", "label": "Hexagonal tulle net holes without infill", "roi_type": "hardware", "must_lock_base": True, "bbox_norm": None}]),
        ("tex_held_technical_ripstop", "Matte nylon micro-ripstop grid swatch", False, [], [{"roi_id": "ripstop_grid", "label": "Raised crosshatch reinforcement grid", "roi_type": "textile_weave", "must_lock_base": True, "bbox_norm": None}]),
    ],
    "macros": [
        ("mac_two_way_brass_zip", "Brushed brass zipper teeth and slider pull tab macro", False, ["YKK 5"], [{"roi_id": "zip_teeth", "label": "Interlocking teeth spacing and pull stamp", "roi_type": "zipper", "must_lock_base": True, "bbox_norm": None}]),
        ("mac_woven_neck_label", "Satin neck label sewn with folded miter corners", False, ["MADE IN ITALY"], [{"roi_id": "woven_brand", "label": "Micro-woven serif lettering", "roi_type": "logo", "must_lock_base": True, "bbox_norm": None}]),
        ("mac_debossed_leather_stamp", "Blind-debossed leather creed with gold foil micro-type", False, ["MILANO 1984"], [{"roi_id": "foil_stamp", "label": "Foil serif character geometry", "roi_type": "logo", "must_lock_base": True, "bbox_norm": None}]),
        ("mac_twin_needle_topstitch", "Double-needle felled seam with exact stitch-per-inch count", False, [], [{"roi_id": "topstitch_holes", "label": "Needle punctures and twisted thread", "roi_type": "stitch", "must_lock_base": True, "bbox_norm": None}]),
        ("mac_keyhole_buttonhole", "Tailored gimp-reinforced keyhole buttonhole and corozo button", False, [], [{"roi_id": "purl_stitch", "label": "Dense gimp buttonhole bartack", "roi_type": "stitch", "must_lock_base": True, "bbox_norm": None}]),
        ("mac_engraved_clasp_bevel", "Palladium-plated handbag turn-lock clasp with laser engraving", False, ["FIDELIS"], [{"roi_id": "bevel_engraving", "label": "Chamfered edge reflection and engraving", "roi_type": "hardware", "must_lock_base": True, "bbox_norm": None}]),
        ("mac_held_care_label_symbols", "Printed satin care tag with laundry icons and composition text", False, ["100% SILK"], [{"roi_id": "care_text", "label": "Fine care icons and small percentages", "roi_type": "care_label", "must_lock_base": True, "bbox_norm": None}]),
        ("mac_held_concealed_nylon_zip", "Invisible coil zipper closed seam in silk crepe", False, [], [{"roi_id": "coil_line", "label": "Seam kissing edge along invisible track", "roi_type": "zipper", "must_lock_base": True, "bbox_norm": None}]),
        ("mac_held_chain_strap_links", "Interlinked curb metal strap with edge-painted leather weaving", False, [], [{"roi_id": "chain_links", "label": "Specular link bevels and paint edge", "roi_type": "hardware", "must_lock_base": True, "bbox_norm": None}]),
        ("mac_held_chain_embroidery", "Monogram chain-stitch embroidery on heavyweight fleece", False, ["MLT"], [{"roi_id": "loop_stitch", "label": "Individual chain embroidery loops", "roi_type": "stitch", "must_lock_base": True, "bbox_norm": None}]),
        ("mac_held_shoe_welt_stitch", "Goodyear storm welt perimeter stitching on calfskin boot", False, [], [{"roi_id": "welt_pitch", "label": "Sole welt stitch pitch and burnished edge", "roi_type": "stitch", "must_lock_base": True, "bbox_norm": None}]),
        ("mac_held_watch_buckle_pin", "Brushed steel tang buckle and leather keeper stitching", False, ["SWISS"], [{"roi_id": "steel_brush", "label": "Brushed satin grain and engraved back", "roi_type": "hardware", "must_lock_base": True, "bbox_norm": None}]),
    ],
    "packshot_edge": [
        ("pak_white_cyc_handbag", "Ecommerce handbag packshot on pure white backdrop with contact shadow", False, [], [{"roi_id": "white_backdrop", "label": "Pure neutral backdrop restraint", "roi_type": "background_edge", "must_lock_base": True, "bbox_norm": None}]),
        ("pak_black_studio_watch", "Watch product on intentional deep black backdrop (non-black-tile test)", False, ["CHRONO"], [{"roi_id": "black_bg", "label": "Legitimate dark studio backdrop", "roi_type": "background_edge", "must_lock_base": True, "bbox_norm": None}]),
        ("pak_alpha_cutout_sneaker", "Cutout product silhouette testing crisp perimeter edge preservation", False, [], [{"roi_id": "silhouette_edge", "label": "Clean cutout perimeter without halo", "roi_type": "alpha_edge", "must_lock_base": True, "bbox_norm": None}]),
        ("pak_low_light_evening_bag", "Low-light moody still life testing shadow noise vs banding", False, [], [{"roi_id": "shadow_rolloff", "label": "Smooth dark shadow tonal gradient", "roi_type": "shadow_rolloff", "must_lock_base": True, "bbox_norm": None}]),
        ("pak_clear_perfume_flacon", "Transparent glass bottle over graded backdrop with embossed label", False, ["EXTRAIT"], [{"roi_id": "flacon_type", "label": "Frosted bottle typography and glass caustic", "roi_type": "text", "must_lock_base": True, "bbox_norm": None}]),
        ("pak_matte_box_packaging", "Luxury rigid paper box testing subtle spot-UV foil micro-type", False, ["ARCHIVE EDITION"], [{"roi_id": "box_foil", "label": "Spot-UV paper typography and crease", "roi_type": "text", "must_lock_base": True, "bbox_norm": None}]),
        ("pak_held_white_shirt_shadow", "Ghost-mannequin poplin shirt on seamless grey backdrop", False, [], [{"roi_id": "collar_edge", "label": "Crisp collar edge vs background shadow", "roi_type": "background_edge", "must_lock_base": True, "bbox_norm": None}]),
        ("pak_held_dark_velvet_packshot", "Midnight velvet pump on charcoal sweep testing shadow separation", False, [], [{"roi_id": "velvet_shadow", "label": "Velvet edge separation without crushed halo", "roi_type": "shadow_rolloff", "must_lock_base": True, "bbox_norm": None}]),
        ("pak_held_tinted_sunglasses", "Semi-transparent acetate sunglasses over warm paper backdrop", False, ["UV400"], [{"roi_id": "lens_tint", "label": "Semi-transparent lens transmission hue", "roi_type": "background_edge", "must_lock_base": True, "bbox_norm": None}]),
        ("pak_held_sunglass_case_grain", "Matte pebbled case testing edge-paint bevel and blind stamp", False, ["MELATO"], [{"roi_id": "case_stamp", "label": "Debossed case brand mark", "roi_type": "logo", "must_lock_base": True, "bbox_norm": None}]),
        ("pak_held_high_key_jewelry", "High-key platinum ring over bright gradient shadow", False, ["Pt950"], [{"roi_id": "hallmark", "label": "Inner band hallmark engraving", "roi_type": "text", "must_lock_base": True, "bbox_norm": None}]),
        ("pak_held_archival_print_scan", "Moderately noisy flat-lay editorial lookbook tear-sheet scan", False, ["AUTUMN / WINTER"], [{"roi_id": "tear_headline", "label": "Printed editorial caption and halftone dots", "roi_type": "text", "must_lock_base": True, "bbox_norm": None}]),
    ],
}


class ManifestValidationError(ValueError):
    """Raised when a corpus manifest violates rights, schema, split, or hash contracts."""


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _safe_repo_path(repo_root: Path, relative_path: str) -> Path:
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise ManifestValidationError("relative_path must be a non-empty string")
    rel = Path(relative_path)
    if rel.is_absolute():
        raise ManifestValidationError(f"Path must be repository-relative, got {relative_path}")
    resolved_root = repo_root.resolve()
    resolved = (resolved_root / rel).resolve()
    if not resolved.is_relative_to(resolved_root):
        raise ManifestValidationError(f"Path escapes repository root: {relative_path}")
    return resolved


def _verify_image_file(path: Path, expected_sha256: str, expected_w: int, expected_h: int) -> None:
    if not path.is_file():
        raise ManifestValidationError(f"Referenced image file is missing on disk: {path}")
    actual_sha = sha256_file(path)
    if actual_sha != expected_sha256:
        raise ManifestValidationError(
            f"SHA-256 mismatch for {path.name}: expected {expected_sha256}, found {actual_sha}"
        )
    try:
        from PIL import Image
    except ImportError:
        return
    with Image.open(path) as im:
        if im.size != (expected_w, expected_h):
            raise ManifestValidationError(
                f"Dimension mismatch for {path.name}: expected {expected_w}x{expected_h}, found {im.width}x{im.height}"
            )


def measure_regression_assets(repo_root: Path) -> List[Dict[str, Any]]:
    """Measure SHA-256, dimensions, and mode for tracked fixture/crop assets."""
    from PIL import Image

    tracked_paths: List[Tuple[str, str]] = []
    for p in sorted((repo_root / "tests" / "fixtures").glob("*.png")):
        tracked_paths.append((p.relative_to(repo_root).as_posix(), "synthetic_test_fixture"))
    for p in sorted((repo_root / "experiments" / "eval_crops").glob("*.png")):
        tracked_paths.append((p.relative_to(repo_root).as_posix(), "internal_eval_crop"))

    records: List[Dict[str, Any]] = []
    for rel_path, origin in tracked_paths:
        abs_path = repo_root / rel_path
        with Image.open(abs_path) as im:
            records.append(
                {
                    "asset_id": abs_path.stem,
                    "relative_path": rel_path,
                    "role": "regression_fixture_only",
                    "counts_toward_60_case_corpus": False,
                    "origin": origin,
                    "rights_cleared": False,
                    "rights_note": "Regression/fixture asset only; not cleared as held-out/calibration Studio benchmark corpus.",
                    "sha256": sha256_file(abs_path),
                    "width": im.width,
                    "height": im.height,
                    "mode": im.mode,
                    "format": im.format,
                    "bytes": abs_path.stat().st_size,
                }
            )
    return records


def build_template_manifest(repo_root: Optional[Path] = None) -> Dict[str, Any]:
    """Generate the frozen 60-slot benchmark manifest (30 calibration / 30 held-out)."""
    cases: List[Dict[str, Any]] = []
    for category, slots in _CATEGORY_PLANNED_SLOTS.items():
        if len(slots) != CORPUS_CATEGORIES[category]["target_count"]:
            raise ManifestValidationError(f"Internal template count mismatch for {category}")
        cal_target = CORPUS_CATEGORIES[category]["calibration_count"]
        for index, (case_id, subject, release_req, known_text, rois) in enumerate(slots):
            split = "calibration" if index < cal_target else "held_out"
            cases.append(
                {
                    "case_id": case_id,
                    "category": category,
                    "split": split,
                    "availability": "missing",
                    "expected_subject": subject,
                    "rights": {
                        "cleared": False,
                        "permission_basis": None,
                        "license_id": None,
                        "model_release_required": release_req,
                        "model_release_verified": False,
                        "notes": "Pending licensed/consented source acquisition.",
                    },
                    "source": {
                        "relative_path": None,
                        "sha256": None,
                        "width": None,
                        "height": None,
                        "color_space": None,
                        "bit_depth": None,
                        "has_alpha": None,
                    },
                    "target": {
                        "scale": None,
                        "expected_width": None,
                        "expected_height": None,
                    },
                    "known_text": list(known_text),
                    "critical_rois": [dict(roi) for roi in rois],
                }
            )

    regression_assets = measure_regression_assets(repo_root) if repo_root is not None else []
    return {
        "schema_version": SCHEMA_VERSION,
        "manifest_purpose": "Frozen 60-case calibration/held-out Studio corpus inventory (F12-A / MEL-79).",
        "split_frozen": True,
        "split_policy": {
            "total_cases": 60,
            "calibration": 30,
            "held_out": 30,
            "per_category": 12,
            "per_category_split": 6,
            "note": "Split assignments and slot definitions are frozen before tuning; missing assets cannot be substituted with regression crops.",
        },
        "cases": cases,
        "regression_assets": regression_assets,
    }


def _validate_roi(roi: Any, *, case_id: str, require_bbox: bool) -> None:
    if not isinstance(roi, dict):
        raise ManifestValidationError(f"{case_id}: critical_rois entry must be an object")
    for field in ("roi_id", "label", "roi_type"):
        val = roi.get(field)
        if not isinstance(val, str) or not val.strip():
            raise ManifestValidationError(f"{case_id}: ROI missing non-empty {field}")
    if roi["roi_type"] not in VALID_ROI_TYPES:
        raise ManifestValidationError(f"{case_id}: unsupported roi_type {roi['roi_type']!r}")
    if not isinstance(roi.get("must_lock_base"), bool):
        raise ManifestValidationError(f"{case_id}: ROI {roi['roi_id']} must_lock_base must be boolean")
    bbox = roi.get("bbox_norm")
    if bbox is None:
        if require_bbox:
            raise ManifestValidationError(
                f"{case_id}: available corpus case must populate normalized bbox_norm for ROI {roi['roi_id']}"
            )
        return
    if (
        not isinstance(bbox, list)
        or len(bbox) != 4
        or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in bbox)
    ):
        raise ManifestValidationError(f"{case_id}: ROI {roi['roi_id']} bbox_norm must be [x0, y0, x1, y1]")
    x0, y0, x1, y1 = [float(v) for v in bbox]
    if not (0.0 <= x0 < x1 <= 1.0 and 0.0 <= y0 < y1 <= 1.0):
        raise ManifestValidationError(
            f"{case_id}: ROI {roi['roi_id']} bbox_norm out of [0,1] bounds or empty: {bbox}"
        )


def validate_corpus_manifest(
    data: Any,
    *,
    repo_root: Optional[Path] = None,
    verify_files: bool = False,
) -> Dict[str, Any]:
    """Validate corpus manifest schema, split invariants, rights gates, and optional file hashes."""
    if not isinstance(data, dict):
        raise ManifestValidationError("Corpus manifest must be a JSON object")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ManifestValidationError(f"Unsupported schema_version: {data.get('schema_version')!r}")
    if data.get("split_frozen") is not True:
        raise ManifestValidationError("split_frozen must be true for F12-A corpus freeze")

    cases = data.get("cases")
    if not isinstance(cases, list):
        raise ManifestValidationError("Manifest 'cases' must be a list")

    seen_ids = set()
    split_shas: Dict[str, set] = {split: set() for split in VALID_SPLITS}
    available_shas = set()
    by_category: Dict[str, Dict[str, int]] = {
        cat: {"total": 0, "calibration": 0, "held_out": 0, "available": 0, "missing": 0, "excluded": 0}
        for cat in CORPUS_CATEGORIES
    }
    by_split: Dict[str, Dict[str, int]] = {
        split: {"total": 0, "available": 0, "missing": 0, "excluded": 0}
        for split in VALID_SPLITS
    }

    for entry in cases:
        if not isinstance(entry, dict):
            raise ManifestValidationError("Each case entry must be an object")
        case_id = entry.get("case_id")
        if not isinstance(case_id, str) or not case_id.strip():
            raise ManifestValidationError("Case entry missing valid case_id")
        if case_id in seen_ids:
            raise ManifestValidationError(f"Duplicate case_id: {case_id}")
        seen_ids.add(case_id)

        category = entry.get("category")
        if category not in CORPUS_CATEGORIES:
            raise ManifestValidationError(f"{case_id}: invalid category {category!r}")
        split = entry.get("split")
        if split not in VALID_SPLITS:
            raise ManifestValidationError(f"{case_id}: invalid split {split!r}")
        availability = entry.get("availability")
        if availability not in VALID_AVAILABILITY:
            raise ManifestValidationError(f"{case_id}: invalid availability {availability!r}")

        by_category[category]["total"] += 1
        by_category[category][split] += 1
        by_category[category][availability] += 1
        by_split[split]["total"] += 1
        by_split[split][availability] += 1

        rights = entry.get("rights")
        source = entry.get("source")
        known_text = entry.get("known_text")
        rois = entry.get("critical_rois")
        if not isinstance(rights, dict) or not isinstance(source, dict):
            raise ManifestValidationError(f"{case_id}: rights and source must be objects")
        for bool_field in ("cleared", "model_release_required", "model_release_verified"):
            if not isinstance(rights.get(bool_field), bool):
                raise ManifestValidationError(f"{case_id}: rights.{bool_field} must be boolean")
        if not isinstance(known_text, list) or any(not isinstance(t, str) for t in known_text):
            raise ManifestValidationError(f"{case_id}: known_text must be a list of strings")
        if not isinstance(rois, list) or not rois:
            raise ManifestValidationError(f"{case_id}: critical_rois must be a non-empty list")

        is_available = availability == "available"
        for roi in rois:
            _validate_roi(roi, case_id=case_id, require_bbox=is_available)

        if is_available:
            if not rights["cleared"]:
                raise ManifestValidationError(f"{case_id}: available case must have rights.cleared=true")
            if not isinstance(rights.get("permission_basis"), str) or not rights["permission_basis"].strip():
                raise ManifestValidationError(f"{case_id}: available case requires rights.permission_basis")
            if not isinstance(rights.get("license_id"), str) or not rights["license_id"].strip():
                raise ManifestValidationError(f"{case_id}: available case requires rights.license_id")
            if rights["model_release_required"] and not rights["model_release_verified"]:
                raise ManifestValidationError(
                    f"{case_id}: model_release_verified must be true when model_release_required=true"
                )
            sha = source.get("sha256")
            if not isinstance(sha, str) or not _SHA256_RE.fullmatch(sha):
                raise ManifestValidationError(f"{case_id}: available case requires 64-char hex source.sha256")
            if sha in available_shas:
                raise ManifestValidationError(f"{case_id}: duplicate source sha256 {sha} across available corpus cases")
            other_split = "held_out" if split == "calibration" else "calibration"
            if sha in split_shas[other_split]:
                raise ManifestValidationError(
                    f"{case_id}: split contamination detected (sha256 {sha} also appears in {other_split})"
                )
            available_shas.add(sha)
            split_shas[split].add(sha)

            w, h = source.get("width"), source.get("height")
            if isinstance(w, bool) or isinstance(h, bool) or not isinstance(w, int) or not isinstance(h, int) or w <= 0 or h <= 0:
                raise ManifestValidationError(f"{case_id}: available case requires positive integer source dimensions")
            if repo_root is not None:
                asset_path = _safe_repo_path(repo_root, source.get("relative_path"))
                if verify_files:
                    _verify_image_file(asset_path, sha, w, h)
            elif not isinstance(source.get("relative_path"), str) or not source["relative_path"].strip():
                raise ManifestValidationError(f"{case_id}: available case requires source.relative_path")
        elif availability == "missing":
            if rights["cleared"]:
                raise ManifestValidationError(f"{case_id}: missing case cannot claim rights.cleared=true")
            if source.get("sha256") is not None:
                raise ManifestValidationError(f"{case_id}: missing case must keep source.sha256=null")

    # Enforce 60-case / 30+30 split freeze contract
    if len(cases) != 60:
        raise ManifestValidationError(f"Corpus manifest must freeze 60 case slots, found {len(cases)}")
    if by_split["calibration"]["total"] != 30 or by_split["held_out"]["total"] != 30:
        raise ManifestValidationError("Frozen split requires 30 calibration and 30 held_out cases")
    for cat, counts in by_category.items():
        spec = CORPUS_CATEGORIES[cat]
        if (
            counts["total"] != spec["target_count"]
            or counts["calibration"] != spec["calibration_count"]
            or counts["held_out"] != spec["held_out_count"]
        ):
            raise ManifestValidationError(
                f"Category {cat} requires 12 cases (6 calibration / 6 held_out), found {counts}"
            )

    regression_assets = data.get("regression_assets")
    if not isinstance(regression_assets, list):
        raise ManifestValidationError("Manifest 'regression_assets' must be a list")
    for asset in regression_assets:
        if not isinstance(asset, dict):
            raise ManifestValidationError("Each regression_assets entry must be an object")
        if asset.get("counts_toward_60_case_corpus") is not False:
            raise ManifestValidationError("Regression asset must explicitly set counts_toward_60_case_corpus=false")
        if asset.get("rights_cleared") is not False:
            raise ManifestValidationError("Regression asset entry must set rights_cleared=false unless promoted cleanly")
        sha = asset.get("sha256")
        if not isinstance(sha, str) or not _SHA256_RE.fullmatch(sha):
            raise ManifestValidationError(f"Regression asset missing valid sha256: {asset.get('asset_id')}")
        w, h = asset.get("width"), asset.get("height")
        if isinstance(w, bool) or isinstance(h, bool) or not isinstance(w, int) or not isinstance(h, int) or w <= 0 or h <= 0:
            raise ManifestValidationError(f"Regression asset invalid dimensions: {asset.get('asset_id')}")
        if repo_root is not None:
            asset_path = _safe_repo_path(repo_root, asset.get("relative_path"))
            if verify_files:
                _verify_image_file(asset_path, sha, w, h)

    return {
        "schema_version": SCHEMA_VERSION,
        "split_frozen": True,
        "total_slots": len(cases),
        "available_cases": sum(c["available"] for c in by_split.values()),
        "missing_cases": sum(c["missing"] for c in by_split.values()),
        "excluded_cases": sum(c["excluded"] for c in by_split.values()),
        "by_split": by_split,
        "by_category": by_category,
        "regression_assets_count": len(regression_assets),
        "regression_assets_verified": bool(verify_files and repo_root is not None),
    }


def load_corpus_manifest(
    manifest_path: Path,
    *,
    repo_root: Optional[Path] = None,
    verify_files: bool = False,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    summary = validate_corpus_manifest(data, repo_root=repo_root, verify_files=verify_files)
    return data, summary
