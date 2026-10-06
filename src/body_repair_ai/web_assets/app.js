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
const detailDialog = document.querySelector("#detail-comparison-dialog");
const donorInput = document.querySelector("#donor-image");
const donorMaskInput = document.querySelector("#donor-mask-file");
const donorEditor = document.querySelector("#donor-editor");
const donorPhotoCanvas = document.querySelector("#donor-photo-canvas");
const donorMaskCanvas = document.querySelector("#donor-mask-canvas");
const donorPhotoContext = donorPhotoCanvas.getContext("2d");
const donorMaskContext = donorMaskCanvas.getContext("2d");
const donorLayerCanvas = document.createElement("canvas");
const donorLayerContext = donorLayerCanvas.getContext("2d", { willReadFrequently: true });
const donorSubmit = document.querySelector("#donor-submit");

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
let donorFile = null;
let donorSamReady = false;
let donorSamStart = null;
let donorSamBusy = false;

function createSynchronizedZoom(root, statusElement) {
  const viewports = [...root.querySelectorAll(".zoom-viewport")];
  const images = [...root.querySelectorAll("[data-zoom-image]")];
  const state = { scale: 1, x: 0, y: 0 };
  let drag = null;

  function clampPosition() {
    const viewport = viewports[0];
    const limitX = viewport.clientWidth * (state.scale - 1) / 2;
    const limitY = viewport.clientHeight * (state.scale - 1) / 2;
    state.x = Math.max(-limitX, Math.min(limitX, state.x));
    state.y = Math.max(-limitY, Math.min(limitY, state.y));
  }

  function apply() {
    clampPosition();
    const transform = `translate3d(${state.x}px, ${state.y}px, 0) scale(${state.scale})`;
    images.forEach((image) => { image.style.transform = transform; });
    viewports.forEach((viewport) => {
      viewport.classList.toggle("drag-ready", state.scale > 1);
    });
    statusElement.textContent = `${Math.round(state.scale * 100)}%`;
  }

  function reset() {
    state.scale = 1;
    state.x = 0;
    state.y = 0;
    apply();
  }

  viewports.forEach((viewport) => {
    viewport.addEventListener("wheel", (event) => {
      event.preventDefault();
      const previousScale = state.scale;
      const nextScale = Math.max(1, Math.min(8, previousScale * Math.exp(-event.deltaY * 0.0015)));
      if (nextScale === previousScale) return;
      const bounds = viewport.getBoundingClientRect();
      const cursorX = event.clientX - bounds.left - bounds.width / 2;
      const cursorY = event.clientY - bounds.top - bounds.height / 2;
      const ratio = nextScale / previousScale;
      state.x = cursorX - (cursorX - state.x) * ratio;
      state.y = cursorY - (cursorY - state.y) * ratio;
      state.scale = nextScale;
      apply();
    }, { passive: false });

    viewport.addEventListener("pointerdown", (event) => {
      if (state.scale <= 1) return;
      event.preventDefault();
      viewport.setPointerCapture(event.pointerId);
      viewport.classList.add("dragging");
      drag = {
        pointerId: event.pointerId,
        clientX: event.clientX,
        clientY: event.clientY,
        x: state.x,
        y: state.y,
      };
    });

    viewport.addEventListener("pointermove", (event) => {
      if (!drag || drag.pointerId !== event.pointerId) return;
      state.x = drag.x + event.clientX - drag.clientX;
      state.y = drag.y + event.clientY - drag.clientY;
      apply();
    });

    const stopDrag = (event) => {
      if (!drag || drag.pointerId !== event.pointerId) return;
      drag = null;
      viewport.classList.remove("dragging");
      if (viewport.hasPointerCapture(event.pointerId)) {
        viewport.releasePointerCapture(event.pointerId);
      }
    };
    viewport.addEventListener("pointerup", stopDrag);
    viewport.addEventListener("pointercancel", stopDrag);
    viewport.addEventListener("dblclick", reset);
  });

  window.addEventListener("resize", apply);
  apply();
  return { reset };
}

const mainZoom = createSynchronizedZoom(
  document.querySelector("#result-comparison"),
  document.querySelector("#main-zoom-value"),
);
const detailZoom = createSynchronizedZoom(
  document.querySelector("#detail-comparison"),
  document.querySelector("#detail-zoom-value"),
);

document.querySelector("#reset-main-zoom").addEventListener("click", mainZoom.reset);
document.querySelector("#reset-detail-zoom").addEventListener("click", detailZoom.reset);
document.querySelector("#open-detail-comparison").addEventListener("click", () => {
  document.querySelector("#detail-original").src = document.querySelector("#result-original").src;
  document.querySelector("#detail-result").src = document.querySelector("#result-image").src;
  detailDialog.showModal();
  requestAnimationFrame(detailZoom.reset);
});
document.querySelector("#close-detail-comparison").addEventListener("click", () => {
  detailDialog.close();
});
detailDialog.addEventListener("click", (event) => {
  if (event.target === detailDialog) detailDialog.close();
});

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
    selectMode(mode);
    message.textContent = mode === "sam"
      ? `SAM 2: обведите рамкой область слоя «${layerDefinitions[activeLayer].label}».`
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

function layerHasContent(name) {
  const pixels = layerContexts[name].getImageData(
    0, 0, photoCanvas.width, photoCanvas.height,
  ).data;
  for (let index = 3; index < pixels.length; index += 4) {
    if (pixels[index] > 127) return true;
  }
  return false;
}

function canvasHasContent(canvas, context) {
  if (!canvas.width || !canvas.height) return false;
  const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
  for (let index = 3; index < pixels.length; index += 4) {
    if (pixels[index] > 127) return true;
  }
  return false;
}

async function applySamMask(point, endPoint = null) {
  if (samBusy) return;
  if (activeLayer !== "part" && !layerHasContent("part")) {
    message.textContent = "Сначала выделите слой «Деталь»: дефектные слои ограничиваются его границей.";
    return;
  }
  const targetLayer = activeLayer;
  samBusy = true;
  pushHistory();
  message.textContent = `SAM 2 выделяет область слоя «${layerDefinitions[targetLayer].label}»…`;
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
      const context = layerContexts[targetLayer];
      if (targetLayer === "part") {
        context.clearRect(0, 0, photoCanvas.width, photoCanvas.height);
      }
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
      temporaryContext.putImageData(pixels, 0, 0);
      context.drawImage(temporary, 0, 0);
      if (targetLayer !== "part") {
        context.save();
        context.globalCompositeOperation = "destination-in";
        context.drawImage(layerCanvases.part, 0, 0);
        context.restore();
      }
      renderOverlay();
      message.textContent = `SAM 2 добавил область в слой «${layerDefinitions[targetLayer].label}». Подправьте её кистью или ластиком.`;
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
    message.textContent = `Протяните тесную рамку вокруг области «${layerDefinitions[activeLayer].label}» или щёлкните внутри неё.`;
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

function maskCanvasBlob(canvas) {
  const output = document.createElement("canvas");
  output.width = canvas.width;
  output.height = canvas.height;
  const context = output.getContext("2d");
  context.fillStyle = "#000000";
  context.fillRect(0, 0, output.width, output.height);
  context.drawImage(canvas, 0, 0);
  return new Promise((resolve, reject) => {
    output.toBlob(
      (blob) => blob ? resolve(blob) : reject(new Error("Не удалось создать маску.")),
      "image/png",
    );
  });
}

function renderDonorOverlay() {
  donorMaskContext.clearRect(0, 0, donorMaskCanvas.width, donorMaskCanvas.height);
  donorMaskContext.fillStyle = "rgba(117, 230, 189, 0.48)";
  donorMaskContext.fillRect(0, 0, donorMaskCanvas.width, donorMaskCanvas.height);
  donorMaskContext.globalCompositeOperation = "destination-in";
  donorMaskContext.drawImage(donorLayerCanvas, 0, 0);
  donorMaskContext.globalCompositeOperation = "source-over";
}

function loadDonorMaskBlob(blob) {
  const image = new Image();
  image.onload = () => {
    const temporary = document.createElement("canvas");
    temporary.width = donorLayerCanvas.width;
    temporary.height = donorLayerCanvas.height;
    const context = temporary.getContext("2d", { willReadFrequently: true });
    context.drawImage(image, 0, 0, temporary.width, temporary.height);
    const pixels = context.getImageData(0, 0, temporary.width, temporary.height);
    for (let index = 0; index < pixels.data.length; index += 4) {
      const value = Math.max(pixels.data[index], pixels.data[index + 1], pixels.data[index + 2]);
      pixels.data[index] = 255;
      pixels.data[index + 1] = 255;
      pixels.data[index + 2] = 255;
      pixels.data[index + 3] = value;
    }
    donorLayerContext.clearRect(0, 0, donorLayerCanvas.width, donorLayerCanvas.height);
    donorLayerContext.putImageData(pixels, 0, 0);
    renderDonorOverlay();
    donorSubmit.disabled = false;
    URL.revokeObjectURL(image.src);
  };
  image.src = URL.createObjectURL(blob);
}

donorInput.addEventListener("change", () => {
  const file = donorInput.files[0];
  if (!file) return;
  donorFile = file;
  const image = new Image();
  image.onload = () => {
    [donorPhotoCanvas, donorMaskCanvas, donorLayerCanvas].forEach((canvas) => {
      canvas.width = image.naturalWidth;
      canvas.height = image.naturalHeight;
    });
    donorPhotoContext.drawImage(image, 0, 0);
    donorLayerContext.clearRect(0, 0, donorLayerCanvas.width, donorLayerCanvas.height);
    renderDonorOverlay();
    donorEditor.hidden = false;
    donorSubmit.disabled = true;
    message.textContent = `Донор загружен: ${image.naturalWidth}×${image.naturalHeight}. Выделите его деталь через SAM 2.`;
    URL.revokeObjectURL(image.src);
  };
  image.src = URL.createObjectURL(file);
});

donorMaskInput.addEventListener("change", () => {
  const file = donorMaskInput.files[0];
  if (!file || !donorFile) {
    message.textContent = "Сначала загрузите фотографию-донора.";
    return;
  }
  loadDonorMaskBlob(file);
  message.textContent = "Маска донора загружена.";
});

document.querySelector("#donor-sam").addEventListener("click", () => {
  if (!donorFile) return;
  donorSamReady = true;
  donorMaskCanvas.classList.add("sam-ready");
  message.textContent = "Протяните тесную рамку вокруг детали на фотографии-доноре.";
});

document.querySelector("#donor-clear").addEventListener("click", () => {
  donorLayerContext.clearRect(0, 0, donorLayerCanvas.width, donorLayerCanvas.height);
  renderDonorOverlay();
  donorSubmit.disabled = true;
  message.textContent = "Маска донора очищена.";
});

function donorPointFromEvent(event) {
  const bounds = donorMaskCanvas.getBoundingClientRect();
  return {
    x: (event.clientX - bounds.left) * donorMaskCanvas.width / bounds.width,
    y: (event.clientY - bounds.top) * donorMaskCanvas.height / bounds.height,
  };
}

async function applyDonorSam(start, end = null) {
  if (donorSamBusy || !donorFile) return;
  donorSamBusy = true;
  message.textContent = "SAM 2 выделяет деталь на фотографии-доноре…";
  try {
    const body = new FormData();
    body.append("image", donorFile, donorFile.name);
    body.append("x", start.x.toString());
    body.append("y", start.y.toString());
    if (end) {
      body.append("x2", end.x.toString());
      body.append("y2", end.y.toString());
    }
    const response = await fetch("/api/segment/part", { method: "POST", body });
    if (!response.ok) {
      const payload = await response.json();
      throw new Error(payload.detail || "SAM 2 не смог выделить донора.");
    }
    loadDonorMaskBlob(await response.blob());
    message.textContent = "Деталь-донор выделена. Можно запускать пробную замену.";
  } catch (error) {
    message.textContent = error.message;
  } finally {
    donorSamBusy = false;
  }
}

donorMaskCanvas.addEventListener("pointerdown", (event) => {
  if (!donorSamReady) return;
  event.preventDefault();
  donorSamStart = donorPointFromEvent(event);
  donorMaskCanvas.setPointerCapture(event.pointerId);
});

donorMaskCanvas.addEventListener("pointermove", (event) => {
  if (!donorSamStart) return;
  event.preventDefault();
  const point = donorPointFromEvent(event);
  renderDonorOverlay();
  donorMaskContext.save();
  donorMaskContext.strokeStyle = "#75e6bd";
  donorMaskContext.lineWidth = Math.max(2, donorMaskCanvas.width / 800);
  donorMaskContext.setLineDash([12, 8]);
  donorMaskContext.strokeRect(
    donorSamStart.x,
    donorSamStart.y,
    point.x - donorSamStart.x,
    point.y - donorSamStart.y,
  );
  donorMaskContext.restore();
});

donorMaskCanvas.addEventListener("pointerup", (event) => {
  if (!donorSamStart) return;
  const start = donorSamStart;
  const end = donorPointFromEvent(event);
  donorSamStart = null;
  donorSamReady = false;
  donorMaskCanvas.classList.remove("sam-ready");
  renderDonorOverlay();
  if (donorMaskCanvas.hasPointerCapture(event.pointerId)) {
    donorMaskCanvas.releasePointerCapture(event.pointerId);
  }
  const distance = Math.hypot(end.x - start.x, end.y - start.y);
  applyDonorSam(start, distance > 12 ? end : null);
});

function showJobResult(payload) {
  currentJobId = payload.id;
  const cacheKey = `?v=${Date.now()}`;
  document.querySelector("#result-original").src = payload.original_url + cacheKey;
  document.querySelector("#result-image").src = payload.result_url + cacheKey;
  mainZoom.reset();
  document.querySelector("#backend-badge").textContent = `backend: ${payload.backend}`;
  resultPanel.hidden = false;
  resultPanel.scrollIntoView({ behavior: "smooth" });
}

donorSubmit.addEventListener("click", async () => {
  if (!sourceFile || !donorFile) return;
  if (!layerHasContent("part")) {
    message.textContent = "Сначала выделите слой «Деталь» на исходной фотографии.";
    return;
  }
  if (!canvasHasContent(donorLayerCanvas, donorLayerContext)) {
    message.textContent = "Сначала выделите деталь на фотографии-доноре.";
    return;
  }
  donorSubmit.disabled = true;
  message.textContent = "Выравниваем деталь-донора и подгоняем цвет…";
  try {
    const body = new FormData();
    body.append("image", sourceFile, sourceFile.name);
    body.append("part_mask", await layerBlob("part"), "part.png");
    body.append("donor_image", donorFile, donorFile.name);
    body.append("donor_mask", await maskCanvasBlob(donorLayerCanvas), "donor-mask.png");
    body.append("match_color", document.querySelector("#donor-match-color").checked.toString());
    const response = await fetch("/api/donor-jobs", { method: "POST", body });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Не удалось собрать результат по донору.");
    showJobResult(payload);
    message.textContent = "Пробная замена по донору готова. Проверьте контуры и освещение в сравнении.";
  } catch (error) {
    message.textContent = error.message;
  } finally {
    donorSubmit.disabled = false;
  }
});

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
    showJobResult(payload);
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
