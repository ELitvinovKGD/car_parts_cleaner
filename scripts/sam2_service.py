"""Small local-only HTTP service for point-prompted SAM 2 segmentation."""

from __future__ import annotations

import json
import os
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np
import torch
from PIL import Image
from transformers import Sam2Model, Sam2Processor

HOST = os.getenv("SAM2_HOST", "127.0.0.1")
PORT = int(os.getenv("SAM2_PORT", "8190"))
MODEL_PATH = Path(os.environ["SAM2_MODEL_PATH"]).resolve()
KEEP_GPU = os.getenv("SAM2_KEEP_GPU", "0") == "1"
MAX_IMAGE_BYTES = 25 * 1024 * 1024


class Predictor:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._model: Sam2Model | None = None
        self._processor: Sam2Processor | None = None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def _load(self) -> tuple[Sam2Model, Sam2Processor]:
        if self._model is None or self._processor is None:
            self._processor = Sam2Processor.from_pretrained(
                MODEL_PATH, local_files_only=True
            )
            self._model = Sam2Model.from_pretrained(
                MODEL_PATH, local_files_only=True
            ).eval()
        return self._model, self._processor

    def segment(
        self,
        image: Image.Image,
        x: float,
        y: float,
        x2: float | None = None,
        y2: float | None = None,
    ) -> Image.Image:
        with self._lock:
            model, processor = self._load()
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            model.to(device)
            prompts: dict[str, object]
            if x2 is not None and y2 is not None:
                prompts = {"input_boxes": [[[min(x, x2), min(y, y2), max(x, x2), max(y, y2)]]]}
            else:
                prompts = {
                    "input_points": [[[[x, y]]]],
                    "input_labels": [[[1]]],
                }
            inputs = processor(
                images=image.convert("RGB"), return_tensors="pt", **prompts
            ).to(device)
            autocast = (
                torch.autocast(device_type="cuda", dtype=torch.bfloat16)
                if device.type == "cuda"
                else torch.autocast(device_type="cpu", enabled=False)
            )
            with torch.inference_mode(), autocast:
                outputs = model(**inputs, multimask_output=True)
            masks = processor.post_process_masks(
                outputs.pred_masks.cpu(), inputs["original_sizes"].cpu()
            )[0]
            scores = outputs.iou_scores.detach().float().cpu()[0, 0]
            if x2 is not None and y2 is not None:
                left = max(0, int(min(x, x2)))
                top = max(0, int(min(y, y2)))
                right = min(image.width, int(max(x, x2)))
                bottom = min(image.height, int(max(y, y2)))
                box_area = max(1, (right - left) * (bottom - top))
                qualities = []
                for candidate in masks[0]:
                    area = max(1, int(candidate.sum().item()))
                    inside = int(candidate[top:bottom, left:right].sum().item())
                    containment = inside / area
                    coverage = min(inside / box_area, 1.0)
                    qualities.append(containment * coverage)
                best_index = int(np.argmax(qualities))
            else:
                best_index = int(torch.argmax(scores).item())
            mask = masks[0, best_index].detach().cpu().numpy()
            result = Image.fromarray(np.where(mask, 255, 0).astype(np.uint8), mode="L")
            if not KEEP_GPU and device.type == "cuda":
                model.to("cpu")
                del inputs, outputs, masks
                torch.cuda.empty_cache()
            return result


predictor = Predictor()


class Handler(BaseHTTPRequestHandler):
    server_version = "BodyRepairSAM2/0.1"

    def _json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/health":
            self._json(HTTPStatus.NOT_FOUND, {"detail": "Not found"})
            return
        self._json(
            HTTPStatus.OK,
            {
                "status": "ok",
                "model": MODEL_PATH.name,
                "model_present": (MODEL_PATH / "model.safetensors").exists(),
                "loaded": predictor.loaded,
                "device": "cuda" if torch.cuda.is_available() else "cpu",
            },
        )

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/segment":
            self._json(HTTPStatus.NOT_FOUND, {"detail": "Not found"})
            return
        try:
            query = parse_qs(parsed.query)
            x = float(query["x"][0])
            y = float(query["y"][0])
            x2 = float(query["x2"][0]) if "x2" in query else None
            y2 = float(query["y2"][0]) if "y2" in query else None
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length <= 0 or content_length > MAX_IMAGE_BYTES:
                raise ValueError("Invalid image size")
            image = Image.open(BytesIO(self.rfile.read(content_length)))
            image.load()
            if not (0 <= x < image.width and 0 <= y < image.height):
                raise ValueError("Click is outside the image")
            mask = predictor.segment(image, x, y, x2, y2)
            output = BytesIO()
            mask.save(output, format="PNG")
            body = output.getvalue()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"detail": str(exc)})
        except Exception as exc:  # service boundary: return diagnostics to the local caller
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"detail": str(exc)})

    def log_message(self, format: str, *args: object) -> None:
        print(f"SAM2 {self.address_string()} - {format % args}", flush=True)


if __name__ == "__main__":
    if not (MODEL_PATH / "model.safetensors").exists():
        raise SystemExit(f"SAM 2 model is missing at {MODEL_PATH}. Run setup-sam2.ps1.")
    print(f"SAM 2 service listening on http://{HOST}:{PORT}", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
