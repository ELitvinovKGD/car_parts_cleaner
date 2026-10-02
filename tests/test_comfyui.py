import json
from pathlib import Path

import httpx

from body_repair_ai.domain import Operation
from body_repair_ai.inference.base import InferenceRequest
from body_repair_ai.inference.comfyui import ComfyUIEngine, render_workflow


def test_render_workflow_replaces_exact_placeholders() -> None:
    template = {
        "node": {
            "inputs": {
                "image": "{{IMAGE}}",
                "seed": "{{SEED}}",
                "unchanged": "prefix {{IMAGE}}",
            }
        }
    }

    rendered = render_workflow(template, {"{{IMAGE}}": "input.png", "{{SEED}}": 42})

    assert rendered["node"]["inputs"]["image"] == "input.png"
    assert rendered["node"]["inputs"]["seed"] == 42
    assert rendered["node"]["inputs"]["unchanged"] == "prefix {{IMAGE}}"


def test_comfyui_engine_uploads_queues_and_downloads(tmp_path: Path) -> None:
    workflow_path = tmp_path / "workflow.json"
    workflow_path.write_text(
        json.dumps({"1": {"inputs": {"image": "{{IMAGE}}", "mask": "{{MASK}}"}}}),
        encoding="utf-8",
    )
    image_path = tmp_path / "image.png"
    mask_path = tmp_path / "mask.png"
    image_path.write_bytes(b"image")
    mask_path.write_bytes(b"mask")
    output_path = tmp_path / "output.png"
    upload_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal upload_count
        if request.url.path == "/upload/image":
            upload_count += 1
            return httpx.Response(200, json={"name": f"uploaded-{upload_count}.png"})
        if request.url.path == "/prompt":
            return httpx.Response(200, json={"prompt_id": "prompt-1"})
        if request.url.path == "/history/prompt-1":
            return httpx.Response(
                200,
                json={
                    "prompt-1": {
                        "status": {"status_str": "success"},
                        "outputs": {"9": {"images": [{"filename": "result.png"}]}},
                    }
                },
            )
        if request.url.path == "/view":
            return httpx.Response(200, content=b"generated-image")
        return httpx.Response(404)

    client = httpx.Client(
        base_url="http://comfyui.local",
        transport=httpx.MockTransport(handler),
    )
    engine = ComfyUIEngine(
        base_url="http://comfyui.local",
        workflow_path=workflow_path,
        poll_interval_seconds=0.001,
        client=client,
    )

    result = engine.run(
        InferenceRequest(
            image_path=image_path,
            mask_path=mask_path,
            output_path=output_path,
            operation=Operation.REMOVE_DENT,
            seed=123,
        )
    )

    assert upload_count == 2
    assert result.read_bytes() == b"generated-image"
