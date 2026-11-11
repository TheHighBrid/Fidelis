"""Local inference for the pinned SegFormer B0 clothes export."""
import hashlib
import time

import numpy as np
from PIL import Image

MODEL_ID = "Xenova/segformer_b0_clothes"
REVISION = "a2489ea8e7ec1ee912190546bad31a4906ccca76"
WEIGHTS_SHA256 = "02e6f1545475bc549184b6710487555b4b73eb08354cc3a480fb4fab1473a9d3"
WEIGHTS_SIZE = 15199746
LABELS = (
    "Background", "Hat", "Hair", "Sunglasses", "Upper-clothes", "Skirt",
    "Pants", "Dress", "Belt", "Left-shoe", "Right-shoe", "Face",
    "Left-leg", "Right-leg", "Left-arm", "Right-arm", "Bag", "Scarf",
)
FABRIC_LABELS = {"Upper-clothes", "Skirt", "Pants", "Dress"}


def prepare_input(base):
    """Match the pinned processor's RGB bilinear resize and normalization."""
    resized = Image.fromarray(base).resize((512, 512), Image.Resampling.BILINEAR)
    pixels = np.asarray(resized, dtype=np.float32) / np.float32(255)
    mean = np.array([.485, .456, .406], dtype=np.float32)
    std = np.array([.229, .224, .225], dtype=np.float32)
    return np.ascontiguousarray(((pixels - mean) / std).transpose(2, 0, 1)[None])


def propose(store, job_id, expected_revision, weights):
    job = store.get(job_id)
    if job["profile"] == "packshot_strict":
        raise ValueError("Packshot Strict does not accept semantic texture suggestions")
    with store.open_array(job_id, "base", expected_revision=expected_revision) as base:
        tensor = prepare_input(base)

    with weights.open("rb") as stream:
        model_bytes = stream.read(WEIGHTS_SIZE + 1)
    if len(model_bytes) != WEIGHTS_SIZE or hashlib.sha256(model_bytes).hexdigest() != WEIGHTS_SHA256:
        raise ValueError("Weights do not match the pinned SegFormer B0 ONNX export")
    try:
        import onnxruntime as ort
    except ImportError as error:
        raise ValueError("Install the optional onnxruntime package for local inference") from error

    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    try:
        start = time.perf_counter()
        session = ort.InferenceSession(model_bytes, options, providers=["CPUExecutionProvider"])
        session_seconds = time.perf_counter() - start
        start = time.perf_counter()
        logits, = session.run(["logits"], {"pixel_values": tensor})
        inference_seconds = time.perf_counter() - start
    except Exception as error:
        raise ValueError(f"Local SegFormer inference failed: {error}") from error
    if (
        logits.shape != (1, len(LABELS), 128, 128)
        or logits.dtype != np.float32
        or not np.all(np.isfinite(logits))
    ):
        raise ValueError("SegFormer returned an invalid logits tensor")
    logits = logits[0]
    probabilities = np.exp(logits - logits.max(axis=0))
    probabilities /= probabilities.sum(axis=0)

    routing = {label: "fabric" for label in FABRIC_LABELS}
    routing["Hair"] = "hair"
    receipt = {
        "schema_version": 1,
        "base_artifact_sha256": job["artifacts"]["base"]["sha256"],
        "input_dimensions": job["dimensions"],
        "transform": "full_frame_resize_no_crop_no_rotation",
        "model": {
            "id": MODEL_ID,
            "revision": REVISION,
            "weights_sha256": WEIGHTS_SHA256,
            "terms_reference": "https://huggingface.co/mattmdjaga/segformer_b0_clothes/blob/7142c7f9d2be9ee39a47bd2091ad9d5fbe61bb1b/README.md",
        },
        "labels": [{"name": label, "region": routing.get(label, "unknown")} for label in LABELS],
        "execution": {
            "provider": "CPUExecutionProvider",
            "onnxruntime_version": ort.__version__,
            "session_seconds": session_seconds,
            "inference_seconds": inference_seconds,
        },
    }
    return store.stage_suggestion(job_id, probabilities, receipt, expected_revision=expected_revision)
