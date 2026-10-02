const form = document.querySelector("#job-form");
const fileInput = document.querySelector("#image");
const editor = document.querySelector("#editor");
const photoCanvas = document.querySelector("#photo-canvas");
const paintCanvas = document.querySelector("#paint-canvas");
const placeholder = document.querySelector("#canvas-placeholder");
const photoContext = photoCanvas.getContext("2d");
const paintContext = paintCanvas.getContext("2d");
const semanticCanvas = document.createElement("canvas");
const semanticContext = semanticCanvas.getContext("2d", { willReadFrequently: true });
const brushInput = document.querySelector("#brush-size");
const brushOutput = document.querySelector("#brush-output");
const message = document.querySelector("#message");
const submit = document.querySelector("#submit");
const resultPanel = document.querySelector("#result-panel");

const tools = {
  part: { semantic: "#ffffff", semanticRgb: [255, 255, 255], display: "rgba(0, 183, 255, 0.42)", displayRgba: [0, 183, 255, 107] },
  dent: { semantic: "#ff0000", semanticRgb: [255, 0, 0], display: "rgba(255, 0, 0, 0.55)", displayRgba: [255, 0, 0, 140] },
  dirt: { semantic: "#ffff00", semanticRgb: [255, 255, 0], display: "rgba(255, 255, 0, 0.55)", displayRgba: [255, 255, 0, 140] },
  scratch: { semantic: "#ff00ff", semanticRgb: [255, 0, 255], display: "rgba(255, 0, 255, 0.58)", displayRgba: [255, 0, 255, 148] },
  erase: { semantic: "#000000", semanticRgb: [0, 0, 0], display: null, displayRgba: [0, 0, 0, 0] },
};

let activeTool = "part";
let inputMode = "brush";
let drawing = false;
let lastPoint = null;
let currentJobId = null;
let sourceFile = null;
let history = [];

function resetSemanticCanvas(width, height) {
  semanticCanvas.width = width;
  semanticCanvas.height = height;
  semanticContext.fillStyle = "#000000";
  semanticContext.fillRect(0, 0, width, height);
  paintContext.clearRect(0, 0, width, height);
  history = [];
}

function pushHistory() {
  history.push({
    semantic: semanticContext.getImageData(0, 0, semanticCanvas.width, semanticCanvas.height),
    display: paintContext.getImageData(0, 0, paintCanvas.width, paintCanvas.height),
  });
  if (history.length > 20) history.shift();
}

function restoreSnapshot(snapshot) {
  semanticContext.putImageData(snapshot.semantic, 0, 0);
  paintContext.putImageData(snapshot.display, 0, 0);
}

fileInput.addEventListener("change", () => {
  const file = fileInput.files[0];
  if (!file) return;
  sourceFile = file;
  const image = new Image();
  image.onload = () => {
    [photoCanvas, paintCanvas].forEach((canvas) => {
      canvas.width = image.naturalWidth;
      canvas.height = image.naturalHeight;
    });
    photoContext.drawImage(image, 0, 0);
    resetSemanticCanvas(image.naturalWidth, image.naturalHeight);
    placeholder.hidden = true;
    editor.hidden = false;
    submit.disabled = false;
    message.textContent = `Загружено ${image.naturalWidth}×${image.naturalHeight}. Нанесите разметку.`;
    URL.revokeObjectURL(image.src);
  };
  image.src = URL.createObjectURL(file);
});

document.querySelectorAll(".color-tool").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".color-tool").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    activeTool = button.dataset.tool;
  });
});

document.querySelectorAll(".mode-tool").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".mode-tool").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    inputMode = button.dataset.mode;
    paintCanvas.classList.toggle("fill-mode", inputMode === "fill");
  });
});

brushInput.addEventListener("input", () => {
  brushOutput.value = `${brushInput.value} px`;
});

function pointFromEvent(event) {
  const bounds = paintCanvas.getBoundingClientRect();
  return {
    x: (event.clientX - bounds.left) * (paintCanvas.width / bounds.width),
    y: (event.clientY - bounds.top) * (paintCanvas.height / bounds.height),
  };
}

function stroke(context, from, to, color, width, clear = false) {
  context.save();
  context.globalCompositeOperation = clear ? "destination-out" : "source-over";
  context.strokeStyle = color || "rgba(0,0,0,1)";
  context.lineWidth = width;
  context.lineCap = "round";
  context.lineJoin = "round";
  context.beginPath();
  context.moveTo(from.x, from.y);
  context.lineTo(to.x, to.y);
  context.stroke();
  context.restore();
}

function drawTo(point) {
  const width = Number(brushInput.value);
  const tool = tools[activeTool];
  stroke(semanticContext, lastPoint, point, tool.semantic, width, false);
  stroke(paintContext, lastPoint, point, tool.display, width, activeTool === "erase");
  lastPoint = point;
}

function floodFill(point) {
  const width = semanticCanvas.width;
  const height = semanticCanvas.height;
  const startX = Math.max(0, Math.min(width - 1, Math.floor(point.x)));
  const startY = Math.max(0, Math.min(height - 1, Math.floor(point.y)));
  const semanticImage = semanticContext.getImageData(0, 0, width, height);
  const displayImage = paintContext.getImageData(0, 0, width, height);
  const startOffset = (startY * width + startX) * 4;
  const target = [
    semanticImage.data[startOffset],
    semanticImage.data[startOffset + 1],
    semanticImage.data[startOffset + 2],
    semanticImage.data[startOffset + 3],
  ];
  const tool = tools[activeTool];
  if (
    target[0] === tool.semanticRgb[0]
    && target[1] === tool.semanticRgb[1]
    && target[2] === tool.semanticRgb[2]
    && target[3] === 255
  ) return { changed: 0, blocked: false };

  const queue = new Int32Array(width * height);
  let head = 0;
  let tail = 0;
  queue[tail++] = startY * width + startX;
  // Mark queued pixels using alpha 254; saved semantic pixels are always opaque.
  semanticImage.data[startOffset + 3] = 254;

  while (head < tail) {
    const pixel = queue[head++];
    const x = pixel % width;
    const y = Math.floor(pixel / width);
    const neighbors = [];
    if (x > 0) neighbors.push(pixel - 1);
    if (x + 1 < width) neighbors.push(pixel + 1);
    if (y > 0) neighbors.push(pixel - width);
    if (y + 1 < height) neighbors.push(pixel + width);
    for (const neighbor of neighbors) {
      const offset = neighbor * 4;
      if (
        semanticImage.data[offset] === target[0]
        && semanticImage.data[offset + 1] === target[1]
        && semanticImage.data[offset + 2] === target[2]
        && semanticImage.data[offset + 3] === target[3]
      ) {
        semanticImage.data[offset + 3] = 254;
        queue[tail++] = neighbor;
      }
    }
  }

  const blocked = tail > width * height * 0.65;
  if (blocked) return { changed: tail, blocked: true };

  for (let index = 0; index < tail; index += 1) {
    const offset = queue[index] * 4;
    semanticImage.data[offset] = tool.semanticRgb[0];
    semanticImage.data[offset + 1] = tool.semanticRgb[1];
    semanticImage.data[offset + 2] = tool.semanticRgb[2];
    semanticImage.data[offset + 3] = 255;
    displayImage.data[offset] = tool.displayRgba[0];
    displayImage.data[offset + 1] = tool.displayRgba[1];
    displayImage.data[offset + 2] = tool.displayRgba[2];
    displayImage.data[offset + 3] = tool.displayRgba[3];
  }
  semanticContext.putImageData(semanticImage, 0, 0);
  paintContext.putImageData(displayImage, 0, 0);
  return { changed: tail, blocked: false };
}

paintCanvas.addEventListener("pointerdown", (event) => {
  if (!sourceFile) return;
  event.preventDefault();
  if (inputMode === "fill") {
    pushHistory();
    const result = floodFill(pointFromEvent(event));
    if (result.blocked) {
      history.pop();
      message.textContent = "Заливка захватила почти весь холст. Сначала замкните границу области кистью.";
      return;
    }
    if (result.changed > 0) {
      message.textContent = `Залито пикселей: ${result.changed.toLocaleString("ru-RU")}.`;
    } else {
      history.pop();
    }
    return;
  }
  paintCanvas.setPointerCapture(event.pointerId);
  pushHistory();
  drawing = true;
  lastPoint = pointFromEvent(event);
  drawTo(lastPoint);
});

paintCanvas.addEventListener("pointermove", (event) => {
  if (!drawing) return;
  event.preventDefault();
  drawTo(pointFromEvent(event));
});

function stopDrawing(event) {
  if (!drawing) return;
  drawing = false;
  lastPoint = null;
  if (event.pointerId !== undefined && paintCanvas.hasPointerCapture(event.pointerId)) {
    paintCanvas.releasePointerCapture(event.pointerId);
  }
}

paintCanvas.addEventListener("pointerup", stopDrawing);
paintCanvas.addEventListener("pointercancel", stopDrawing);

document.querySelector("#undo").addEventListener("click", () => {
  const snapshot = history.pop();
  if (snapshot) restoreSnapshot(snapshot);
});

document.querySelector("#clear").addEventListener("click", () => {
  if (!sourceFile) return;
  pushHistory();
  semanticContext.fillStyle = "#000000";
  semanticContext.fillRect(0, 0, semanticCanvas.width, semanticCanvas.height);
  paintContext.clearRect(0, 0, paintCanvas.width, paintCanvas.height);
});

function canvasBlob(canvas) {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => blob ? resolve(blob) : reject(new Error("Не удалось создать маску.")),
      "image/png",
    );
  });
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!sourceFile) return;
  submit.disabled = true;
  message.textContent = "Проверяем разметку и создаём задание…";
  try {
    const annotation = await canvasBlob(semanticCanvas);
    const body = new FormData();
    body.append("image", sourceFile, sourceFile.name);
    body.append("annotation", annotation, "semantic.png");
    body.append("operation", "mixed_repair");
    const response = await fetch("/api/jobs", { method: "POST", body });
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
      ? "Разметка сохранена. Mock-режим пока не изменяет изображение."
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
      ? accepted ? "Результат принят и сохранён." : "Результат отклонён для анализа."
      : payload.detail || "Не удалось сохранить оценку.";
  });
});
