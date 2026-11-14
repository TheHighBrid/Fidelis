"""Reproducible, secret-safe live-worker and workflow schema preflight (F05-A / MEL-76).

Audits local runtime capabilities, resource owner/access and zero-paid-fallback budget
policy, ComfyUI worker `/system_stats` and `/object_info` endpoints, and exported
workflow graph compatibility (node classes, required inputs, model choices, and DAG
links) without placing credentials or secrets in the repository.

A passing preflight receipt (`qualified_preflight`) proves endpoint reachability and
static schema/choice compatibility (`E1`); it does not certify live GPU image output
(`E2`) or human visual acceptance (`E3`).
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from fidelis.studio.capabilities import inventory
from fidelis.studio.comfy import canonical_hash, validate_workflow
from fidelis.studio.store import sha256

WORKER_PREFLIGHT_SCHEMA = "fidelis.worker_preflight.v1"
WORKER_PREFLIGHT_POLICY_SCHEMA = "fidelis.worker_preflight_policy.v1"
DEFAULT_POLICY_PATH = Path(__file__).resolve().parents[2] / "config" / "worker-preflight-policy-v1.json"

_SECRET_VALUE_PATTERNS = (
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-+/=]{8,}"),
    re.compile(r"\b(?:sk|rk|pk)-[A-Za-z0-9_\-]{12,}\b"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{16,}\b"),
    re.compile(r"\b(?:hf|r8)_[A-Za-z0-9]{12,}\b"),
    re.compile(r"\b(?:lin_api|ntn)_[A-Za-z0-9]{12,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)

_MODEL_CHOICE_INPUT_NAMES = frozenset({
    "ckpt_name",
    "unet_name",
    "vae_name",
    "lora_name",
    "clip_name",
    "clip_name1",
    "clip_name2",
    "control_net_name",
    "upscale_model",
    "model_name",
})


def load_worker_preflight_policy(policy_path: Path | str | None = None) -> dict[str, Any]:
    path = Path(policy_path) if policy_path is not None else DEFAULT_POLICY_PATH
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != WORKER_PREFLIGHT_POLICY_SCHEMA:
        raise ValueError(f"Expected {WORKER_PREFLIGHT_POLICY_SCHEMA} policy document")
    if data.get("allow_remote_cloud_fallback") is not False:
        raise ValueError("Worker preflight policy must forbid automatic remote cloud fallback")
    budget = data.get("budget_policy")
    if not isinstance(budget, dict):
        raise ValueError("Missing budget_policy in worker preflight policy")
    if budget.get("allow_paid_remote_execution") is not False or float(budget.get("max_paid_spend_usd", -1)) != 0.0:
        raise ValueError("Local Studio worker preflight policy requires zero paid remote spend")
    access = data.get("resource_access_policy")
    if not isinstance(access, dict) or access.get("secret_storage_policy") != "forbid_repo_secrets":
        raise ValueError("Missing or invalid resource_access_policy in worker preflight policy")
    return data


def find_secret_violations(
    value: Any,
    *,
    forbidden_keys: set[str] | None = None,
    path: str = "root",
) -> list[str]:
    if forbidden_keys is None:
        forbidden_keys = {
            "access_key",
            "api_key",
            "apikey",
            "auth_token",
            "authorization",
            "bearer",
            "client_secret",
            "password",
            "private_key",
            "secret",
            "secret_key",
            "token",
        }
    violations: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            key_str = str(key)
            normalized = re.sub(r"[^a-z0-9]+", "_", key_str.lower()).strip("_")
            if normalized in forbidden_keys:
                violations.append(f"{path}.{key_str}: forbidden secret key '{key_str}'")
            violations.extend(
                find_secret_violations(item, forbidden_keys=forbidden_keys, path=f"{path}.{key_str}")
            )
    elif isinstance(value, list):
        for idx, item in enumerate(value):
            violations.extend(
                find_secret_violations(item, forbidden_keys=forbidden_keys, path=f"{path}[{idx}]")
            )
    elif isinstance(value, str):
        for pattern in _SECRET_VALUE_PATTERNS:
            if pattern.search(value):
                violations.append(f"{path}: string matches forbidden credential/token pattern")
                break
    return violations


def validate_endpoint_policy(address: str, policy: dict[str, Any]) -> dict[str, Any]:
    violations: list[str] = []
    parsed = urlparse(address)
    allowed_schemes = set(policy.get("allowed_schemes", ["http"]))
    allowed_hosts = set(policy.get("allowed_hosts", ["127.0.0.1", "localhost", "::1"]))

    if parsed.scheme not in allowed_schemes:
        violations.append(f"Endpoint scheme '{parsed.scheme}' not in allowed_schemes {sorted(allowed_schemes)}")
    if parsed.hostname not in allowed_hosts:
        violations.append(f"Endpoint host '{parsed.hostname}' not in allowed_hosts {sorted(allowed_hosts)}")
    if parsed.path not in ("", "/"):
        violations.append("Endpoint URL must not include a subpath")
    if parsed.username or parsed.password:
        violations.append("Endpoint URL must not embed username/password credentials")
    if parsed.query or parsed.fragment:
        violations.append("Endpoint URL must not include query parameters or fragments")
    if parsed.port is not None and not (1 <= int(parsed.port) <= 65535):
        violations.append("Endpoint port must be in 1..65535")

    host_str = (
        f"[{parsed.hostname}]"
        if parsed.hostname and ":" in parsed.hostname
        else parsed.hostname
    )
    sanitized_endpoint = f"{parsed.scheme}://{host_str}"
    if parsed.port:
        sanitized_endpoint = f"{sanitized_endpoint}:{parsed.port}"

    return {
        "endpoint": sanitized_endpoint,
        "hostname": parsed.hostname,
        "port": parsed.port or (80 if parsed.scheme == "http" else None),
        "scheme": parsed.scheme,
        "policy_compliant": len(violations) == 0,
        "violations": violations,
    }


def inspect_workflow_bundle(
    bundle: dict[str, Any],
    object_info: dict[str, Any] | None = None,
    *,
    max_nodes: int = 500,
) -> dict[str, Any]:
    """Inspect an exported ComfyUI workflow bundle offline and optionally against live `/object_info`."""
    structural_errors: list[str] = []
    if not isinstance(bundle, dict) or bundle.get("schema_version") != 1:
        structural_errors.append("Expected workflow bundle schema_version 1")
    family = bundle.get("family") if isinstance(bundle, dict) else None
    if family not in ("sdxl", "flux", "other"):
        structural_errors.append("Declare the workflow model family ('sdxl', 'flux', or 'other')")

    graph = bundle.get("workflow") if isinstance(bundle, dict) else None
    if not isinstance(graph, dict) or not graph or len(graph) > max_nodes:
        structural_errors.append(f"Supply an exported ComfyUI API graph (1..{max_nodes} nodes)")
        graph = {} if not isinstance(graph, dict) else graph

    input_node = bundle.get("input_node") if isinstance(bundle, dict) else None
    output_node = bundle.get("output_node") if isinstance(bundle, dict) else None
    if not isinstance(input_node, str) or input_node not in graph or graph.get(input_node, {}).get("class_type") != "LoadImage":
        structural_errors.append("input_node must identify a LoadImage node")
    if not isinstance(output_node, str) or output_node not in graph or graph.get(output_node, {}).get("class_type") != "SaveImage":
        structural_errors.append("output_node must identify a SaveImage node")

    required_classes: set[str] = set()
    referenced_models: list[dict[str, Any]] = []
    for node_id in sorted(graph):
        node = graph[node_id]
        if not isinstance(node, dict):
            structural_errors.append(f"Invalid workflow node {node_id}")
            continue
        class_type = node.get("class_type")
        if isinstance(class_type, str) and class_type:
            required_classes.add(class_type)
        inputs = node.get("inputs")
        if isinstance(inputs, dict):
            for input_name in sorted(inputs):
                val = inputs[input_name]
                if input_name in _MODEL_CHOICE_INPUT_NAMES and isinstance(val, str):
                    referenced_models.append({
                        "node_id": str(node_id),
                        "class_type": str(class_type or ""),
                        "input_name": input_name,
                        "model_identifier": val,
                    })

    report: dict[str, Any] = {
        "workflow_sha256": canonical_hash(bundle) if isinstance(bundle, dict) else None,
        "family": family,
        "node_count": len(graph),
        "input_node": input_node,
        "output_node": output_node,
        "required_node_classes": sorted(required_classes),
        "referenced_models": referenced_models,
        "structural_valid": len(structural_errors) == 0,
        "structural_errors": structural_errors,
        "schema_evaluated": object_info is not None,
        "schema_compatible": False,
        "missing_node_classes": [],
        "missing_required_inputs": [],
        "model_choice_checks": [],
        "validation_error": None,
    }

    if object_info is None:
        return report

    missing_classes = sorted(cls for cls in required_classes if cls not in object_info)
    missing_inputs: list[dict[str, Any]] = []
    choice_checks: list[dict[str, Any]] = []

    for node_id in sorted(graph):
        node = graph[node_id]
        if not isinstance(node, dict):
            continue
        class_type = node.get("class_type")
        inputs = node.get("inputs")
        if not isinstance(class_type, str) or class_type not in object_info or not isinstance(inputs, dict):
            continue
        spec = object_info[class_type].get("input", {}) if isinstance(object_info[class_type], dict) else {}
        required_spec = spec.get("required", {}) if isinstance(spec.get("required"), dict) else {}
        optional_spec = spec.get("optional", {}) if isinstance(spec.get("optional"), dict) else {}

        missing_for_node = sorted(set(required_spec) - set(inputs))
        if missing_for_node:
            missing_inputs.append({
                "node_id": str(node_id),
                "class_type": class_type,
                "missing_inputs": missing_for_node,
            })

        for name in sorted(inputs):
            value = inputs[name]
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str) and isinstance(value[1], int):
                continue
            if node_id == input_node and name == "image":
                continue
            field = required_spec.get(name, optional_spec.get(name))
            if isinstance(field, list) and field and isinstance(field[0], list):
                allowed_choices = field[0]
                available = value in allowed_choices
                choice_checks.append({
                    "node_id": str(node_id),
                    "class_type": class_type,
                    "input_name": name,
                    "requested_value": value,
                    "available": available,
                    "installed_choice_count": len(allowed_choices),
                })

    report["missing_node_classes"] = missing_classes
    report["missing_required_inputs"] = missing_inputs
    report["model_choice_checks"] = choice_checks

    try:
        validate_workflow(bundle, object_info)
        report["schema_compatible"] = True
    except ValueError as exc:
        report["schema_compatible"] = False
        report["validation_error"] = str(exc)

    return report


def _sanitize_system_stats(stats: dict[str, Any]) -> dict[str, Any]:
    system = stats.get("system") if isinstance(stats.get("system"), dict) else {}
    raw_devices = stats.get("devices") if isinstance(stats.get("devices"), list) else []
    devices: list[dict[str, Any]] = []
    for dev in raw_devices:
        if not isinstance(dev, dict):
            continue
        devices.append({
            "name": str(dev.get("name", "unknown")),
            "type": str(dev.get("type", "unknown")),
            "index": dev.get("index"),
            "vram_total": dev.get("vram_total"),
            "vram_free": dev.get("vram_free"),
            "torch_vram_total": dev.get("torch_vram_total"),
            "torch_vram_free": dev.get("torch_vram_free"),
        })
    return {
        "comfyui_version": system.get("comfyui_version"),
        "python_version": system.get("python_version"),
        "pytorch_version": system.get("pytorch_version"),
        "os": system.get("os"),
        "embedded_python": bool(system.get("embedded_python", False)),
        "ram_total": system.get("ram_total"),
        "ram_free": system.get("ram_free"),
        "devices": devices,
    }


def _probe_worker(address: str, *, timeout: float) -> tuple[dict[str, Any], dict[str, Any] | None]:
    client = httpx.Client(timeout=timeout, trust_env=False, follow_redirects=False)
    try:
        stats_resp = client.get(f"{address}/system_stats")
        stats_resp.raise_for_status()
        stats = stats_resp.json()

        schema_resp = client.get(f"{address}/object_info")
        schema_resp.raise_for_status()
        schema = schema_resp.json()

        if not isinstance(stats, dict) or not isinstance(schema, dict):
            raise ValueError("Invalid ComfyUI capability response")

        sanitized = _sanitize_system_stats(stats)
        worker_summary = {
            "reachable": True,
            "reason": None,
            "system": {
                "comfyui_version": sanitized["comfyui_version"],
                "python_version": sanitized["python_version"],
                "pytorch_version": sanitized["pytorch_version"],
                "os": sanitized["os"],
                "embedded_python": sanitized["embedded_python"],
                "ram_total": sanitized["ram_total"],
                "ram_free": sanitized["ram_free"],
            },
            "devices": sanitized["devices"],
            "installed_node_count": len(schema),
            "node_classes": sorted(schema),
            "object_info_sha256": canonical_hash(schema),
            "live_inference_verified": False,
        }
        return worker_summary, schema
    except (httpx.HTTPError, ValueError) as exc:
        return {
            "reachable": False,
            "reason": type(exc).__name__,
            "detail": str(exc)[:240],
            "system": None,
            "devices": [],
            "installed_node_count": 0,
            "node_classes": [],
            "object_info_sha256": None,
            "live_inference_verified": False,
        }, None
    finally:
        client.close()


def run_worker_preflight(
    repo_root: Path | str,
    *,
    address: str = "http://127.0.0.1:8188",
    workflow_path: Path | str | None = None,
    policy_path: Path | str | None = None,
    app_home: Path | str | None = None,
    timeout: float = 2.0,
    owner: str = "local-operator",
    access_method: str = "loopback",
) -> dict[str, Any]:
    """Run a reproducible, secret-safe preflight of the local runtime, worker endpoint, and workflow."""
    repo_root = Path(repo_root).resolve()
    resolved_policy_path = Path(policy_path).resolve() if policy_path is not None else DEFAULT_POLICY_PATH
    policy = load_worker_preflight_policy(resolved_policy_path)
    forbidden_keys = set(policy.get("forbidden_secret_keys", []))

    policy_violations: list[str] = []
    endpoint_check = validate_endpoint_policy(address, policy)
    policy_violations.extend(endpoint_check["violations"])

    timeout_range = policy["budget_policy"].get("timeout_seconds_range", [0.5, 60.0])
    if not (float(timeout_range[0]) <= float(timeout) <= float(timeout_range[1])):
        policy_violations.append(
            f"Timeout {timeout}s outside allowed range [{timeout_range[0]}, {timeout_range[1]}]"
        )

    owner_clean = str(owner or "").strip()
    if not owner_clean:
        policy_violations.append("Resource owner identifier must be non-empty")
    if access_method not in ("loopback", "ssh_tunnel"):
        policy_violations.append("access_method must be 'loopback' or 'ssh_tunnel'")

    policy_violations.extend(
        find_secret_violations(
            {"address": address, "owner": owner_clean, "access_method": access_method},
            forbidden_keys=forbidden_keys,
            path="request",
        )
    )

    workflow_bundle: dict[str, Any] | None = None
    workflow_file_meta: dict[str, Any] | None = None
    if workflow_path is not None:
        wf_path = Path(workflow_path).resolve()
        workflow_bundle = json.loads(wf_path.read_text(encoding="utf-8"))
        try:
            rel_wf = str(wf_path.relative_to(repo_root))
        except ValueError:
            rel_wf = wf_path.name
        workflow_file_meta = {
            "path": rel_wf,
            "file_sha256": sha256(wf_path),
        }
        policy_violations.extend(
            find_secret_violations(workflow_bundle, forbidden_keys=forbidden_keys, path="workflow")
        )

    local_inventory = inventory(repo_root, app_home)

    worker_summary: dict[str, Any]
    object_info: dict[str, Any] | None = None
    if endpoint_check["policy_compliant"] and not policy_violations:
        worker_summary, object_info = _probe_worker(endpoint_check["endpoint"], timeout=float(timeout))
    else:
        worker_summary = {
            "reachable": False,
            "reason": "PolicyViolation",
            "detail": "Skipped network probe due to policy or secret violation",
            "system": None,
            "devices": [],
            "installed_node_count": 0,
            "node_classes": [],
            "object_info_sha256": None,
            "live_inference_verified": False,
        }

    max_nodes = int(policy["budget_policy"].get("max_workflow_nodes", 500))
    workflow_report: dict[str, Any] | None = None
    if workflow_bundle is not None:
        workflow_report = inspect_workflow_bundle(
            workflow_bundle,
            object_info,
            max_nodes=max_nodes,
        )
        if workflow_file_meta is not None:
            workflow_report["source_file"] = workflow_file_meta

    if policy_violations:
        preflight_status = "policy_violation"
    elif workflow_report is not None and not workflow_report["structural_valid"]:
        preflight_status = "workflow_incompatible"
    elif not worker_summary["reachable"]:
        preflight_status = "worker_unreachable"
    elif workflow_report is None:
        preflight_status = "reachable_no_workflow"
    elif not workflow_report["schema_compatible"]:
        preflight_status = "workflow_incompatible"
    else:
        preflight_status = "qualified_preflight"

    receipt = {
        "schema": WORKER_PREFLIGHT_SCHEMA,
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "preflight_status": preflight_status,
        "evidence_level": "E1_preflight_protocol_only",
        "live_inference_verified": False,
        "visual_quality_certified": False,
        "policy": {
            "policy_schema": policy["schema"],
            "policy_version": policy.get("version", "1.0.0"),
            "policy_sha256": sha256(resolved_policy_path),
            "owner": owner_clean,
            "access_method": access_method,
            "endpoint": endpoint_check["endpoint"],
            "allow_remote_cloud_fallback": False,
            "max_paid_spend_usd": 0.0,
            "secret_storage_policy": policy["resource_access_policy"]["secret_storage_policy"],
            "policy_compliant": len(policy_violations) == 0,
            "policy_violations": policy_violations,
        },
        "local_runtime": local_inventory,
        "worker": worker_summary,
        "workflow": workflow_report,
    }

    receipt_secret_check = find_secret_violations(receipt, forbidden_keys=forbidden_keys, path="receipt")
    if receipt_secret_check:
        raise ValueError(f"Refusing to emit preflight receipt containing secret material: {receipt_secret_check}")

    return receipt
