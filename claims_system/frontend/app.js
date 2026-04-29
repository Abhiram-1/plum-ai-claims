const API_BASE = window.location.origin;
const API = {
  submitStructured: `${API_BASE}/claims/submit`,
  submitWithFiles: `${API_BASE}/claims/submit-with-files`,
  runCase: (id) => `${API_BASE}/claims/test/${encodeURIComponent(id)}`,
  runAll: `${API_BASE}/claims/test/run-all`,
  policySummary: `${API_BASE}/policy/summary`,
};

const DOC_TYPES = [
  "PRESCRIPTION",
  "HOSPITAL_BILL",
  "LAB_REPORT",
  "PHARMACY_BILL",
  "DENTAL_REPORT",
  "DIAGNOSTIC_REPORT",
  "DISCHARGE_SUMMARY",
];

const REQUIRED_DOCS = {
  CONSULTATION: ["PRESCRIPTION", "HOSPITAL_BILL"],
  // Per backend/data/policy_terms.json → document_requirements.DIAGNOSTIC.required
  DIAGNOSTIC: ["PRESCRIPTION", "LAB_REPORT", "HOSPITAL_BILL"],
  PHARMACY: ["PRESCRIPTION", "PHARMACY_BILL"],
  DENTAL: ["HOSPITAL_BILL"],
  VISION: ["PRESCRIPTION", "HOSPITAL_BILL"],
  ALTERNATIVE_MEDICINE: ["PRESCRIPTION", "HOSPITAL_BILL"],
};

function toMs(n) {
  const v = Number(n);
  return Number.isFinite(v) ? v : null;
}

function fmtMs(n) {
  const ms = toMs(n);
  if (ms == null) return "—";
  if (ms < 1000) return `~${Math.round(ms)}ms`;
  return `~${(ms / 1000).toFixed(1)}s`;
}

function updateTestsKpis({ total, passed, avgMs } = {}) {
  const totalEl = document.querySelector("#kpiTotalCases");
  const passEl = document.querySelector("#kpiPassRate");
  const barEl = document.querySelector("#kpiPassBar");
  const avgEl = document.querySelector("#kpiAvgTime");

  if (totalEl && total != null) totalEl.textContent = String(total);

  if (passEl && total) {
    const rate = total ? passed / total : 0;
    passEl.textContent = pct(rate);
    if (barEl) barEl.style.width = `${Math.round(rate * 100)}%`;
  }

  if (avgEl) avgEl.textContent = fmtMs(avgMs);
}

function $(sel) {
  const el = document.querySelector(sel);
  if (!el) throw new Error(`Missing element: ${sel}`);
  return el;
}

function setStatus(el, text, kind) {
  el.textContent = text || "";
  if (!text) {
    el.removeAttribute("data-kind");
    return;
  }
  if (kind) el.setAttribute("data-kind", kind);
  else el.removeAttribute("data-kind");
}

function pretty(obj) {
  return JSON.stringify(obj, null, 2);
}

function fmtINR(n) {
  if (n == null || Number.isNaN(Number(n))) return "—";
  try {
    return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(
      Number(n)
    );
  } catch {
    return `₹${Number(n).toFixed(0)}`;
  }
}

function pct(n) {
  if (n == null || Number.isNaN(Number(n))) return "—";
  return `${Math.round(Number(n) * 100)}%`;
}

function safeText(s) {
  return String(s == null ? "" : s);
}

function statusChip(status) {
  const s = String(status || "").toUpperCase();
  if (s === "SUCCESS") return { cls: "chip chip--ok", label: "SUCCESS" };
  if (s === "PARTIAL") return { cls: "chip chip--warn", label: "PARTIAL" };
  if (s === "FAILED") return { cls: "chip chip--bad", label: "FAILED" };
  return { cls: "chip", label: s || "UNKNOWN" };
}

function heroTone(data) {
  const d = String(data?.decision || "").toUpperCase();
  const manual = Boolean(data?.manual_review_recommended);
  if (d === "APPROVED" && !manual) return "ok";
  if (d === "REJECTED" || d === "DOCUMENT_ISSUE") return "bad";
  return "warn";
}

const NOTE_PIPELINE_RE = /pipeline components failed|manual verification is recommended before disbursement/i;
const NOTE_FINANCIAL_RE = /co-pay|network discount|deducted|approved:|₹/i;

function splitApprovalNotes(notes) {
  const pipeline = [];
  const financial = [];
  const other = [];
  for (const raw of notes || []) {
    const n = safeText(raw);
    if (!n) continue;
    if (NOTE_PIPELINE_RE.test(n)) pipeline.push(n);
    else if (NOTE_FINANCIAL_RE.test(n) && !NOTE_PIPELINE_RE.test(n)) financial.push(n);
    else other.push(n);
  }
  return { pipeline, financial, other };
}

function headlineForOutcome(data) {
  const d = String(data?.decision || "").toUpperCase();
  const manual = Boolean(data?.manual_review_recommended);
  if (d === "DOCUMENT_ISSUE") return "Documents need attention";
  if (d === "REJECTED") return "Not approved";
  if (d === "MANUAL_REVIEW") return "Manual review required";
  if (d === "PARTIAL") return "Partially approved";
  if (d === "APPROVED" && manual) return "Approved — ops review";
  if (d === "APPROVED") return "Approved";
  return "Decision";
}

function taglineForOutcome(data) {
  const rs = data?.rejection_reasons;
  if (rs && rs.length) return safeText(rs[0]);
  const d = String(data?.decision || "").toUpperCase();
  if (d === "APPROVED" || d === "PARTIAL") {
    const { financial, other } = splitApprovalNotes(data?.approval_notes);
    if (financial.length) return "Amount breakdown below shows how we reached the approved figure.";
    const pick = other[0];
    if (pick) return safeText(pick);
  }
  return "Expand the agent trace if you need step-by-step checks.";
}

function renderCheckRow(c) {
  const passed = Boolean(c?.passed);
  const row = el("div", { class: `checkRow ${passed ? "checkRow--pass" : "checkRow--fail"}` }, [
    el("span", { class: "checkRow__icon", "aria-hidden": "true" }, passed ? "✓" : "!"),
    el("div", { class: "checkRow__main" }, [
      el("div", { class: "checkRow__name" }, safeText(c?.check_name || "check")),
      el("div", { class: "checkRow__detail" }, safeText(c?.detail || "")),
    ]),
  ]);
  return row;
}

function renderResultHero(data, heroEl) {
  heroEl.className = `resultHero resultHero--${heroTone(data)}`;
  heroEl.textContent = "";
  const metaBits = [
    data?.claim_id ? `Claim ${data.claim_id}` : null,
    data?.member_id ? `Member ${data.member_id}` : null,
    data?.claim_category ? safeText(data.claim_category) : null,
  ].filter(Boolean);
  const ms = data?.processing_time_ms != null ? `${Math.round(Number(data.processing_time_ms))} ms` : null;

  const left = el("div", { class: "resultHero__main" }, [
    el("div", { class: "resultHero__eyebrow" }, "Outcome"),
    el("div", { class: "resultHero__headRow" }, [
      el("h2", { class: "resultHero__headline" }, headlineForOutcome(data)),
      el("span", { class: "confPill", title: "Model confidence" }, pct(data?.confidence_score)),
    ]),
    el("p", { class: "resultHero__lead" }, taglineForOutcome(data)),
    el("div", { class: "resultHero__meta" }, [metaBits.join(" · "), ms].filter(Boolean).join(" · ")),
  ]);

  const right = el("div", { class: "resultHero__figures" }, [
    el("div", { class: "resultHero__fig" }, [
      el("div", { class: "resultHero__figLabel" }, "Approved"),
      el("div", { class: "resultHero__figValue resultHero__figValue--primary" }, fmtINR(data?.approved_amount)),
    ]),
    el("div", { class: "resultHero__fig" }, [
      el("div", { class: "resultHero__figLabel" }, "Claimed"),
      el("div", { class: "resultHero__figValue" }, fmtINR(data?.claimed_amount)),
    ]),
  ]);

  heroEl.appendChild(el("div", { class: "resultHero__top" }, [left, right]));
}

function el(tag, attrs, children) {
  const node = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null) continue;
      if (k === "class") node.className = v;
      else if (k === "html") node.innerHTML = v;
      else node.setAttribute(k, String(v));
    }
  }
  if (children != null) {
    const arr = Array.isArray(children) ? children : [children];
    for (const c of arr) {
      if (c == null) continue;
      if (typeof c === "string") node.appendChild(document.createTextNode(c));
      else node.appendChild(c);
    }
  }
  return node;
}

function renderDecisionView(data) {
  const root = el("div", { class: "outcomeStack" });
  const { pipeline, financial, other } = splitApprovalNotes(data?.approval_notes);
  const alertItems = [];
  for (const p of pipeline) alertItems.push(p);
  if (data?.manual_review_recommended && !pipeline.some((p) => /manual verification/i.test(p))) {
    alertItems.push("Manual verification is recommended before disbursement.");
  }
  for (const f of data?.component_failures || []) alertItems.push(safeText(f));

  const uniq = [];
  const seen = new Set();
  for (const x of alertItems) {
    const k = x.trim().slice(0, 120);
    if (!k || seen.has(k)) continue;
    seen.add(k);
    uniq.push(x.trim());
  }

  if (uniq.length) {
    root.appendChild(
      el("div", { class: "alertStrip", role: "region", "aria-label": "Important notices" }, [
        el("div", { class: "alertStrip__title" }, "Needs attention"),
        el("ul", { class: "alertStrip__list" }, uniq.map((t) => el("li", null, safeText(t)))),
      ])
    );
  }

  const decU = String(data?.decision || "").toUpperCase();
  const allReject = (data?.rejection_reasons || []).filter(Boolean);
  if ((decU === "REJECTED" || decU === "DOCUMENT_ISSUE") && allReject.length > 1) {
    root.appendChild(
      el("div", { class: "noteCard" }, [
        el("div", { class: "noteCard__title" }, "Additional reasons"),
        el("ul", { class: "noteCard__list" }, allReject.slice(1).map((r) => el("li", null, safeText(r)))),
      ])
    );
  }

  const finLines = [...financial, ...other].filter((n) => !NOTE_PIPELINE_RE.test(n));
  if (finLines.length) {
    root.appendChild(
      el("div", { class: "noteCard noteCard--financial" }, [
        el("div", { class: "noteCard__title" }, "Amount breakdown"),
        el("ul", { class: "noteCard__list" }, finLines.map((r) => el("li", null, safeText(r)))),
      ])
    );
  }

  const fraud = data?.fraud_signals;
  if (fraud && fraud.length) {
    root.appendChild(
      el("div", { class: "noteCard" }, [
        el("div", { class: "noteCard__title" }, "Fraud screening"),
        el("ul", { class: "noteCard__list" }, fraud.map((r) => el("li", null, safeText(r)))),
      ])
    );
  }

  const agentBlocks = (data?.agent_traces || []).map((t) => {
    const chip = statusChip(t?.status);
    const warnings = (t?.warnings || []).length;
    const checks = (t?.checks || []).length;
    const dur = t?.duration_ms != null ? `${Math.round(Number(t.duration_ms))} ms` : "—";

    return el("details", { class: "traceItem" }, [
      el("summary", { class: "traceItem__sum" }, [
        el("div", { class: "traceItem__left" }, [
          el("span", { class: chip.cls }, chip.label),
          el("div", { class: "traceName", title: safeText(t?.agent_name) }, safeText(t?.agent_name || "Agent")),
        ]),
        el("div", { class: "traceMeta" }, `${dur} · ${checks} checks · ${warnings} warning(s)`),
      ]),
      el("div", { class: "traceBody" }, [
        el("div", { class: "kv" }, [
          el("div", { class: "kv__k" }, "Started"),
          el("div", { class: "kv__v" }, safeText(t?.started_at || "—")),
          el("div", { class: "kv__k" }, "Completed"),
          el("div", { class: "kv__v" }, safeText(t?.completed_at || "—")),
          el("div", { class: "kv__k" }, "Error"),
          el("div", { class: "kv__v" }, safeText(t?.error || "—")),
        ]),

        (t?.checks || []).length
          ? el("div", { style: "margin-top:10px" }, [
              el("div", { class: "card__title", style: "margin-bottom:8px" }, "Checks"),
              el("div", { class: "checkList" }, (t.checks || []).map((c) => renderCheckRow(c))),
            ])
          : null,

        (t?.warnings || []).length
          ? el("div", { style: "margin-top:10px" }, [
              el("div", { class: "card__title", style: "margin-bottom:8px" }, "Warnings"),
              el("ul", { class: "list" }, (t.warnings || []).map((w) => el("li", null, safeText(w)))),
            ])
          : null,
      ]),
    ]);
  });

  const traceSheet = el("details", { class: "traceSheet" }, [
    el("summary", { class: "traceSheet__summary" }, [
      el("span", { class: "traceSheet__summaryTitle" }, "Agent trace"),
      el(
        "span",
        { class: "traceSheet__summaryMeta" },
        `${(data?.agent_traces?.length ?? 0) || 0} steps · tap to expand`
      ),
    ]),
    el("div", { class: "traceSheet__body" }, [
      el("div", { class: "card card--trace" }, [el("div", { class: "card__bd card__bd--flush" }, agentBlocks)]),
    ]),
  ]);

  root.appendChild(traceSheet);
  return root;
}

function requiredDocsForCategory(claimCategory) {
  return REQUIRED_DOCS[claimCategory] || [];
}

function formatElapsed(sec) {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function renderDocHint(claimCategory) {
  const hint = document.querySelector("#doc_hint");
  if (!hint) return;
  const req = requiredDocsForCategory(claimCategory);
  if (!req.length) {
    hint.textContent = "";
    return;
  }
  hint.innerHTML = `Usually requires: <strong>${req.join(", ")}</strong>`;
}

function guessTypeFromFilename(fileName) {
  const n = (fileName || "").toLowerCase();
  if (!n) return "";
  if (n.includes("prescription") || n.includes("rx") || n.includes("doctor")) return "PRESCRIPTION";
  if (n.includes("lab") || n.includes("report") || n.includes("path")) return "LAB_REPORT";
  if (n.includes("pharma") || n.includes("chemist")) return "PHARMACY_BILL";
  if (n.includes("dental")) return "DENTAL_REPORT";
  if (n.includes("bill") || n.includes("invoice") || n.includes("receipt")) return "HOSPITAL_BILL";
  return "";
}

function defaultTypesForFiles(required, files) {
  // If counts match, map in policy order. Otherwise leave blanks for user selection.
  if (!required?.length || !files?.length) return files.map(() => "");
  if (required.length !== files.length) return files.map(() => "");
  return required.slice();
}

function renderDocAssignments(claimCategory, files, onRemoveAtIndex) {
  const wrap = document.querySelector("#doc_assignments");
  const rows = document.querySelector("#doc_rows");
  const count = document.querySelector("#docCount");
  if (!wrap || !rows) return;

  const list = Array.from(files || []);
  rows.innerHTML = "";

  if (count) count.textContent = list.length ? `${list.length} file(s) selected` : "";

  if (!list.length) {
    wrap.hidden = true;
    return;
  }

  const required = requiredDocsForCategory(claimCategory);
  const defaults = defaultTypesForFiles(required, list);

  for (let i = 0; i < list.length; i++) {
    const f = list[i];
    const row = document.createElement("div");
    row.className = "docRow";

    const name = document.createElement("div");
    name.className = "docRow__name";
    name.textContent = f.name;

    const sel = document.createElement("select");
    sel.className = "input docType";
    sel.dataset.index = String(i);

    const opt0 = document.createElement("option");
    opt0.value = "";
    opt0.textContent = "Select type…";
    sel.appendChild(opt0);

    for (const t of DOC_TYPES) {
      const opt = document.createElement("option");
      opt.value = t;
      opt.textContent = t;
      sel.appendChild(opt);
    }

    const inferred = defaults[i] || guessTypeFromFilename(f.name);
    if (inferred) sel.value = inferred;

    const rm = document.createElement("button");
    rm.type = "button";
    rm.className = "btn btn--ghost btn--icon";
    rm.title = "Remove file";
    rm.setAttribute("aria-label", `Remove ${f.name}`);
    rm.textContent = "✕";
    rm.addEventListener("click", () => onRemoveAtIndex?.(i));

    row.appendChild(name);
    row.appendChild(sel);
    row.appendChild(rm);
    rows.appendChild(row);
  }

  wrap.hidden = false;
}

function showRoute(route) {
  const routes = ["submit", "tests", "policy"];
  for (const r of routes) {
    const panel = $(`#route-${r}`);
    panel.hidden = r !== route;
  }
  for (const btn of document.querySelectorAll(".navbtn")) {
    if (btn.dataset.route === route) btn.setAttribute("aria-current", "page");
    else btn.removeAttribute("aria-current");
  }
  // UI is served under /ui/, so avoid rewriting the pathname to "/".
  history.replaceState({}, "", route === "submit" ? "#submit" : `#${route}`);
}

function getRouteFromHash() {
  const h = (location.hash || "").replace("#", "");
  if (h === "tests" || h === "policy") return h;
  if (h === "submit") return "submit";
  return "submit";
}

async function fetchJson(url, opts) {
  const timeoutMs = opts?.timeoutMs ?? 600000; // 10 minutes (vision extraction can be slow)
  const { timeoutMs: _drop, ...fetchOpts } = opts || {};

  const controller = new AbortController();
  const t = setTimeout(() => controller.abort(), timeoutMs);

  try {
    console.log('Fetching:', url, 'with options:', fetchOpts);
    const res = await fetch(url, { ...(fetchOpts || {}), signal: controller.signal });
    console.log('Response status:', res.status, res.statusText);
    const text = await res.text();
    console.log('Response text length:', text.length);
    let data = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch (parseError) {
      console.error('JSON parse error:', parseError, 'Raw text:', text.substring(0, 200));
      data = { raw: text };
    }
    if (!res.ok) {
      const msg = data?.detail ? String(data.detail) : `Request failed (${res.status})`;
      console.error('Request failed:', msg, data);
      throw new Error(msg);
    }
    console.log('Successfully parsed response:', data);
    return data;
  } catch (e) {
    console.error('Fetch error:', e);
    if (e?.name === "AbortError") {
      throw new Error(`Request timed out after ${Math.round(timeoutMs / 1000)}s. The server may still be processing your documents—please try again in a moment.`);
    }
    throw e;
  } finally {
    clearTimeout(t);
  }
}

function initNav() {
  for (const btn of document.querySelectorAll(".navbtn")) {
    btn.addEventListener("click", () => showRoute(btn.dataset.route));
  }
  showRoute(getRouteFromHash());
  window.addEventListener("hashchange", () => showRoute(getRouteFromHash()));
}

function initSubmitForm() {
  const form = $("#claimForm");
  const status = $("#submitStatus");
  const result = $("#result");
  const resultLoader = $("#resultLoader");
  const resultBody = $("#resultBody");
  const resultHero = $("#resultHero");
  const resultJson = $("#resultJson");
  const decisionView = $("#decisionView");
  const btnToggleRaw = $("#btnToggleRaw");
  const btnDownloadJson = $("#btnDownloadJson");
  const btnSubmit = $("#btnSubmit");
  const btnClear = $("#btnClear");
  const btnAddDoc = $("#btnAddDoc");

  const docFiles = $("#doc_files");
  const docAssignments = $("#doc_assignments");
  const docRows = $("#doc_rows");

  const selectedFiles = [];

  const refreshDocsUI = () => {
    renderDocAssignments(form.claim_category.value, selectedFiles, (idx) => {
      selectedFiles.splice(idx, 1);
      refreshDocsUI();
    });
  };

  function setSubmitBusy(busy) {
    form.classList.toggle("form--busy", busy);
    btnSubmit.disabled = busy;
    btnClear.disabled = busy;
    const label = btnSubmit.querySelector(".btn__label");
    if (busy) {
      if (!btnSubmit.querySelector(".btn__spinner")) {
        btnSubmit.insertBefore(el("span", { class: "btn__spinner", "aria-hidden": "true" }), btnSubmit.firstChild);
      }
      if (label) label.textContent = "Processing…";
    } else {
      btnSubmit.querySelector(".btn__spinner")?.remove();
      if (label) label.textContent = "Submit claim";
    }
  }

  function resetResultDock() {
    result.hidden = true;
    resultLoader.hidden = true;
    resultBody.hidden = true;
    resultJson.textContent = "";
    resultJson.hidden = true;
    btnToggleRaw.textContent = "Show raw JSON";
    decisionView.textContent = "";
    resultHero.textContent = "";
  }

  btnClear.addEventListener("click", () => {
    form.reset();
    resetResultDock();
    setSubmitBusy(false);
    setStatus(status, "", "");
    docRows.textContent = "";
    docAssignments.hidden = true;
    selectedFiles.splice(0, selectedFiles.length);
    const count = document.querySelector("#docCount");
    if (count) count.textContent = "";
    const td = form.querySelector('input[name="treatment_date"]');
    if (td) td.value = new Date().toISOString().slice(0, 10);
  });

  // Default date = today
  const td = form.querySelector('input[name="treatment_date"]');
  if (td && !td.value) td.value = new Date().toISOString().slice(0, 10);

  const cat = form.querySelector('select[name="claim_category"]');
  if (cat) {
    renderDocHint(cat.value);
    cat.addEventListener("change", () => {
      renderDocHint(cat.value);
      refreshDocsUI();
    });
  }

  btnAddDoc.addEventListener("click", () => {
    docFiles.click();
  });

  docFiles.addEventListener("change", () => {
    const file = (docFiles.files && docFiles.files[0]) || null;
    if (file) {
      selectedFiles.push(file);
      // allow selecting the same file again later if needed
      docFiles.value = "";
      refreshDocsUI();
      setStatus(status, "", "");
    }
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    resetResultDock();

    const fd = new FormData();
    const member_id = form.member_id.value.trim();
    const policy_id = form.policy_id.value.trim();
    const claim_category = form.claim_category.value;
    const treatment_date = form.treatment_date.value;
    const claimed_amount = form.claimed_amount.value;
    const hospital_name = form.hospital_name.value.trim();
    const document_types_json = (form.document_types_json?.value || "").trim();

    fd.append("member_id", member_id);
    fd.append("policy_id", policy_id);
    fd.append("claim_category", claim_category);
    fd.append("treatment_date", treatment_date);
    fd.append("claimed_amount", claimed_amount);
    if (hospital_name) fd.append("hospital_name", hospital_name);

    const files = Array.from(selectedFiles || []);
    if (!files.length) {
      setStatus(status, "Please choose one or more documents to upload.", "err");
      return;
    }

    const required = requiredDocsForCategory(claim_category);
    if (files.length === 0) {
      setStatus(status, "Please select at least one document to upload.", "err");
      return;
    }
    
    // For most categories, 1-2 documents are sufficient
    // The backend will validate specific requirements
    if (files.length > 5) {
      setStatus(status, "Too many files selected. Please upload only relevant medical documents.", "err");
      return;
    }

    let typesJson = document_types_json;
    if (typesJson) {
      let parsedTypes = null;
      try {
        parsedTypes = JSON.parse(typesJson);
      } catch {
        setStatus(status, "Advanced JSON type override is not valid JSON.", "err");
        return;
      }
      if (!Array.isArray(parsedTypes)) {
        setStatus(status, "Advanced JSON type override must be a JSON array.", "err");
        return;
      }
      if (parsedTypes.length !== files.length) {
        setStatus(
          status,
          `Advanced JSON type override has ${parsedTypes.length} entries but you uploaded ${files.length} file(s). They must match.`,
          "err"
        );
        return;
      }
    }

    if (!typesJson) {
      const selects = Array.from(document.querySelectorAll("select.docType"));
      if (selects.length !== files.length) {
        setStatus(status, "Please add your documents again so type assignment rows appear.", "err");
        return;
      }
      const chosenTypes = selects.map((s) => (s.value || "").trim());
      if (chosenTypes.some((t) => !t)) {
        setStatus(status, "Please choose a document type for every uploaded file.", "err");
        return;
      }

      // Validate required set (order-independent)
      const need = new Map();
      for (const t of required) need.set(t, (need.get(t) || 0) + 1);
      const have = new Map();
      for (const t of chosenTypes) have.set(t, (have.get(t) || 0) + 1);

      let ok = true;
      const missing = [];
      for (const [t, c] of need.entries()) {
        if ((have.get(t) || 0) < c) {
          ok = false;
          missing.push(t);
        }
      }
      if (!ok) {
        setStatus(
          status,
          `Missing required document(s): ${missing.join(", ")}. For ${claim_category} claims, you need: ${required.join(", ")}`,
          "err"
        );
        return;
      }

      typesJson = JSON.stringify(chosenTypes);
    }

    if (typesJson) fd.append("document_types_json", typesJson);

    for (const f of files) fd.append("documents", f, f.name);

    let elapsedSec = 0;
    const submitStatusMsg = () =>
      setStatus(
        status,
        `Working… ${formatElapsed(elapsedSec)} — vision extraction runs on the server (often ~1–3 minutes per file).`,
        ""
      );
    submitStatusMsg();
    const statusTick = setInterval(() => {
      elapsedSec += 1;
      submitStatusMsg();
    }, 1000);

    result.hidden = false;
    resultLoader.hidden = false;
    resultBody.hidden = true;
    setSubmitBusy(true);
    result.scrollIntoView({ behavior: "smooth", block: "nearest" });

    try {
      const data = await fetchJson(API.submitWithFiles, {
        method: "POST",
        body: fd,
        timeoutMs: 600000,
      });

      console.log('Processing response data:', data);
      renderResultHero(data, resultHero);
      decisionView.textContent = "";
      decisionView.appendChild(renderDecisionView(data));
      resultJson.textContent = pretty(data);
      resultLoader.hidden = true;
      resultBody.hidden = false;
      setStatus(status, "Done — review the outcome below.", "ok");
      console.log('UI should now show results');

      btnToggleRaw.onclick = () => {
        const show = resultJson.hidden;
        resultJson.hidden = !show;
        btnToggleRaw.textContent = show ? "Hide raw JSON" : "Show raw JSON";
      };
      btnDownloadJson.onclick = () => {
        const blob = new Blob([pretty(data)], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `${safeText(data?.claim_id || "claim")}.json`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 250);
      };

      requestAnimationFrame(() => {
        result.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    } catch (err) {
      resetResultDock();
      setStatus(status, err.message || "Submit failed.", "err");
    } finally {
      clearInterval(statusTick);
      setSubmitBusy(false);
    }
  });
}

function initTests() {
  const status = $("#testsStatus");
  const dock = $("#testsResult");
  const loader = $("#testsLoader");
  const body = $("#testsBody");
  const hero = $("#testsHero");
  const decision = $("#testsDecision");
  const out = $("#testsOut");
  const btnToggleRaw = $("#btnTestsToggleRaw");
  const btnDownloadJson = $("#btnTestsDownloadJson");

  $("#runCase").addEventListener("click", async () => {
    out.textContent = "";
    out.hidden = true;
    dock.hidden = false;
    loader.hidden = false;
    body.hidden = true;
    setStatus(status, "Running…", "");
    const id = $("#caseId").value.trim().toUpperCase();
    
    // Simple connectivity test first
    try {
      await fetch('/health');
      console.log('Server connectivity: OK');
    } catch (e) {
      console.error('Server connectivity failed:', e);
      loader.hidden = true;
      dock.hidden = true;
      setStatus(status, "Cannot connect to server. Please check if the backend is running.", "err");
      return;
    }
    
    try {
      console.log('Running test case:', id, 'URL:', API.runCase(id));
      const data = await fetchJson(API.runCase(id), { method: "POST" });
      console.log('Test case result:', data);
      renderResultHero(data, hero);
      decision.textContent = "";
      decision.appendChild(renderDecisionView(data));
      out.textContent = pretty(data);
      loader.hidden = true;
      body.hidden = false;
      setStatus(status, `Done (${id}).`, "ok");

      btnToggleRaw.onclick = () => {
        const show = out.hidden;
        out.hidden = !show;
        btnToggleRaw.textContent = show ? "Hide raw JSON" : "Show raw JSON";
      };
      btnDownloadJson.onclick = () => {
        const blob = new Blob([pretty(data)], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `${safeText(data?.claim_id || id || "test")}.json`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 250);
      };
    } catch (err) {
      console.error('Test case error:', err);
      loader.hidden = true;
      dock.hidden = true;
      setStatus(status, err.message || "Run failed.", "err");
    }
  });

  $("#runAll").addEventListener("click", async () => {
    out.textContent = "";
    out.hidden = false;
    dock.hidden = true;
    setStatus(status, "Running all cases…", "");
    try {
      const data = await fetchJson(API.runAll, { method: "POST" });
      out.textContent = pretty(data);
      if (Array.isArray(data)) {
        const total = data.length;
        const passed = data.filter((r) => r && r.matched === true).length;
        const msList = data.map((r) => toMs(r?.processing_time_ms)).filter((x) => x != null);
        const avgMs = msList.length ? msList.reduce((a, b) => a + b, 0) / msList.length : null;
        updateTestsKpis({ total, passed, avgMs });
      }
      setStatus(status, "Done (all cases).", "ok");
    } catch (err) {
      setStatus(status, err.message || "Run failed.", "err");
    }
  });
}

function initPolicy() {
  const status = $("#policyStatus");
  const out = $("#policyOut");

  $("#loadPolicy").addEventListener("click", async () => {
    out.textContent = "";
    out.hidden = true;
    setStatus(status, "Loading…", "");
    try {
      const data = await fetchJson(API.policySummary, { method: "GET" });
      out.textContent = pretty(data);
      out.hidden = false;
      setStatus(status, "Loaded.", "ok");
    } catch (err) {
      setStatus(status, err.message || "Load failed.", "err");
      out.hidden = true;
    }
  });
}

initNav();
initSubmitForm();
initTests();
initPolicy();

