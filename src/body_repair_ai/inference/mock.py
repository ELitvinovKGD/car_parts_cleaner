from shutil import copyfile

from body_repair_ai.inference.base import InferenceRequest


class MockInferenceEngine:
    """Safe pipeline placeholder that copies the input unchanged."""

    name = "mock"

    def run(self, request: InferenceRequest):
        request.output_path.parent.mkdir(parents=True, exist_ok=True)
        copyfile(request.image_path, request.output_path)
        return request.output_path
