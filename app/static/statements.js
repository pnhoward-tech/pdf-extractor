const $ = (id) => document.getElementById(id);
const drop = $("drop");
const picker = $("picker");
const results = $("results");

let files = [];
let payload = null;

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
const humanSize = (b) =>
  b < 1048576 ? `${Math.round(b / 1024)} KB` : `${(b / 1048576).toFixed(1)} MB`;

// Status is icon + word + colour. Colour alone never carries the meaning.
const ICONS = {
  ok: "M13.5 4.5 6 12 2.5 8.5",
  check: "M8 4v5M8 11.5v.5",
  info: "M8 7v5M8 4.5v.5",
};

function pill(kind, text) {
  const span = document.createElement("span");
  span.className = `pill ${kind}`;
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 16 16");
  svg.setAttribute("aria-hidden", "true");
  if (kind === "ok") {
    svg.innerHTML = `<path d="${ICONS.ok}" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>`;
  } else {
    svg.innerHTML =
      `<circle cx="8" cy="8" r="6.5" fill="none" stroke="currentColor" stroke-width="1.6"/>` +
      `<path d="${ICONS[kind]}" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>`;
  }
  span.append(svg, document.createTextNode(text));
  return span;
}

function setStatus(message, isError = false) {
  $("status").textContent = message;
  $("status").classList.toggle("error", isError);
}

/* ---------------------------------------------------------------- files */

function addFiles(incoming) {
  const pdfs = [...incoming].filter((f) => /\.pdf$/i.test(f.name));
  const skipped = incoming.length - pdfs.length;
  const seen = new Set(files.map((f) => `${f.name}:${f.size}`));
  for (const file of pdfs) {
    const key = `${file.name}:${file.size}`;
    if (!seen.has(key)) {
      seen.add(key);
      files.push(file);
    }
  }
  files.sort((a, b) => a.name.localeCompare(b.name));
  renderFiles();
  setStatus(skipped ? `Ignored ${plural(skipped, "non-PDF file")}.` : "", Boolean(skipped));
}

function renderFiles() {
  const list = $("filelist");
  list.innerHTML = "";
  for (const file of files) {
    const li = document.createElement("li");
    const name = document.createElement("span");
    name.textContent = file.name;
    const size = document.createElement("span");
    size.className = "size";
    size.textContent = humanSize(file.size);
    li.append(name, size);
    list.append(li);
  }
  list.hidden = files.length === 0;
  $("run").disabled = files.length === 0;
  $("clear").hidden = files.length === 0;
}

drop.addEventListener("click", () => picker.click());
drop.addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") {
    e.preventDefault();
    picker.click();
  }
});
picker.addEventListener("change", () => addFiles(picker.files));
["dragenter", "dragover"].forEach((t) =>
  drop.addEventListener(t, (e) => {
    e.preventDefault();
    drop.classList.add("over");
  })
);
["dragleave", "drop"].forEach((t) =>
  drop.addEventListener(t, (e) => {
    e.preventDefault();
    drop.classList.remove("over");
  })
);
drop.addEventListener("drop", (e) => addFiles(e.dataTransfer.files));
$("clear").addEventListener("click", () => {
  files = [];
  payload = null;
  picker.value = "";
  results.hidden = true;
  renderFiles();
  setStatus("");
});

/* -------------------------------------------------------------- extract */

$("run").addEventListener("click", async () => {
  const body = new FormData();
  files.forEach((f) => body.append("files", f));
  body.append("account_label", $("label").value.trim());
  body.append("profile", $("profile").value);
  body.append("ocr", $("ocr").checked ? "true" : "false");
  body.append("dedupe", $("dedupe").checked ? "true" : "false");

  $("run").disabled = true;
  results.hidden = true;
  setStatus(
    `Reading ${plural(files.length, "statement")}…` +
      ($("ocr").checked ? " Scans take a while to OCR." : "")
  );

  try {
    const response = await fetch("/api/statements/extract", { method: "POST", body });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Extraction failed.");
    payload = data;
    render(data);
    setStatus("");
  } catch (err) {
    setStatus(err.message, true);
  } finally {
    $("run").disabled = files.length === 0;
  }
});

$("dl-txns").addEventListener("click", () => {
  if (payload) window.location.href = `/api/statements/download/${payload.job_id}/transactions`;
});
$("dl-recon").addEventListener("click", () => {
  if (payload) window.location.href = `/api/statements/download/${payload.job_id}/reconciliation`;
});

/* --------------------------------------------------------------- render */

function render(data) {
  renderKpis(data);
  renderStatements(data.statements);
  renderAlerts(data);
  buildAccountFilter(data.rows);
  renderRows();
  $("dl-txns").disabled = data.shipped_count === 0;
  results.hidden = false;
}

function kpi(value, label, sub = "", tone = "") {
  const box = document.createElement("div");
  box.className = `kpi${tone ? ` is-${tone}` : ""}`;
  const v = document.createElement("div");
  v.className = "value";
  v.textContent = value;
  const l = document.createElement("div");
  l.className = "label";
  l.textContent = label;
  box.append(v, l);
  if (sub) {
    const s = document.createElement("div");
    s.className = "sub";
    s.textContent = sub;
    box.append(s);
  }
  return box;
}

function renderKpis(data) {
  const total = data.statements.length;
  const ok = data.statements.filter((s) => s.ok).length;
  const accounts = new Set(data.rows.map((r) => r.account_id).filter(Boolean));
  const currencies = [...new Set(data.statements.map((s) => s.currency))];
  const box = $("kpis");
  box.innerHTML = "";
  box.append(
    kpi(`${ok}/${total}`, "Statements reconciled", ok === total ? "all balance" : `${total - ok} held back`,
        ok === total ? "good" : "critical"),
    kpi(data.shipped_count.toLocaleString(), "Transactions in the CSV",
        data.row_count !== data.shipped_count ? `${data.row_count - data.shipped_count} withheld` : ""),
    kpi(String(accounts.size), "Accounts", currencies.join(", ")),
    kpi(String(new Set(data.statements.map((s) => s.bank)).size), "Banks"),
    kpi(String(data.duplicates.length), "Cross-account duplicates",
        data.duplicates.length ? "tagged, not removed" : "none found",
        data.duplicates.length ? "" : "")
  );
}

function renderStatements(statements) {
  const box = $("statements");
  box.innerHTML = "";
  for (const s of statements) {
    const details = document.createElement("details");
    details.className = "stmt";
    if (!s.ok) details.open = true;

    const summary = document.createElement("summary");
    summary.className = "stmt-head";
    summary.append(s.ok ? pill("ok", "Balances") : pill("check", "Check"));

    const name = document.createElement("div");
    name.innerHTML = "";
    const title = document.createElement("div");
    title.className = "stmt-name";
    title.textContent = s.source_file;
    const meta = document.createElement("div");
    meta.className = "stmt-meta";
    meta.textContent = [s.owner, s.account_id, s.bank, s.ocr ? "OCR" : ""]
      .filter(Boolean).join(" · ");
    name.append(title, meta);
    summary.append(name);

    const figures = [
      ["Opening", s.opening_balance],
      ["In", s.computed_paid_in],
      ["Out", s.computed_paid_out],
      [s.liability ? "Owed" : "Closing", s.closing_balance],
    ];
    for (const [cap, value] of figures) {
      const cell = document.createElement("div");
      cell.className = "stmt-num";
      const c = document.createElement("span");
      c.className = "cap";
      c.textContent = cap;
      cell.append(c, document.createTextNode(value || "—"));
      summary.append(cell);
    }
    const chev = document.createElement("span");
    chev.className = "chev";
    chev.textContent = "›";
    summary.append(chev);
    details.append(summary);

    const body = document.createElement("div");
    body.className = "stmt-body";
    const dl = document.createElement("dl");
    const facts = [
      ["Profile", s.inferred ? `${s.profile} (inferred)` : s.profile],
      ["Chosen because", s.selection],
      ["Period", s.period_start || s.period_end ? `${s.period_start || "?"} to ${s.period_end || "?"}` : "not printed"],
      ["Transactions", String(s.transaction_count)],
      ["Bank's own totals", `in ${s.printed_paid_in || "—"}, out ${s.printed_paid_out || "—"}`],
    ];
    for (const [term, value] of facts) {
      const dt = document.createElement("dt");
      dt.textContent = term;
      const dd = document.createElement("dd");
      dd.textContent = value;
      dl.append(dt, dd);
    }
    body.append(dl);
    for (const note of s.notes) {
      const p = document.createElement("p");
      p.className = "note";
      p.textContent = note;
      body.append(p);
    }
    const said = new Set(s.notes);
    for (const warning of s.warnings) {
      if (said.has(warning) || [...said].some((n) => n.startsWith(warning.slice(0, 40)))) continue;
      said.add(warning);
      const p = document.createElement("p");
      p.className = "warn";
      p.textContent = warning;
      body.append(p);
    }
    details.append(body);
    box.append(details);
  }
}

function renderAlerts(data) {
  const items = [];
  for (const e of data.errors) items.push(["check", `${e.file}: ${e.message}`]);
  for (const c of data.continuity) items.push(["info", c]);
  for (const d of data.duplicates) {
    items.push(["info", `${plural(d.count, "record")} of one movement across ${d.accounts.join(" and ")} — tagged, not removed.`]);
  }
  const list = $("alerts");
  list.innerHTML = "";
  for (const [kind, text] of items) {
    const li = document.createElement("li");
    li.append(pill(kind, kind === "ok" ? "OK" : kind === "check" ? "Error" : "Note"),
              document.createTextNode(text));
    list.append(li);
  }
  $("alerts-panel").hidden = items.length === 0;
}

const COLUMNS = [
  ["txn_date", "Date"],
  ["description", "Description"],
  ["paid_out", "Out"],
  ["paid_in", "In"],
  ["currency", "Ccy"],
  ["running_balance", "Balance"],
  ["type_code", "Code"],
  ["owner", "Owner"],
  ["account_id", "Account"],
  ["source_file", "Statement"],
  ["date_confidence", "Date check"],
  ["duplicate_of", "Also in"],
];

function buildAccountFilter(rows) {
  const select = $("f-account");
  const current = select.value;
  const accounts = [...new Set(rows.map((r) => `${r.owner || "?"} · ${r.account_id || "?"}`))].sort();
  select.innerHTML = '<option value="">All accounts</option>';
  for (const account of accounts) {
    const option = document.createElement("option");
    option.value = account;
    option.textContent = account;
    select.append(option);
  }
  select.value = accounts.includes(current) ? current : "";
}

function visibleRows() {
  if (!payload) return [];
  const term = $("search").value.trim().toLowerCase();
  const account = $("f-account").value;
  const direction = $("f-direction").value;
  const status = $("f-status").value;

  return payload.rows.filter((row) => {
    if (status === "" && row._reconciled === "no") return false;
    if (status === "dup" && !row.duplicate_group) return false;
    if (account && `${row.owner || "?"} · ${row.account_id || "?"}` !== account) return false;
    if (direction === "out" && !row.paid_out) return false;
    if (direction === "in" && !row.paid_in) return false;
    if (term) {
      const haystack = `${row.description} ${row.type_code} ${row.owner} ${row.source_file}`.toLowerCase();
      if (!haystack.includes(term)) return false;
    }
    return true;
  });
}

function renderRows() {
  const rows = visibleRows();
  const table = $("preview");
  table.innerHTML = "";

  const head = table.createTHead().insertRow();
  for (const [, label] of COLUMNS) {
    const th = document.createElement("th");
    th.textContent = label;
    head.append(th);
  }

  const body = table.createTBody();
  for (const row of rows) {
    const tr = body.insertRow();
    if (row._reconciled === "no") tr.className = "unreconciled";
    if (row.duplicate_group) tr.className += " duplicate";
    for (const [key] of COLUMNS) {
      const td = tr.insertCell();
      const value = row[key] ?? "";
      if (key === "paid_out" || key === "paid_in" || key === "running_balance") {
        td.className = `num ${key === "paid_in" ? "in" : "out"}`;
      }
      if (key === "date_confidence" && value && value !== "certain") {
        td.append(pill("info", value.replace(/_/g, " ")));
        continue;
      }
      if (key === "description") {
        td.className = "desc";
        td.title = value;  // the full text, for anything the cell clips
      }
      td.textContent = key === "date_confidence" && value === "certain" ? "" : value;
    }
  }

  const total = payload ? payload.row_count : 0;
  $("rowcount").textContent =
    `Showing ${rows.length.toLocaleString()} of ${total.toLocaleString()} rows` +
    (payload && payload.truncated ? " (preview capped at 500; the download has them all)" : "") +
    (payload && payload.held_back.length
      ? ` · ${plural(payload.held_back.length, "statement")} held back: ${payload.held_back.join(", ")}`
      : "");
}

["search", "f-account", "f-direction", "f-status"].forEach((id) =>
  $(id).addEventListener("input", renderRows)
);

/* ---------------------------------------------------------------- setup */

(async () => {
  try {
    const { profiles } = await (await fetch("/api/statements/profiles")).json();
    for (const p of profiles) {
      const option = document.createElement("option");
      option.value = p.name;
      option.textContent = `${p.name} — ${p.bank} (${p.currency})`;
      $("profile").append(option);
    }
  } catch {
    setStatus("Could not load the profile list.", true);
  }
})();
