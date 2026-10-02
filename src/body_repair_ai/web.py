from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel

from body_repair_ai.config import Settings, get_settings
from body_repair_ai.domain import JobRecord, Operation
from body_repair_ai.image_processing.semantic import parse_semantic_mask
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
    def health() -> dict[str, str]:
        return {"status": "ok", "backend": service.engine.name}

    @app.post("/api/jobs", status_code=201)
    async def create_job(
        image: Annotated[UploadFile, File()],
        annotation: Annotated[UploadFile, File()],
        operation: Annotated[Operation, Form()] = Operation.MIXED_REPAIR,
    ) -> dict[str, object]:
        original_image = await _read_image(image, "Image")
        annotation_image = await _read_image(annotation, "Semantic mask")
        try:
            semantic_masks = parse_semantic_mask(
                annotation_image,
                expected_size=original_image.size,
            )
            job = service.process(
                original_image,
                semantic_masks.editable,
                operation,
                semantic_mask=annotation_image,
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
