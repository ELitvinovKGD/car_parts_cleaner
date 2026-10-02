const form = document.querySelector("#job-form");
const message = document.querySelector("#message");
const submit = document.querySelector("#submit");
const resultPanel = document.querySelector("#result-panel");
let currentJobId = null;

function bindPreview(inputId, previewId) {
  const input = document.querySelector(inputId);
  const preview = document.querySelector(previewId);
  input.addEventListener("change", () => {
    const file = input.files[0];
    if (!file) return;
    preview.src = URL.createObjectURL(file);
    preview.style.display = "block";
  });
}

bindPreview("#image", "#image-preview");
bindPreview("#mask", "#mask-preview");

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  submit.disabled = true;
  message.textContent = "Проверяем маску и создаём задание…";
  try {
    const response = await fetch("/api/jobs", { method: "POST", body: new FormData(form) });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Не удалось создать задание.");
    currentJobId = payload.id;
    const cacheKey = `?v=${Date.now()}`;
    document.querySelector("#result-original").src = payload.original_url + cacheKey;
    document.querySelector("#result-image").src = payload.result_url + cacheKey;
    document.querySelector("#backend-badge").textContent = `backend: ${payload.backend}`;
    resultPanel.hidden = false;
    resultPanel.scrollIntoView({ behavior: "smooth" });
    message.textContent = payload.backend === "mock"
      ? "Mock-режим: инфраструктура проверена, модель пока не изменяет изображение."
      : "Обработка завершена.";
  } catch (error) {
    message.textContent = error.message;
  } finally {
    submit.disabled = false;
  }
});

document.querySelectorAll("[data-review]").forEach((button) => {
  button.addEventListener("click", async () => {
    if (!currentJobId) return;
    const accepted = button.dataset.review === "true";
    const response = await fetch(`/api/jobs/${currentJobId}/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ accepted }),
    });
    const payload = await response.json();
    message.textContent = response.ok
      ? accepted ? "Результат принят и сохранён." : "Результат отклонён и сохранён для анализа."
      : payload.detail || "Не удалось сохранить оценку.";
  });
});
