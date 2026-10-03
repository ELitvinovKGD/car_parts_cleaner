const form = document.querySelector("#job-form");
const fileInput = document.querySelector("#image");
const editor = document.querySelector("#editor");
const photoCanvas = document.querySelector("#photo-canvas");
const paintCanvas = document.querySelector("#paint-canvas");
const placeholder = document.querySelector("#canvas-placeholder");
const photoContext = photoCanvas.getContext("2d");
const paintContext = paintCanvas.getContext("2d");
const brushInput = document.querySelector("#brush-size");
const brushOutput = document.querySelector("#brush-output");
const message = document.querySelector("#message");
const submit = document.querySelector("#submit");
const resultPanel = document.querySelector("#result-panel");

const layerDefinitions = {
  part: { label: "деталь", color: "rgba(0, 183, 255, 0.42)" },
  dent: { label: "вмятина", color: "rgba(255, 0, 0, 0.55)" },
  scratch: { label: "царапина", color: "rgba(255, 0, 255, 0.58)" },
  dirt: { label: "грязь", color: "rgba(255, 230, 0, 0.55)" },
};
const layerOrder = ["part", "dirt", "dent", "scratch"];
const layerCanvases = Object.fromEntries(Object.keys(layerDefinitions).map((name) => {
  const canvas = document.createElement("canvas");
  return [name, canvas];
}));
const layerContexts = Object.fromEntries(Object.entries(layerCanvases).map(([name, canvas]) => [
  name,
  canvas.getContext("2d", { willReadFrequently: true }),
]));

let activeLayer = "part";
let inputMode = "brush";
let drawing = false;
let lastPoint = null;
let currentJobId = null;
let sourceFile = null;
let history = [];
let samBusy = false;
let samStart = null;

function resetLayers(width, height) {
  for (const canvas of Object.values(layerCanvases)) {
    canvas.width = width;
    canvas.height = height;
    canvas.getContext("2d").clearRect(0, 0, width, height);
  }
  paintContext.clearRect(0, 0, width, height);
  history = [];
}

function pushHistory() {
  history.push({
    name: activeLayer,
    imageData: layerContexts[activeLayer].getImageData(
      0, 0, photoCanvas.width, photoCanvas.height,
    ),
  });
  if (history.length > 10) history.shift();
}

function restoreSnapshot(snapshot) {
  layerContexts[snapshot.name].putImageData(snapshot.imageData, 0, 0);
  renderOverlay();
}

function renderOverlay() {
  paintContext.clearRect(0, 0, paintCanvas.width, paintCanvas.height);
  const tint = document.createElement("canvas");
  tint.width = paintCanvas.width;
  tint.height = paintCanvas.height;
  const tintContext = tint.getContext("2d");
  for (const name of layerOrder) {
    tintContext.clearRect(0, 0, tint.width, tint.height);
    tintContext.fillStyle = layerDefinitions[name].color;
    tintContext.fillRect(0, 0, tint.width, tint.height);
    tintContext.globalCompositeOperation = "destination-in";
    tintContext.drawImage(layerCanvases[name], 0, 0);
    tintContext.globalCompositeOperation = "source-over";
    paintContext.drawImage(tint, 0, 0);
  }
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
    resetLayers(image.naturalWidth, image.naturalHeight);
    placeholder.hidden = true;
    editor.hidden = false;
    submit.disabled = false;
    message.textContent = `Загружено ${image.naturalWidth}×${image.naturalHeight}. Начните с выделения детали.`;
    URL.revokeObjectURL(image.src);
  };
  image.src = URL.createObjectURL(file);
});

document.querySelectorAll(".layer-tool").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".layer-tool").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    activeLayer = button.dataset.layer;
    if (inputMode === "sam" && activeLayer !== "part") selectMode("brush");
    message.textContent = `Активный слой: ${layerDefinitions[activeLayer].label}.`;
  });
});

function selectMode(mode) {
  inputMode = mode;
  document.querySelectorAll(".mode-tool").forEach((item) => {
    item.classList.toggle("active", item.dataset.mode === mode);
  });
  paintCanvas.classList.toggle("fill-mode", mode === "fill");
  paintCanvas.classList.toggle("sam-mode", mode === "sam");
}

document.querySelectorAll(".mode-tool").forEach((button) => {
  button.addEventListener("click", () => {
    const mode = button.dataset.mode;
    if (mode === "sam" && activeLayer !== "part") {
      document.querySelector('[data-layer="part"]').click();
    }
    selectMode(mode);
    message.textContent = mode === "sam"
      ? "SAM 2: щёлкните внутри нужной кузовной детали."
      : `Режим: ${button.textContent.trim().toLowerCase()}.`;
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

function stroke(context, from, to, width, clear = false) {
  context.save();
  context.globalCompositeOperation = clear ? "destination-out" : "source-over";
  context.strokeStyle = "#ffffff";
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
  stroke(
    layerContexts[activeLayer],
    lastPoint,
    point,
    Number(brushInput.value),
    inputMode === "erase",
  );
  lastPoint = point;
  renderOverlay();
}

function floodFill(point) {
  const canvas = layerCanvases[activeLayer];
  const context = layerContexts[activeLayer];
  const width = canvas.width;
  const height = canvas.height;
  const startX = Math.max(0, Math.min(width - 1, Math.floor(point.x)));
  const startY = Math.max(0, Math.min(height - 1, Math.floor(point.y)));
  const image = context.getImageData(0, 0, width, height);
  const start = (startY * width + startX) * 4;
  const targetAlpha = image.data[start + 3];
  if (targetAlpha > 127) return { changed: 0, blocked: false };

  const queue = new Int32Array(width * height);
  let head = 0;
  let tail = 0;
  queue[tail++] = startY * width + startX;
  image.data[start + 3] = 1;
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
      if (image.data[offset + 3] === targetAlpha) {
        image.data[offset + 3] = 1;
        queue[tail++] = neighbor;
      }
    }
  }
  if (tail > width * height * 0.65) return { changed: tail, blocked: true };
  for (let index = 0; index < tail; index += 1) {
    const offset = queue[index] * 4;
    image.data[offset] = 255;
    image.data[offset + 1] = 255;
    image.data[offset + 2] = 255;
    image.data[offset + 3] = 255;
  }
  context.putImageData(image, 0, 0);
  renderOverlay();
  return { changed: tail, blocked: false };
}

async function applySamMask(point, endPoint = null) {
  if (samBusy) return;
  samBusy = true;
  pushHistory();
  message.textContent = "SAM 2 выделяет деталь… Первый запуск загружает модель в память.";
  try {
    const body = new FormData();
    body.append("image", sourceFile, sourceFile.name);
    body.append("x", point.x.toString());
    body.append("y", point.y.toString());
    if (endPoint) {
      body.append("x2", endPoint.x.toString());
      body.append("y2", endPoint.y.toString());
    }
    const response = await fetch("/api/segment/part", { method: "POST", body });
    if (!response.ok) {
      const payload = await response.json();
      throw new Error(payload.detail || "SAM 2 не смог выделить деталь.");
    }
    const blob = await response.blob();
    const maskImage = new Image();
    maskImage.onload = () => {
      const context = layerContexts.part;
      context.clearRect(0, 0, photoCanvas.width, photoCanvas.height);
      const temporary = document.createElement("canvas");
      temporary.width = photoCanvas.width;
      temporary.height = photoCanvas.height;
      const temporaryContext = temporary.getContext("2d", { willReadFrequently: true });
      temporaryContext.drawImage(maskImage, 0, 0, temporary.width, temporary.height);
      const pixels = temporaryContext.getImageData(0, 0, temporary.width, temporary.height);
      for (let index = 0; index < pixels.data.length; index += 4) {
        const value = pixels.data[index];
        pixels.data[index] = 255;
        pixels.data[index + 1] = 255;
        pixels.data[index + 2] = 255;
        pixels.data[index + 3] = value;
      }
      context.putImageData(pixels, 0, 0);
      renderOverlay();
      message.textContent = "SAM 2 создал слой детали. Подправьте его кистью или ластиком.";
      URL.revokeObjectURL(maskImage.src);
    };
    maskImage.src = URL.createObjectURL(blob);
  } catch (error) {
    history.pop();
    message.textContent = error.message;
  } finally {
    samBusy = false;
  }
}

paintCanvas.addEventListener("pointerdown", (event) => {
  if (!sourceFile) return;
  event.preventDefault();
  const point = pointFromEvent(event);
  if (inputMode === "sam") {
    samStart = point;
    paintCanvas.setPointerCapture(event.pointerId);
    message.textContent = "Протяните рамку вокруг одной детали или просто щёлкните внутри неё.";
    return;
  }
  if (inputMode === "fill") {
    pushHistory();
    const result = floodFill(point);
    if (result.blocked) {
      restoreSnapshot(history.pop());
      message.textContent = "Заливка захватила почти весь холст. Сначала замкните границу кистью.";
    } else if (result.changed > 0) {
      message.textContent = `Залито пикселей: ${result.changed.toLocaleString("ru-RU")}.`;
    } else {
      history.pop();
    }
    return;
  }
  paintCanvas.setPointerCapture(event.pointerId);
  pushHistory();
  drawing = true;
  lastPoint = point;
  drawTo(lastPoint);
});

paintCanvas.addEventListener("pointermove", (event) => {
  if (samStart && inputMode === "sam") {
    event.preventDefault();
    const point = pointFromEvent(event);
    renderOverlay();
    paintContext.save();
    paintContext.strokeStyle = "#75e6bd";
    paintContext.lineWidth = Math.max(2, photoCanvas.width / 800);
    paintContext.setLineDash([12, 8]);
    paintContext.strokeRect(
      samStart.x,
      samStart.y,
      point.x - samStart.x,
      point.y - samStart.y,
    );
    paintContext.restore();
    return;
  }
  if (!drawing) return;
  event.preventDefault();
  drawTo(pointFromEvent(event));
});

function stopDrawing(event) {
  if (samStart && inputMode === "sam") {
    const start = samStart;
    const end = pointFromEvent(event);
    samStart = null;
    renderOverlay();
    if (paintCanvas.hasPointerCapture(event.pointerId)) {
      paintCanvas.releasePointerCapture(event.pointerId);
    }
    const distance = Math.hypot(end.x - start.x, end.y - start.y);
    applySamMask(start, distance > 12 ? end : null);
    return;
  }
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

document.querySelector("#clear-layer").addEventListener("click", () => {
  if (!sourceFile) return;
  pushHistory();
  layerContexts[activeLayer].clearRect(0, 0, photoCanvas.width, photoCanvas.height);
  renderOverlay();
  message.textContent = `Очищен слой «${layerDefinitions[activeLayer].label}».`;
});

function layerBlob(name) {
  const output = document.createElement("canvas");
  output.width = photoCanvas.width;
  output.height = photoCanvas.height;
  const context = output.getContext("2d");
  context.fillStyle = "#000000";
  context.fillRect(0, 0, output.width, output.height);
  context.drawImage(layerCanvases[name], 0, 0);
  return new Promise((resolve, reject) => {
    output.toBlob(
      (blob) => blob ? resolve(blob) : reject(new Error("Не удалось создать маску.")),
      "image/png",
    );
  });
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!sourceFile) return;
  submit.disabled = true;
  message.textContent = "Сохраняем слои и запускаем этапы: вмятины → царапины → грязь…";
  try {
    const body = new FormData();
    body.append("image", sourceFile, sourceFile.name);
    for (const name of Object.keys(layerDefinitions)) {
      body.append(`${name}_mask`, await layerBlob(name), `${name}.png`);
    }
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
    const stages = payload.completed_stages.join(" → ");
    message.textContent = payload.backend === "mock"
      ? `Слои сохранены (${stages}). Mock-режим не изменяет изображение.`
      : `Обработка завершена: ${stages}.`;
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
