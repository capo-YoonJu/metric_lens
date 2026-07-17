const API = "";

const CONFLICT_LABELS = {
  formula_mismatch: "수식 불일치",
  grain_mismatch: "집계단위 불일치",
  filter_diff: "필터 차이",
  denominator_diff: "분모 개념 차이 (LLM)",
  numerator_diff: "분자 개념 차이 (LLM)",
  synonym: "동의어 (LLM)",
  semantic_diff: "의미 차이 (LLM)",
};

const STATUS_LABELS = {
  running: "실행중",
  awaiting_review: "검토 대기",
  completed: "완료",
  unresolved: "미해결",
  resolved: "해결됨",
  error: "오류",
};

const RESOLUTION_LABELS = {
  wontfix: "보류 (부서별 정의 허용)",
  adopted_a: "A 정의 채택",
  adopted_b: "B 정의 채택",
  merged: "병합된 새 정의 생성",
};

const CONFIDENCE_LABELS = { low: "낮음", medium: "보통", high: "높음" };

// Renders the LLM's proposed standard, if one was generated. Advisory only —
// the human still submits the decision-form below it; nothing here is
// auto-applied.
function recommendationBox(rec) {
  if (!rec || !rec.resolution) return "";
  let html = `
    <div class="recommendation-box">
      <div class="recommendation-head">
        <span class="ai-badge">AI 추천안</span>
        <strong>${escapeHtml(RESOLUTION_LABELS[rec.resolution] || rec.resolution)}</strong>
        ${rec.confidence ? `<span class="muted">확신도: ${escapeHtml(CONFIDENCE_LABELS[rec.confidence] || rec.confidence)}</span>` : ""}
      </div>
      <p>${escapeHtml(rec.rationale || "")}</p>
  `;
  if (rec.merged_definition) {
    html += `<details><summary>병합 정의 초안 보기</summary><pre>${escapeHtml(JSON.stringify(rec.merged_definition, null, 2))}</pre></details>`;
  }
  html += `<p class="hint">참고용 제안이며 최종 결정은 검토자가 아래에서 직접 선택해야 합니다.</p></div>`;
  return html;
}

// ---------------------------------------------------------------- helpers

function el(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

function fmtDate(iso) {
  if (!iso) return "-";
  const d = new Date(iso.includes("Z") || iso.includes("+") ? iso : iso + "Z");
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString("ko-KR", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function statusBadge(status) {
  return `<span class="badge badge-${status}">${STATUS_LABELS[status] || status}</span>`;
}

function conflictTypeBadge(type) {
  return `<span class="conflict-type ${type}">${CONFLICT_LABELS[type] || type}</span>`;
}

let toastTimer = null;
function toast(message, type = "") {
  const t = document.getElementById("toast");
  t.textContent = message;
  t.className = `toast ${type}`;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, 4000);
}

async function api(path, options = {}) {
  const res = await fetch(API + path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const contentType = res.headers.get("content-type") || "";
  const data = contentType.includes("application/json") ? await res.json() : null;
  if (!res.ok) {
    const detail = data && data.detail ? data.detail : `요청 실패 (${res.status})`;
    throw new Error(detail);
  }
  return data;
}

// ---------------------------------------------------------------- tabs

const tabButtons = document.querySelectorAll(".tab-btn");
tabButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    tabButtons.forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(`panel-${btn.dataset.tab}`).classList.add("active");
    if (btn.dataset.tab === "review") loadReview();
    if (btn.dataset.tab === "history") loadHistory();
  });
});

// ---------------------------------------------------------------- 지표 등록

const ingestForm = document.getElementById("ingest-form");
const ingestResult = document.getElementById("ingest-result");
const ingestSubmit = document.getElementById("ingest-submit");

ingestForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const payload = {
    department: document.getElementById("f-department").value.trim(),
    source_type: document.getElementById("f-source-type").value,
    content: document.getElementById("f-content").value.trim(),
  };
  ingestSubmit.disabled = true;
  ingestSubmit.textContent = "실행 중... (LLM 정규화 + 충돌 탐지)";
  ingestResult.classList.remove("empty");
  ingestResult.innerHTML = `<p class="muted">그래프 실행 중입니다...</p>`;

  try {
    const result = await api("/metrics/ingest", { method: "POST", body: JSON.stringify(payload) });
    renderIngestResult(result);
    toast(
      result.status === "awaiting_review"
        ? `충돌 ${result.conflicts.length}건 발견 — HITL 검토 탭에서 결정하세요.`
        : "지표가 등록되었습니다.",
      result.status === "awaiting_review" ? "" : "success"
    );
    loadMetrics();
    if (result.status === "awaiting_review") loadReviewCount();
  } catch (err) {
    ingestResult.innerHTML = `<p style="color:var(--danger)">오류: ${escapeHtml(err.message)}</p>`;
    toast(err.message, "error");
  } finally {
    ingestSubmit.disabled = false;
    ingestSubmit.textContent = "등록 & 충돌 탐지 실행";
  }
});

function renderIngestResult(result) {
  const metric = result.metric || {};
  const conflicts = result.conflicts || [];
  let html = `
    <div class="status-line">${statusBadge(result.status)} <span class="thread-id">thread_id: ${result.thread_id}</span></div>
    <p><strong>${escapeHtml(metric.label || metric.name || "-")}</strong> (<code>${escapeHtml(metric.name || "-")}</code>)</p>
    <table>
      <tr><th>수식</th><td>${escapeHtml(metric.formula_normalized || "-")}</td></tr>
      <tr><th>집계단위</th><td>${escapeHtml(metric.grain || "-")}</td></tr>
      <tr><th>분자 / 분모</th><td>${escapeHtml(metric.numerator || "-")} / ${escapeHtml(metric.denominator || "-")}</td></tr>
      <tr><th>부서</th><td>${escapeHtml(metric.department || "-")}</td></tr>
    </table>
  `;

  if (conflicts.length) {
    html += `<h3 style="margin-top:16px;font-size:0.9rem;">충돌 ${conflicts.length}건 발견</h3>`;
    for (const c of conflicts) {
      html += `
        <div class="conflict-row">
          ${conflictTypeBadge(c.conflict_type)}
          <div>${escapeHtml(c.detail)}</div>
          <div class="meta">${escapeHtml(c.department_a)} (${escapeHtml(c.metric_name_a)}) vs ${escapeHtml(c.department_b)} (${escapeHtml(c.metric_name_b)})</div>
        </div>`;
    }
    html += recommendationBox(result.recommendation);
    html += `<p class="hint">HITL 검토 탭에서 결정을 입력하면 그래프가 재개됩니다.</p>`;
  } else if (result.status === "completed") {
    html += `<p class="muted" style="margin-top:10px;">충돌이 발견되지 않아 즉시 완료되었습니다.</p>`;
  }

  ingestResult.innerHTML = html;
}

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

// ---------------------------------------------------------------- 지표 레지스트리

async function loadMetrics() {
  const box = document.getElementById("metrics-list");
  try {
    const metrics = await api("/metrics");
    if (!metrics.length) {
      box.innerHTML = `<p class="muted">등록된 지표가 없습니다.</p>`;
      return;
    }
    box.innerHTML = `
      <table>
        <thead><tr><th>지표</th><th>부서</th><th>수식</th><th>단위</th><th>분자/분모</th><th>표준</th></tr></thead>
        <tbody>
          ${metrics.map((m) => `
            <tr class="${m.is_standard ? "" : "non-standard-row"}">
              <td><strong>${escapeHtml(m.label)}</strong><br/><code>${escapeHtml(m.name)}</code></td>
              <td>${escapeHtml(m.department)}</td>
              <td>${escapeHtml(m.formula_normalized)}</td>
              <td>${escapeHtml(m.grain)}</td>
              <td>${escapeHtml(m.numerator || "-")} / ${escapeHtml(m.denominator || "-")}</td>
              <td>${m.is_standard ? `<span class="badge badge-standard">표준</span>` : `<span class="muted">-</span>`}</td>
            </tr>`).join("")}
        </tbody>
      </table>`;
  } catch (err) {
    box.innerHTML = `<p style="color:var(--danger)">불러오기 실패: ${escapeHtml(err.message)}</p>`;
  }
}
document.getElementById("refresh-metrics").addEventListener("click", loadMetrics);

// ---------------------------------------------------------------- HITL 검토

async function loadReviewCount() {
  try {
    const conflicts = await api("/conflicts?status=unresolved");
    const threads = new Set(conflicts.map((c) => c.thread_id));
    const badge = document.getElementById("review-count");
    if (threads.size > 0) {
      badge.hidden = false;
      badge.textContent = threads.size;
    } else {
      badge.hidden = true;
    }
    return conflicts;
  } catch {
    return [];
  }
}

async function loadReview() {
  const box = document.getElementById("review-list");
  box.innerHTML = `<p class="muted">불러오는 중...</p>`;
  try {
    const conflicts = await loadReviewCount();
    if (!conflicts.length) {
      box.innerHTML = `<p class="muted">대기 중인 충돌이 없습니다.</p>`;
      return;
    }
    const groups = new Map();
    for (const c of conflicts) {
      if (!groups.has(c.thread_id)) groups.set(c.thread_id, []);
      groups.get(c.thread_id).push(c);
    }
    box.innerHTML = "";
    for (const [threadId, group] of groups) {
      box.appendChild(renderReviewCard(threadId, group));
    }
  } catch (err) {
    box.innerHTML = `<p style="color:var(--danger)">불러오기 실패: ${escapeHtml(err.message)}</p>`;
  }
}

function renderReviewCard(threadId, group) {
  const head = group[0];
  const rec = head.recommended_resolution
    ? { resolution: head.recommended_resolution, rationale: head.recommendation_rationale }
    : null;
  const card = el(`
    <div class="review-card">
      <h3>${escapeHtml(head.metric_name_a)} <span class="muted">vs</span> ${escapeHtml(head.metric_name_b)}</h3>
      <div class="thread-id">thread_id: ${threadId}</div>
      <div class="conflicts"></div>
      ${recommendationBox(rec)}
      <form class="decision-form">
        <label class="full">
          결정
          <select name="resolution">
            <option value="adopted_a">A 채택 — ${escapeHtml(head.department_a)}의 정의</option>
            <option value="adopted_b">B 채택 — ${escapeHtml(head.department_b)}의 정의</option>
            <option value="merged">병합 — 두 정의를 통합한 새 정의</option>
            <option value="wontfix">보류 — 부서별 정의 차이 허용</option>
          </select>
        </label>
        <label class="full">
          검토자
          <input type="text" name="resolved_by" placeholder="예: 데이터거버넌스팀 홍길동" required />
        </label>
        <label class="full">
          메모
          <textarea name="note" rows="2" placeholder="결정 근거를 남겨주세요 (감사 로그에 보존됩니다)"></textarea>
        </label>
        <button type="submit">결정 제출 &amp; 그래프 재개</button>
      </form>
    </div>
  `);

  if (rec) {
    // Pre-select the recommendation as a convenience default — the reviewer
    // can freely change it before submitting; nothing is decided until they do.
    card.querySelector('select[name="resolution"]').value = rec.resolution;
  }

  const conflictsBox = card.querySelector(".conflicts");
  for (const c of group) {
    conflictsBox.appendChild(el(`
      <div class="conflict-row">
        ${conflictTypeBadge(c.conflict_type)}
        <div>${escapeHtml(c.detail)}</div>
        <div class="meta">${escapeHtml(c.department_a)} (${escapeHtml(c.metric_name_a)}) vs ${escapeHtml(c.department_b)} (${escapeHtml(c.metric_name_b)})</div>
      </div>
    `));
  }

  const form = card.querySelector("form");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    const submitBtn = form.querySelector("button");
    submitBtn.disabled = true;
    submitBtn.textContent = "재개 중...";
    try {
      await api(`/conflicts/${threadId}/resume`, {
        method: "POST",
        body: JSON.stringify({
          resolution: fd.get("resolution"),
          note: fd.get("note") || "",
          resolved_by: fd.get("resolved_by"),
        }),
      });
      toast("결정이 반영되어 그래프가 재개되었습니다.", "success");
      loadReview();
      loadMetrics();
    } catch (err) {
      toast(err.message, "error");
      submitBtn.disabled = false;
      submitBtn.textContent = "결정 제출 & 그래프 재개";
    }
  });

  return card;
}

document.getElementById("refresh-review").addEventListener("click", loadReview);

// ---------------------------------------------------------------- 실행 내역

let selectedThreadId = null;

async function loadHistory() {
  const box = document.getElementById("history-list");
  box.innerHTML = `<p class="muted">불러오는 중...</p>`;
  try {
    const runs = await api("/runs");
    if (!runs.length) {
      box.innerHTML = `<p class="muted">실행 내역이 없습니다.</p>`;
      return;
    }
    box.innerHTML = `
      <table>
        <thead><tr><th>thread</th><th>부서</th><th>지표</th><th>상태</th><th>시작</th></tr></thead>
        <tbody>
          ${runs.map((r) => `
            <tr class="clickable ${r.thread_id === selectedThreadId ? "selected" : ""}" data-thread="${r.thread_id}">
              <td><code>${r.thread_id.slice(0, 8)}</code></td>
              <td>${escapeHtml(r.department)}</td>
              <td>${escapeHtml(r.metric_name || "-")}</td>
              <td>${statusBadge(r.status)}</td>
              <td>${fmtDate(r.created_at)}</td>
            </tr>`).join("")}
        </tbody>
      </table>`;
    box.querySelectorAll("tr[data-thread]").forEach((row) => {
      row.addEventListener("click", () => {
        selectedThreadId = row.dataset.thread;
        box.querySelectorAll("tr").forEach((r) => r.classList.remove("selected"));
        row.classList.add("selected");
        loadRunDetail(row.dataset.thread);
      });
    });
  } catch (err) {
    box.innerHTML = `<p style="color:var(--danger)">불러오기 실패: ${escapeHtml(err.message)}</p>`;
  }
}

async function loadRunDetail(threadId) {
  const box = document.getElementById("history-detail");
  box.classList.remove("empty");
  box.innerHTML = `<p class="muted">불러오는 중...</p>`;
  try {
    const data = await api(`/runs/${threadId}`);
    const { run, events, conflicts } = data;

    let html = `
      <div class="status-line">${statusBadge(run.status)} <span class="thread-id">${run.thread_id}</span></div>
      <p><strong>${escapeHtml(run.metric_name || "(정규화 전)")}</strong> — ${escapeHtml(run.department)} / ${escapeHtml(run.source_type)}</p>
      <div class="timeline">
        ${events.map((ev) => `
          <div class="timeline-item">
            <div class="node-name">${escapeHtml(ev.node)}</div>
            <div class="summary">${escapeHtml(ev.summary)}</div>
            <div class="timestamp">${fmtDate(ev.created_at)}</div>
            ${ev.detail ? `<details><summary>상세 (LLM 판단 / 데이터)</summary><pre>${escapeHtml(JSON.stringify(ev.detail, null, 2))}</pre></details>` : ""}
          </div>
        `).join("")}
      </div>
    `;

    if (conflicts.length) {
      html += `<h3 style="font-size:0.9rem;margin-top:16px;">충돌 이력 (${conflicts.length}건)</h3>`;
      for (const c of conflicts) {
        html += `
          <div class="conflict-row">
            ${conflictTypeBadge(c.conflict_type)} ${statusBadge(c.status)}
            <div>${escapeHtml(c.detail)}</div>
            <div class="meta">${escapeHtml(c.department_a)} vs ${escapeHtml(c.department_b)}</div>
            ${c.resolution ? `<div class="meta">결정: ${RESOLUTION_LABELS[c.resolution] || c.resolution} · ${escapeHtml(c.resolved_by || "")} ${c.note ? "· " + escapeHtml(c.note) : ""}</div>` : ""}
          </div>`;
      }
    }

    box.innerHTML = html;
  } catch (err) {
    box.innerHTML = `<p style="color:var(--danger)">불러오기 실패: ${escapeHtml(err.message)}</p>`;
  }
}

document.getElementById("refresh-history").addEventListener("click", () => {
  loadHistory();
  if (selectedThreadId) loadRunDetail(selectedThreadId);
});

// ---------------------------------------------------------------- init

loadMetrics();
loadReviewCount();
