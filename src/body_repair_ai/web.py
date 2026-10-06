from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel

from body_repair_ai.config import Settings, get_settings
from body_repair_ai.domain import JobRecord, Operation
from body_repair_ai.image_processing.semantic import parse_layer_masks, parse_semantic_mask
from body_repair_ai.inference import ComfyUIEngine, InferenceEngine, MockInferenceEngine
from body_repair_ai.service import RestorationService
from body_repair_ai.storage import DatasetStore

MAX_UPLOAD_BYTES = 25 * 1024 * 1024


class ReviewPayload(BaseModel):
    accepted: bool


def _public_job(job: JobRecord) -> dict[str, object]:
    return {
        "id": str(job.id),
        "operation": job.operation,
        "status": job.status,
        "backend": job.backend,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "error": job.error,
        "original_url": f"/api/jobs/{job.id}/artifacts/original",
        "mask_url": f"/api/jobs/{job.id}/artifacts/mask",
        "layer_urls": {
            name: f"/api/jobs/{job.id}/artifacts/{name}"
            for name in job.layer_mask_paths
        },
        "donor_url": (
            f"/api/jobs/{job.id}/artifacts/donor" if job.donor_path is not None else None
        ),
        "donor_mask_url": (
            f"/api/jobs/{job.id}/artifacts/donor_mask"
            if job.donor_mask_path is not None
            else None
        ),
        "completed_stages": job.completed_stages,
        "stage_tile_counts": job.stage_tile_counts,
        "result_url": (
            f"/api/jobs/{job.id}/artifacts/result" if job.result_path is not None else None
        ),
    }


async def _read_image(upload: UploadFile, label: str) -> Image.Image:
    payload = await upload.read(MAX_UPLOAD_BYTES + 1)
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"{label} exceeds 25 MB.")
    try:
        with Image.open(BytesIO(payload)) as image:
            image.load()
            return image.copy()
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(status_code=400, detail=f"{label} is not a valid image.") from exc


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    store = DatasetStore(settings.data_dir)
    store.initialize()

    engine: InferenceEngine
    if settings.inference_backend == "mock":
        engine = MockInferenceEngine()
    elif settings.inference_backend == "comfyui":
        engine = ComfyUIEngine(
            base_url=settings.comfyui_url,
            workflow_path=settings.comfyui_workflow,
            timeout_seconds=settings.comfyui_timeout_seconds,
            poll_interval_seconds=settings.comfyui_poll_interval_seconds,
        )
    else:
        raise RuntimeError(f"Unsupported inference backend: {settings.inference_backend}")
    service = RestorationService(settings, store, engine)

    app = FastAPI(title="Body Repair AI", version="0.1.0")
    assets = Path(__file__).with_name("web_assets")
    app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(assets / "index.html")

    @app.get("/api/health")
    def health() -> dict[str, str | bool]:
        try:
            sam_response = httpx.get(f"{settings.sam2_url.rstrip('/')}/health", timeout=1.0)
            sam_ready = sam_response.status_code == 200
        except httpx.HTTPError:
            sam_ready = False
        return {"status": "ok", "backend": service.engine.name, "sam2": sam_ready}

    @app.post("/api/segment/part")
    async def segment_part(
        image: Annotated[UploadFile, File()],
        x: Annotated[float, Form()],
        y: Annotated[float, Form()],
        x2: Annotated[float | None, Form()] = None,
        y2: Annotated[float | None, Form()] = None,
    ) -> Response:
        source = await _read_image(image, "Image")
        if not (0 <= x < source.width and 0 <= y < source.height):
            raise HTTPException(status_code=422, detail="SAM 2 click is outside the image.")
        buffer = BytesIO()
        source.convert("RGB").save(buffer, format="PNG")
        try:
            response = httpx.post(
                f"{settings.sam2_url.rstrip('/')}/segment",
                params={
                    "x": x,
                    "y": y,
                    **({"x2": x2, "y2": y2} if x2 is not None and y2 is not None else {}),
                },
                content=buffer.getvalue(),
                headers={"Content-Type": "image/png"},
                timeout=settings.sam2_timeout_seconds,
            )
            response.raise_for_status()
        except httpx.ConnectError as exc:
            raise HTTPException(
                status_code=503,
                detail="SAM 2 недоступен. Запустите .\\scripts\\start-sam2.ps1.",
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"SAM 2 отклонил запрос: {exc.response.text[:500]}",
            ) from exc
        except httpx.TimeoutException as exc:
            raise HTTPException(status_code=504, detail="SAM 2 не успел выделить деталь.") from exc
        return Response(content=response.content, media_type="image/png")

    @app.post("/api/jobs", status_code=201)
    async def create_job(
        image: Annotated[UploadFile, File()],
        annotation: Annotated[UploadFile | None, File()] = None,
        part_mask: Annotated[UploadFile | None, File()] = None,
        dent_mask: Annotated[UploadFile | None, File()] = None,
        dirt_mask: Annotated[UploadFile | None, File()] = None,
        scratch_mask: Annotated[UploadFile | None, File()] = None,
        operation: Annotated[Operation, Form()] = Operation.MIXED_REPAIR,
    ) -> dict[str, object]:
        original_image = await _read_image(image, "Image")
        try:
            layer_uploads = (part_mask, dent_mask, dirt_mask, scratch_mask)
            if all(upload is not None for upload in layer_uploads):
                part_image, dent_image, dirt_image, scratch_image = [
                    await _read_image(upload, "Layer mask")
                    for upload in layer_uploads
                    if upload is not None
                ]
                semantic_masks = parse_layer_masks(
                    part=part_image,
                    dent=dent_image,
                    dirt=dirt_image,
                    scratch=scratch_image,
                    expected_size=original_image.size,
                )
                job = service.process_layers(original_image, semantic_masks)
            elif annotation is not None:
                annotation_image = await _read_image(annotation, "Semantic mask")
                semantic_masks = parse_semantic_mask(
                    annotation_image,
                    expected_size=original_image.size,
                )
                if operation is Operation.MIXED_REPAIR and len(semantic_masks.labels_present) == 1:
                    operation = {
                        "dent": Operation.REMOVE_DENT,
                        "dirt": Operation.REMOVE_DIRT,
                        "scratch": Operation.REMOVE_SCRATCH,
                    }[semantic_masks.labels_present[0]]
                job = service.process(
                    original_image,
                    semantic_masks.editable,
                    operation,
                    semantic_mask=annotation_image,
                )
            else:
                raise ValueError("Upload all four layer masks.")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except httpx.ConnectError as exc:
            raise HTTPException(
                status_code=503,
                detail="ComfyUI недоступен. Запустите .\\scripts\\start-comfyui.ps1.",
            ) from exc
        except httpx.HTTPStatusError as exc:
            details = exc.response.text[:1000]
            raise HTTPException(
                status_code=502,
                detail=f"ComfyUI отклонил workflow: {details}",
            ) from exc
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise HTTPException(
                status_code=504,
                detail="ComfyUI не завершил обработку за отведённое время.",
            ) from exc
        return _public_job(job)

    @app.post("/api/donor-jobs", status_code=201)
    async def create_donor_job(
        image: Annotated[UploadFile, File()],
        part_mask: Annotated[UploadFile, File()],
        donor_image: Annotated[UploadFile, File()],
        donor_mask: Annotated[UploadFile, File()],
        match_color: Annotated[bool, Form()] = True,
    ) -> dict[str, object]:
        target = await _read_image(image, "Image")
        target_mask = await _read_image(part_mask, "Part mask")
        donor = await _read_image(donor_image, "Donor image")
        donor_mask_image = await _read_image(donor_mask, "Donor mask")
        try:
            job = service.process_donor(
                target,
                target_mask,
                donor,
                donor_mask_image,
                match_color=match_color,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _public_job(job)

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, object]:
        try:
            return _public_job(store.load_job(job_id))
        except (FileNotFoundError, ValueError):
            raise HTTPException(status_code=404, detail="Job not found.") from None

    @app.get("/api/jobs/{job_id}/artifacts/{artifact}", response_class=FileResponse)
    def get_artifact(job_id: str, artifact: str) -> FileResponse:
        try:
            job = store.load_job(job_id)
        except (FileNotFoundError, ValueError):
            raise HTTPException(status_code=404, detail="Job not found.") from None
        paths = {
            "original": job.original_path,
            "mask": job.hard_mask_path,
            "result": job.result_path,
            "donor": job.donor_path,
            "donor_mask": job.donor_mask_path,
            **job.layer_mask_paths,
        }
        path = paths.get(artifact)
        if path is None or not path.exists():
            raise HTTPException(status_code=404, detail="Artifact not found.")
        return FileResponse(path)

    @app.post("/api/jobs/{job_id}/review")
    def review_job(job_id: str, payload: ReviewPayload) -> dict[str, object]:
        try:
            job = service.review(job_id, accepted=payload.accepted)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Job not found.") from None
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _public_job(job)

    return app


app = create_app()
