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
        "Photorealistic local retouch of the exact same used automotive part. Edit only the "
        "masked defects: gently remove dirt, visible scratches, scuffs and shallow dents. "
        "Preserve the original silhouette, geometry, body lines, holes, fasteners, grille, "
        "material, paint color, texture, lighting and natural reflections. Keep realistic wear."
    ),
    Operation.REMOVE_DENT: (
        "Exact same used automotive part after a conservative local repair. Flatten only the "
        "shallow dent inside the mask and continue the existing surface curvature and reflection. "
        "Preserve geometry, silhouette, edges, body lines, seams, holes, fasteners, paint, "
        "texture, lighting and every construction detail."
    ),
    Operation.REMOVE_DIRT: (
        "Exact same used automotive part after gentle cleaning. Remove only dirt, dust, sand and "
        "stains inside the mask. Reveal the same underlying material without repainting or making "
        "it new. Preserve geometry, texture, moderate gloss, lighting, reflections, holes, edges "
        "and natural signs of use."
    ),
    Operation.REMOVE_SCRATCH: (
        "Exact same used automotive part after conservative local retouch. Remove only the marked "
        "visible scratch or scuff, continuing the surrounding paint texture, color, lighting and "
        "reflection. Preserve geometry, silhouette, edges, seams, holes, fasteners and subtle "
        "natural wear."
    ),
}

NEGATIVE_PROMPT = (
    "changed shape, changed silhouette, changed proportions, moved object, resized object, changed "
    "perspective, changed body line, warped edge, distorted grille, invented hole, missing hole, "
    "invented fastener, missing fastener, altered seam, altered logo, altered text, new object, "
    "changed background, changed shadow, changed lighting, changed color, excessive gloss, plastic "
    "texture, brand new part, oversmoothed surface, fake reflection, repeating pattern, blur, "
    "watermark, generative artifact"
)

OPERATION_DENOISE = {
    Operation.MIXED_REPAIR: 0.36,
    Operation.REMOVE_DENT: 0.38,
    Operation.REMOVE_DIRT: 0.32,
    Operation.REMOVE_SCRATCH: 0.34,
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
                "{{NEGATIVE_PROMPT}}": NEGATIVE_PROMPT,
                "{{DENOISE}}": OPERATION_DENOISE[request.operation],
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
