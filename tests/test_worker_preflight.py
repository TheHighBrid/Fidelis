from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from fidelis.studio.worker_preflight import (
    WORKER_PREFLIGHT_SCHEMA,
    find_secret_violations,
    inspect_workflow_bundle,
    load_worker_preflight_policy,
    run_worker_preflight,
    validate_endpoint_policy,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _sample_workflow_bundle(
    *,
    ckpt_name: str = "juggernautXL_v9Rdphoto2Lightning.safetensors",
    extra_node: dict | None = None,
) -> dict:
    workflow = {
        "1": {
            "class_type": "LoadImage",
            "inputs": {"image": "placeholder.png"},
        },
        "2": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": ckpt_name},
        },
        "3": {
            "class_type": "VAEEncode",
            "inputs": {
                "pixels": ["1", 0],
                "vae": ["2", 2],
            },
        },
        "4": {
            "class_type": "VAEDecode",
            "inputs": {
                "samples": ["3", 0],
                "vae": ["2", 2],
            },
        },
        "5": {
            "class_type": "SaveImage",
            "inputs": {
                "images": ["4", 0],
                "filename_prefix": "fidelis_texture",
            },
        },
    }
    if extra_node is not None:
        workflow["6"] = extra_node
    return {
        "schema_version": 1,
        "family": "sdxl",
        "input_node": "1",
        "output_node": "5",
        "workflow": workflow,
    }


def _sample_object_info() -> dict:
    return {
        "LoadImage": {
            "input": {
                "required": {
                    "image": [["sample.png"], {}],
                }
            }
        },
        "CheckpointLoaderSimple": {
            "input": {
                "required": {
                    "ckpt_name": [
                        [
                            "juggernautXL_v9Rdphoto2Lightning.safetensors",
                            "sd_xl_base_1.0.safetensors",
                        ],
                        {},
                    ]
                }
            }
        },
        "VAEEncode": {
            "input": {
                "required": {
                    "pixels": ["IMAGE"],
                    "vae": ["VAE"],
                }
            }
        },
        "VAEDecode": {
            "input": {
                "required": {
                    "samples": ["LATENT"],
                    "vae": ["VAE"],
                }
            }
        },
        "SaveImage": {
            "input": {
                "required": {
                    "images": ["IMAGE"],
                    "filename_prefix": ["STRING", {"default": "ComfyUI"}],
                }
            }
        },
    }


def _sample_system_stats() -> dict:
    return {
        "system": {
            "os": "posix",
            "ram_total": 34359738368,
            "ram_free": 17179869184,
            "comfyui_version": "0.3.14",
            "python_version": "3.11.9",
            "pytorch_version": "2.5.1",
            "embedded_python": False,
            "argv": ["main.py", "--listen", "127.0.0.1"],
        },
        "devices": [
            {
                "name": "mps",
                "type": "mps",
                "index": 0,
                "vram_total": 25769803776,
                "vram_free": 21474836480,
                "torch_vram_total": 25769803776,
                "torch_vram_free": 21474836480,
            }
        ],
    }


@contextmanager
def _mock_comfy_worker(stats_payload: dict, object_info_payload: dict):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/system_stats":
                body = json.dumps(stats_payload).encode("utf-8")
            elif self.path == "/object_info":
                body = json.dumps(object_info_payload).encode("utf-8")
            else:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class WorkerPreflightTest(unittest.TestCase):
    def test_custom_policy_cannot_expand_local_access_or_budget(self):
        mutations = (
            ("allowed_hosts", ["127.0.0.1", "192.0.2.55"]),
            ("allowed_schemes", ["https"]),
            ("allowed_hosts", "localhost"),
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "policy.json"
            for key, value in mutations:
                with self.subTest(key=key, value=value):
                    policy = load_worker_preflight_policy()
                    policy[key] = value
                    path.write_text(json.dumps(policy))
                    with patch("fidelis.studio.worker_preflight._probe_worker") as probe:
                        with self.assertRaises(ValueError):
                            run_worker_preflight(REPO_ROOT, policy_path=path)
                    probe.assert_not_called()
            for value in ([0, 60], [1, 120], [10, 1], [1, float("inf")], [True, 3]):
                with self.subTest(value=value):
                    policy = load_worker_preflight_policy()
                    policy["budget_policy"]["timeout_seconds_range"] = value
                    path.write_text(json.dumps(policy))
                    with self.assertRaises(ValueError):
                        load_worker_preflight_policy(path)
            for value in (0, 501, True, "500"):
                with self.subTest(max_nodes=value):
                    policy = load_worker_preflight_policy()
                    policy["budget_policy"]["max_workflow_nodes"] = value
                    path.write_text(json.dumps(policy))
                    with self.assertRaises(ValueError):
                        load_worker_preflight_policy(path)
            policy = load_worker_preflight_policy()
            policy["allowed_hosts"] = ["127.0.0.1"]
            policy["budget_policy"]["timeout_seconds_range"] = [1, 5]
            path.write_text(json.dumps(policy))
            narrowed = load_worker_preflight_policy(path)
            self.assertTrue(validate_endpoint_policy("http://127.0.0.1:8188", narrowed)["policy_compliant"])
            self.assertFalse(validate_endpoint_policy("http://localhost:8188", narrowed)["policy_compliant"])

    def test_custom_secret_list_cannot_remove_builtin_protections(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "policy.json"
            policy = load_worker_preflight_policy()
            policy["forbidden_secret_keys"] = []
            path.write_text(json.dumps(policy))
            bundle = _sample_workflow_bundle()
            bundle["password"] = "ordinary-placeholder"
            workflow = Path(tmpdir) / "workflow.json"
            workflow.write_text(json.dumps(bundle))
            with patch("fidelis.studio.worker_preflight._probe_worker") as probe:
                receipt = run_worker_preflight(REPO_ROOT, policy_path=path, workflow_path=workflow)
            probe.assert_not_called()
            self.assertEqual(receipt["preflight_status"], "policy_violation")
            self.assertNotIn("ordinary-placeholder", json.dumps(receipt))

    def test_invalid_endpoints_never_probe_or_echo_address(self):
        examples = ("http://127.0.0.1:abc", "http://127.0.0.1:65536", "http://127.0.0.1:0",
                    "http://127.0.0.1:", "http://[::1", "http://[::1]extra", "http://@127.0.0.1",
                    "http://127.0.0.1?", "http://127.0.0.1#", "http://127.0.0.1\n",
                    "http://127.0.0.1\\", "http://nonlocal.example:8188")
        with tempfile.TemporaryDirectory() as home:
            for address in examples:
                with self.subTest(address=address), patch("fidelis.studio.worker_preflight._probe_worker") as probe:
                    receipt = run_worker_preflight(REPO_ROOT, address=address, app_home=home)
                    self.assertEqual(receipt["preflight_status"], "policy_violation")
                    self.assertIsNone(receipt["policy"]["endpoint"])
                    self.assertNotIn(address, json.dumps(receipt))
                    probe.assert_not_called()

    def test_malformed_endpoint_node_is_incompatible(self):
        bundle = _sample_workflow_bundle()
        bundle["workflow"]["1"] = None
        report = inspect_workflow_bundle(bundle, _sample_object_info())
        self.assertFalse(report["structural_valid"])
        self.assertFalse(report["schema_compatible"])
        self.assertIn("input_node must identify a LoadImage node", report["structural_errors"])

    def test_malformed_worker_node_spec_is_incompatible(self):
        schema = _sample_object_info()
        schema["CheckpointLoaderSimple"]["input"] = None
        report = inspect_workflow_bundle(_sample_workflow_bundle(), schema)
        self.assertFalse(report["schema_compatible"])
        self.assertIsNotNone(report["validation_error"])

    def test_default_policy_is_valid_and_zero_spend(self):
        from fidelis.studio.worker_preflight import validate_endpoint_policy

        policy = load_worker_preflight_policy()
        self.assertEqual(policy["schema"], "fidelis.worker_preflight_policy.v1")
        self.assertFalse(policy["allow_remote_cloud_fallback"])
        self.assertEqual(policy["budget_policy"]["max_paid_spend_usd"], 0.0)
        self.assertFalse(policy["budget_policy"]["allow_paid_remote_execution"])
        v6 = validate_endpoint_policy("http://[::1]:8188", policy)
        self.assertTrue(v6["policy_compliant"])
        self.assertEqual(v6["endpoint"], "http://[::1]:8188")

    def test_reachable_worker_and_compatible_workflow_qualifies_preflight(self):
        bundle = _sample_workflow_bundle()
        with tempfile.TemporaryDirectory() as tmpdir:
            wf_path = Path(tmpdir) / "sdxl_texture_workflow.json"
            wf_path.write_text(json.dumps(bundle), encoding="utf-8")

            with _mock_comfy_worker(_sample_system_stats(), _sample_object_info()) as address:
                receipt = run_worker_preflight(
                    REPO_ROOT,
                    address=address,
                    workflow_path=wf_path,
                    owner="melato-local",
                    access_method="loopback",
                )

        self.assertEqual(receipt["schema"], WORKER_PREFLIGHT_SCHEMA)
        self.assertEqual(receipt["preflight_status"], "qualified_preflight")
        self.assertFalse(receipt["live_inference_verified"])
        self.assertFalse(receipt["visual_quality_certified"])
        self.assertTrue(receipt["policy"]["policy_compliant"])
        self.assertTrue(receipt["worker"]["reachable"])
        self.assertEqual(receipt["worker"]["system"]["comfyui_version"], "0.3.14")
        self.assertEqual(len(receipt["worker"]["devices"]), 1)
        self.assertEqual(receipt["worker"]["devices"][0]["type"], "mps")
        self.assertTrue(receipt["workflow"]["schema_compatible"])
        self.assertEqual(receipt["workflow"]["missing_node_classes"], [])
        self.assertEqual(len(receipt["workflow"]["model_choice_checks"]), 1)
        self.assertTrue(receipt["workflow"]["model_choice_checks"][0]["available"])

    def test_missing_checkpoint_or_node_class_reports_workflow_incompatible(self):
        bundle = _sample_workflow_bundle(
            ckpt_name="missing_checkpoint_v1.safetensors",
            extra_node={"class_type": "UninstalledCustomPackNode", "inputs": {}},
        )
        report = inspect_workflow_bundle(bundle, _sample_object_info())
        self.assertFalse(report["schema_compatible"])
        self.assertEqual(report["missing_node_classes"], ["UninstalledCustomPackNode"])
        self.assertEqual(len(report["model_choice_checks"]), 1)
        self.assertFalse(report["model_choice_checks"][0]["available"])
        self.assertEqual(
            report["model_choice_checks"][0]["requested_value"],
            "missing_checkpoint_v1.safetensors",
        )

    def test_comfy_v3_combo_options_are_checked_for_model_choices(self):
        schema = _sample_object_info()
        schema["UpscaleModelLoader"] = {
            "input": {
                "required": {
                    "model_name": [
                        "COMBO",
                        {"multiselect": False, "options": ["realesr-general-x4v3.pth"]},
                    ]
                }
            },
            "output": ["UPSCALE_MODEL"],
        }
        schema["ImageUpscaleWithModel"] = {
            "input": {
                "required": {
                    "upscale_model": ["UPSCALE_MODEL"],
                    "image": ["IMAGE"],
                }
            },
            "output": ["IMAGE"],
        }
        valid_bundle = {
            "schema_version": 1,
            "family": "other",
            "input_node": "1",
            "output_node": "4",
            "workflow": {
                "1": {"class_type": "LoadImage", "inputs": {"image": "placeholder.png"}},
                "2": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": "realesr-general-x4v3.pth"}},
                "3": {"class_type": "ImageUpscaleWithModel", "inputs": {"upscale_model": ["2", 0], "image": ["1", 0]}},
                "4": {"class_type": "SaveImage", "inputs": {"images": ["3", 0], "filename_prefix": "out"}},
            },
        }
        ok = inspect_workflow_bundle(valid_bundle, schema)
        self.assertTrue(ok["schema_compatible"])
        self.assertEqual(len(ok["model_choice_checks"]), 1)
        self.assertTrue(ok["model_choice_checks"][0]["available"])
        self.assertEqual(ok["model_choice_checks"][0]["requested_value"], "realesr-general-x4v3.pth")

        missing_bundle = json.loads(json.dumps(valid_bundle))
        missing_bundle["workflow"]["2"]["inputs"]["model_name"] = "absent_model.pth"
        bad = inspect_workflow_bundle(missing_bundle, schema)
        self.assertFalse(bad["schema_compatible"])
        self.assertEqual(len(bad["model_choice_checks"]), 1)
        self.assertFalse(bad["model_choice_checks"][0]["available"])
        self.assertEqual(bad["model_choice_checks"][0]["requested_value"], "absent_model.pth")

    def test_unreachable_worker_records_offline_workflow_digest_without_failing_crash(self):
        bundle = _sample_workflow_bundle()
        with tempfile.TemporaryDirectory() as tmpdir:
            wf_path = Path(tmpdir) / "workflow.json"
            wf_path.write_text(json.dumps(bundle), encoding="utf-8")
            receipt = run_worker_preflight(
                REPO_ROOT,
                address="http://127.0.0.1:9",
                workflow_path=wf_path,
                timeout=0.5,
            )

        self.assertEqual(receipt["preflight_status"], "worker_unreachable")
        self.assertFalse(receipt["worker"]["reachable"])
        self.assertIsNotNone(receipt["workflow"]["workflow_sha256"])
        self.assertTrue(receipt["workflow"]["structural_valid"])
        self.assertFalse(receipt["workflow"]["schema_evaluated"])
        self.assertFalse(receipt["workflow"]["schema_compatible"])

    def test_policy_and_secret_guard_rejects_non_loopback_and_embedded_credentials(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            wf_path = Path(tmpdir) / "secret_workflow.json"
            bad_bundle = _sample_workflow_bundle()
            bad_bundle["api_key"] = "sk-live-secret-token-1234567890"
            wf_path.write_text(json.dumps(bad_bundle), encoding="utf-8")

            receipt = run_worker_preflight(
                REPO_ROOT,
                address="http://user:hunter2@192.0.2.55:8188/api?token=abc",
                workflow_path=wf_path,
            )

        self.assertEqual(receipt["preflight_status"], "policy_violation")
        self.assertFalse(receipt["policy"]["policy_compliant"])
        joined = " | ".join(receipt["policy"]["policy_violations"])
        self.assertIn("allowed_hosts", joined)
        self.assertIn("username/password", joined)
        self.assertIn("forbidden secret key", joined)
        self.assertEqual(find_secret_violations(receipt), [])

    def test_cli_writes_receipt_and_honors_require_qualified(self):
        bundle = _sample_workflow_bundle()
        with tempfile.TemporaryDirectory() as tmpdir:
            wf_path = Path(tmpdir) / "workflow.json"
            out_path = Path(tmpdir) / "preflight-receipt.json"
            wf_path.write_text(json.dumps(bundle), encoding="utf-8")

            with _mock_comfy_worker(_sample_system_stats(), _sample_object_info()) as address:
                proc = subprocess.run(
                    [
                        sys.executable,
                        str(REPO_ROOT / "scripts" / "worker-preflight.py"),
                        "--address",
                        address,
                        "--workflow",
                        str(wf_path),
                        "--output",
                        str(out_path),
                        "--require-qualified",
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            saved = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["preflight_status"], "qualified_preflight")

            unreachable_proc = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "worker-preflight.py"),
                    "--address",
                    "http://127.0.0.1:9",
                    "--workflow",
                    str(wf_path),
                    "--timeout",
                    "0.5",
                    "--require-qualified",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(unreachable_proc.returncode, 1)


if __name__ == "__main__":
    unittest.main()
