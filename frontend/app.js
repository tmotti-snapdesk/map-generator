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

// --- People +/- buttons ---
const peopleInput = document.getElementById("people-input");
document.getElementById("btn-minus").addEventListener("click", () => {
  const v = parseInt(peopleInput.value, 10);
  if (v > 1) peopleInput.value = v - 1;
});
document.getElementById("btn-plus").addEventListener("click", () => {
  const v = parseInt(peopleInput.value, 10);
  if (v < 500) peopleInput.value = v + 1;
});

// --- Progress helpers ---
function setStep(n) {
  for (let i = 1; i <= 3; i++) {
    const el = document.getElementById(`step-${i}`);
    el.classList.remove("active", "done");
    if (i < n) el.classList.add("done");
    else if (i === n) el.classList.add("active");
    // Update done dot text
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

// --- Form submit ---
document.getElementById("gen-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  showError("");
  document.getElementById("result-section").style.display = "none";

  const file = pdfInput.files[0];
  const people = parseInt(peopleInput.value, 10);

  if (!file) {
    showError("Veuillez sélectionner un fichier PDF.");
    return;
  }
  if (!people || people < 1) {
    showError("Le nombre de collaborateurs doit être au moins 1.");
    return;
  }

  setSubmitLoading(true);
  showProgress(true);
  setStep(1);

  // Simulate step progression (the server does it all at once;
  // we animate the steps as time passes)
  const stepTimer1 = setTimeout(() => setStep(2), 3000);
  const stepTimer2 = setTimeout(() => setStep(3), 6000);

  try {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("people", String(people));

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

    setStep(4); // all done
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);

    const resultSection = document.getElementById("result-section");
    const resultImg = document.getElementById("result-img");
    const downloadLink = document.getElementById("download-link");
    const resultTitle = document.getElementById("result-title");

    resultImg.src = url;
    downloadLink.href = url;
    downloadLink.download = `plan_${people}p.png`;
    resultTitle.textContent = `Plan d'aménagement ${people}p`;
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
