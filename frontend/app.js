const API_BASE = window.location.origin;

// --- File drop zone ---
const dropZone = document.getElementById("drop-zone");
const pdfInput = document.getElementById("pdf-input");
const fileNameEl = document.getElementById("file-name");

pdfInput.addEventListener("change", () => {
  if (pdfInput.files[0]) {
    fileNameEl.textContent = pdfInput.files[0].name;
  }
});

dropZone.addEventListener("dragover", (e) => {
  e.preventDefault();
  dropZone.classList.add("dragover");
});
dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragover"));
dropZone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropZone.classList.remove("dragover");
  const file = e.dataTransfer.files[0];
  if (file && file.type === "application/pdf") {
    const dt = new DataTransfer();
    dt.items.add(file);
    pdfInput.files = dt.files;
    fileNameEl.textContent = file.name;
  }
});

// --- Area +/- buttons ---
const areaInput = document.getElementById("area-input");
document.getElementById("btn-minus").addEventListener("click", () => {
  const v = parseInt(areaInput.value, 10);
  if (v > 10) areaInput.value = Math.max(10, v - 10);
});
document.getElementById("btn-plus").addEventListener("click", () => {
  const v = parseInt(areaInput.value, 10);
  if (v < 10000) areaInput.value = Math.min(10000, v + 10);
});

// --- Progress helpers ---
function setStep(n) {
  for (let i = 1; i <= 3; i++) {
    const el = document.getElementById(`step-${i}`);
    el.classList.remove("active", "done");
    if (i < n) el.classList.add("done");
    else if (i === n) el.classList.add("active");
    if (i < n) el.querySelector(".step-dot").textContent = "✓";
    else el.querySelector(".step-dot").textContent = String(i);
  }
}

function showProgress(show) {
  document.getElementById("progress-wrap").style.display = show ? "block" : "none";
}

function showError(msg) {
  const el = document.getElementById("error-box");
  el.textContent = msg;
  el.style.display = msg ? "block" : "none";
}

function setSubmitLoading(loading) {
  const btn = document.getElementById("btn-submit");
  btn.disabled = loading;
  btn.innerHTML = loading
    ? `<div class="spinner"></div> Génération en cours…`
    : "Générer le plan";
}

// --- Render scenario cards ---
function renderScenarios(scenarios) {
  const container = document.getElementById("scenarios-container");
  container.innerHTML = "";

  const densityLabels = { low: "Flex", medium: "Standard", high: "Dense" };

  for (const s of scenarios) {
    const imgSrc = `data:image/png;base64,${s.image}`;
    const filename = `plan_${s.density}_${s.n_people}p.png`;

    const card = document.createElement("div");
    card.className = "scenario-card";
    card.innerHTML = `
      <div class="scenario-header">
        <span class="scenario-title">${s.label}</span>
        <div style="display:flex;gap:8px;align-items:center;">
          <span class="scenario-badge">${s.n_people} postes</span>
          <a href="${imgSrc}" download="${filename}" class="btn-download">⬇ Télécharger</a>
        </div>
      </div>
      <img src="${imgSrc}" class="scenario-img" alt="${s.label}" />
    `;
    container.appendChild(card);
  }
}

// --- Form submit ---
document.getElementById("gen-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  showError("");
  document.getElementById("result-section").style.display = "none";

  const file = pdfInput.files[0];
  const area = parseFloat(areaInput.value);

  if (!file) {
    showError("Veuillez sélectionner un fichier PDF.");
    return;
  }
  if (!area || area < 10) {
    showError("La surface doit être d'au moins 10 m².");
    return;
  }

  setSubmitLoading(true);
  showProgress(true);
  setStep(1);

  const stepTimer1 = setTimeout(() => setStep(2), 3000);
  const stepTimer2 = setTimeout(() => setStep(3), 6000);

  try {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("area_m2", String(area));

    const resp = await fetch(`${API_BASE}/api/generate`, {
      method: "POST",
      body: formData,
    });

    clearTimeout(stepTimer1);
    clearTimeout(stepTimer2);

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      throw new Error(err.detail || "Erreur serveur");
    }

    setStep(4);
    const data = await resp.json();

    renderScenarios(data.scenarios);

    const resultSection = document.getElementById("result-section");
    resultSection.style.display = "block";
    resultSection.scrollIntoView({ behavior: "smooth", block: "start" });

  } catch (err) {
    clearTimeout(stepTimer1);
    clearTimeout(stepTimer2);
    showError(`Erreur : ${err.message}`);
  } finally {
    setSubmitLoading(false);
    showProgress(false);
  }
});
