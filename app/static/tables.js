const $ = (id) => document.getElementById(id);
const drop = $("drop");
const picker = $("picker");
const fileList = $("filelist");
const status = $("status");
const results = $("results");

let files = [];
let jobId = null;

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
const humanSize = (bytes) =>
  bytes < 1024 * 1024 ? `${Math.round(bytes / 1024)} KB` : `${(bytes / 1048576).toFixed(1)} MB`;

function setStatus(message, isError = false) {
  status.textContent = message;
  status.classList.toggle("error", isError);
}

function addFiles(incoming) {
  const pdfs = [...incoming].filter((f) => /\.pdf$/i.test(f.name));
  const skipped = incoming.length - pdfs.length;
  // De-duplicate by name+size so dropping the same batch twice is harmless.
  const seen = new Set(files.map((f) => `${f.name}:${f.size}`));
  for (const file of pdfs) {
    const key = `${file.name}:${file.size}`;
    if (!seen.has(key)) {
      seen.add(key);
      files.push(file);
    }
  }
  renderFiles();
  setStatus(skipped ? `Ignored ${plural(skipped, "non-PDF file")}.` : "", Boolean(skipped));
}

function renderFiles() {
  fileList.innerHTML = "";
  for (const file of files) {
    const li = document.createElement("li");
    const name = document.createElement("span");
    name.textContent = file.name;
    const size = document.createElement("span");
    size.className = "size";
    size.textContent = humanSize(file.size);
    li.append(name, size);
    fileList.append(li);
  }
  fileList.hidden = files.length === 0;
  $("run").disabled = files.length === 0;
  $("clear").hidden = files.length === 0;
}

function reset() {
  files = [];
  jobId = null;
  picker.value = "";
  results.hidden = true;
  renderFiles();
  setStatus("");
}

drop.addEventListener("click", () => picker.click());
drop.addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") {
    e.preventDefault();
    picker.click();
  }
});
picker.addEventListener("change", () => addFiles(picker.files));

["dragenter", "dragover"].forEach((type) =>
  drop.addEventListener(type, (e) => {
    e.preventDefault();
    drop.classList.add("over");
  })
);
["dragleave", "drop"].forEach((type) =>
  drop.addEventListener(type, (e) => {
    e.preventDefault();
    drop.classList.remove("over");
  })
);
drop.addEventListener("drop", (e) => addFiles(e.dataTransfer.files));
$("clear").addEventListener("click", reset);

$("run").addEventListener("click", async () => {
  const body = new FormData();
  files.forEach((file) => body.append("files", file));
  body.append("profile", $("profile").value);
  body.append("include_unmatched", $("unmatched").checked ? "true" : "false");

  $("run").disabled = true;
  results.hidden = true;
  setStatus(`Extracting from ${plural(files.length, "PDF")}…`);

  try {
    const response = await fetch("/api/tables/extract", { method: "POST", body });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Extraction failed.");
    render(payload);
    setStatus("");
  } catch (err) {
    setStatus(err.message, true);
  } finally {
    $("run").disabled = files.length === 0;
  }
});

$("download").addEventListener("click", () => {
  if (jobId) window.location.href = `/api/tables/download/${jobId}`;
});

function render(payload) {
  jobId = payload.job_id;
  const ok = payload.files.filter((f) => !f.error).length;
  $("summary").textContent =
    `${plural(payload.row_count, "row")} from ${plural(ok, "file")}`;
  $("truncated").hidden = !payload.truncated;
  renderReport(payload.files);
  renderPreview(payload.columns, payload.rows);
  results.hidden = false;
}

function renderReport(fileReports) {
  const body = $("report-body");
  body.innerHTML = "";
  for (const file of fileReports) {
    const wrap = document.createElement("div");
    wrap.className = "file-report";
    const title = document.createElement("h3");
    title.textContent = file.error
      ? file.filename
      : `${file.filename} — ${plural(file.row_count, "row")}`;
    wrap.append(title);

    const lines = document.createElement("ul");
    if (file.error) {
      lines.append(item(file.error, "err"));
    }
    for (const table of file.tables || []) {
      const mapped = Object.entries(table.matched)
        .map(([col, src]) => (src ? `${col} ← "${src}"` : `${col} ← (not found)`))
        .join(", ");
      lines.append(
        item(
          `p.${table.page} table ${table.table}: ${table.profile} ` +
            `(${Math.round(table.confidence * 100)}% fit, ${plural(table.row_count, "row")}) — ${mapped}`
        )
      );
    }
    for (const warning of file.warnings || []) {
      lines.append(item(warning, "warn"));
    }
    if (lines.childElementCount) wrap.append(lines);
    body.append(wrap);
  }
}

function item(text, className = "") {
  const li = document.createElement("li");
  li.textContent = text;
  if (className) li.className = className;
  return li;
}

function renderPreview(columns, rows) {
  const table = $("preview");
  table.innerHTML = "";

  const head = table.createTHead().insertRow();
  for (const column of columns) {
    const th = document.createElement("th");
    th.textContent = column;
    head.append(th);
  }

  const tbody = table.createTBody();
  for (const row of rows) {
    const tr = tbody.insertRow();
    for (const column of columns) {
      tr.insertCell().textContent = row[column] ?? "";
    }
  }
}

(async () => {
  try {
    const { profiles } = await (await fetch("/api/tables/profiles")).json();
    for (const profile of profiles) {
      const option = document.createElement("option");
      option.value = profile.name;
      option.textContent = `${profile.name} — ${profile.columns.join(", ")}`;
      $("profile").append(option);
    }
  } catch {
    setStatus("Could not load profiles.", true);
  }
})();
