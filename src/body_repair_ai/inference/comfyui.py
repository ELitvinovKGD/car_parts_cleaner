from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from body_repair_ai.domain import Operation
from body_repair_ai.inference.base import InferenceRequest

OPERATION_PROMPTS = {
    Operation.MIXED_REPAIR: (
        "Restore only the marked defects on the painted automotive panel. Remove dents, dirt, "
        "and scratches while preserving the existing paint color, reflections, lighting, panel "
        "curvature, seams, and edges."
    ),
    Operation.REMOVE_DENT: (
        "Restore the smooth painted automotive panel inside the mask. Remove only the shallow "
        "dent while continuing the existing paint color, reflections, lighting, and panel "
        "curvature."
    ),
    Operation.REMOVE_DIRT: (
        "Remove only the dirt inside the mask. Reconstruct the same painted automotive surface, "
        "preserving color, reflections, lighting, and geometry."
    ),
    Operation.REMOVE_SCRATCH: (
        "Remove only the scratch inside the mask. Restore the original automotive paint and "
        "continue the surrounding reflections and lighting naturally."
    ),
}


def render_workflow(template: Any, replacements: dict[str, Any]) -> Any:
    """Recursively replace exact placeholder values in a ComfyUI API workflow."""

    if isinstance(template, dict):
        return {key: render_workflow(value, replacements) for key, value in template.items()}
    if isinstance(template, list):
        return [render_workflow(value, replacements) for value in template]
    if isinstance(template, str) and template in replacements:
        return replacements[template]
    return template


class ComfyUIEngine:
    name = "comfyui"

    def __init__(
        self,
        *,
        base_url: str,
        workflow_path: Path,
        timeout_seconds: float = 300.0,
        poll_interval_seconds: float = 1.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.workflow_path = workflow_path
        self.timeout_seconds = timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.client = client or httpx.Client(base_url=self.base_url, timeout=30.0)

    def _upload(self, path: Path, remote_name: str) -> str:
        with path.open("rb") as file_handle:
            response = self.client.post(
                "/upload/image",
                files={"image": (remote_name, file_handle, "image/png")},
                data={"type": "input", "overwrite": "true"},
            )
        response.raise_for_status()
        payload = response.json()
        return payload.get("name", remote_name)

    def _load_workflow(self) -> dict[str, Any]:
        if not self.workflow_path.exists():
            raise FileNotFoundError(
                f"ComfyUI workflow not found: {self.workflow_path}. "
                "Export it in API format and configure COMFYUI_WORKFLOW."
            )
        workflow = json.loads(self.workflow_path.read_text(encoding="utf-8"))
        if not isinstance(workflow, dict):
            raise ValueError("ComfyUI workflow must be a JSON object in API format.")
        return workflow

    def _wait_for_output(self, prompt_id: str) -> dict[str, str]:
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            response = self.client.get(f"/history/{prompt_id}")
            response.raise_for_status()
            history = response.json().get(prompt_id)
            if history:
                status = history.get("status", {})
                if status.get("status_str") == "error":
                    raise RuntimeError(f"ComfyUI execution failed: {status}")
                for node_output in history.get("outputs", {}).values():
                    images = node_output.get("images", [])
                    if images:
                        return images[0]
            time.sleep(self.poll_interval_seconds)
        raise TimeoutError(f"ComfyUI did not finish within {self.timeout_seconds:g} seconds.")

    def run(self, request: InferenceRequest) -> Path:
        request_id = uuid4().hex
        image_name = self._upload(request.image_path, f"body-repair-{request_id}-image.png")
        mask_name = self._upload(request.mask_path, f"body-repair-{request_id}-mask.png")
        seed = request.seed if request.seed is not None else int.from_bytes(uuid4().bytes[:4])
        workflow = render_workflow(
            self._load_workflow(),
            {
                "{{IMAGE}}": image_name,
                "{{MASK}}": mask_name,
                "{{PROMPT}}": OPERATION_PROMPTS[request.operation],
                "{{SEED}}": seed,
                "{{OUTPUT_PREFIX}}": f"body-repair-{request_id}",
            },
        )
        queued = self.client.post(
            "/prompt",
            json={"prompt": workflow, "client_id": request_id},
        )
        queued.raise_for_status()
        prompt_id = queued.json()["prompt_id"]
        output = self._wait_for_output(prompt_id)
        image_response = self.client.get(
            "/view",
            params={
                "filename": output["filename"],
                "subfolder": output.get("subfolder", ""),
                "type": output.get("type", "output"),
            },
        )
        image_response.raise_for_status()
        request.output_path.parent.mkdir(parents=True, exist_ok=True)
        request.output_path.write_bytes(image_response.content)
        return request.output_path
