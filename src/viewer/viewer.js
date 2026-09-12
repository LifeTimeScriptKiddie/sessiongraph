(() => {
  const $ = id => document.getElementById(id);
  const initial = JSON.parse($("capture-data").textContent);
  let data = initial, graph, view, selected, result = null, tape = null, selectedStepId = null, mode = "activity";
  const buttons = new Map();
  const rowButtons = new Map();
  const element = (tag, text, className) => { const e = document.createElement(tag); if (text !== undefined) e.textContent = text; if (className) e.className = className; return e; };
  const relation = { observed_text_match: "text matched at captured boundary", summary_ancestor: "recorded summary ancestor", recorded_parent: "recorded parent (not inclusion proof)", response_to: "response associated with request" };
  function setStatus(text) { $("load-status").textContent = text || ""; }
  function resolveStepText(step) {
    const ev = step?.event;
    if (ev && typeof ev.rawText === "string" && ev.rawText.length) {
      return { text: ev.rawText, source: "rawText", path: ev.sourcePath || step.path || null, truncated: false, bytes: ev.byteCount ?? ev.rawText.length };
    }
    const sources = data.sources;
    if (!sources) return null;
    const byId = sources.byEventId?.[step.eventId];
    if (byId?.text) return { text: byId.text, source: "embed", path: byId.path || step.path || null, truncated: !!byId.truncated, bytes: byId.bytes };
    const path = step.path || ev?.sourcePath || (typeof ev?.sourceAlias === "string" && ev.sourceAlias.includes("/") ? ev.sourceAlias : null);
    if (path && sources.byPath?.[path]?.text) {
      const hit = sources.byPath[path];
      return { text: hit.text, source: "path", path, truncated: !!hit.truncated, bytes: hit.bytes };
    }
    return null;
  }
  function clock(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return String(iso).slice(11, 19) || iso;
    return d.toISOString().slice(11, 19);
  }
  function turnIdsFromTape() {
    return tape?.turns?.slice() || [];
  }
  function setMode(next) {
    mode = next;
    $("mode-activity").setAttribute("aria-pressed", String(next === "activity"));
    $("mode-provenance").setAttribute("aria-pressed", String(next === "provenance"));
    $("activity-view").hidden = next !== "activity";
    $("provenance-view").hidden = next !== "provenance";
    $("page-extras").hidden = next !== "provenance";
    $("header-mode").textContent = next === "activity" ? "Activity tape · local only" : "Provenance inspector · local only";
    if (next === "provenance") {
      const picker = $("request-picker");
      if (graph.requests.length) showRequest(picker.value || graph.requests[0].id);
      else showInventory(picker.value || "");
      requestAnimationFrame(drawEdges);
    }
  }
  function fillPicker() {
    $("request-picker").replaceChildren();
    const all = element("option", "All turns");
    all.value = "";
    $("request-picker").append(all);
    if (mode === "provenance" && graph.requests.length) {
      for (const req of graph.requests) {
        const node = graph.nodes.find(n => n.id === req.id);
        const option = element("option", `${req.label} · ${req.attempt || "attempt unknown"} · ${node.event.evidence}`);
        option.value = req.id;
        $("request-picker").append(option);
      }
    } else {
      for (const id of turnIdsFromTape()) {
        const option = element("option", `Turn ${id}`);
        option.value = id;
        $("request-picker").append(option);
      }
    }
  }
  function load(next) {
    const projected = buildProvenanceGraph(next.events);
    graph = projected; data = next;
    tape = buildActivityTape(next.events);
    $("dataset-label").textContent = next.label || "Local recorded events";
    $("error").hidden = true;
    const c = tape.counts;
    setStatus(`Loaded ${c.events} events → ${c.steps} activity steps · input ${c.input} · process ${c.process} · boundary ${c.boundary} · outcome ${c.outcome} · health ${c.health}`);
    fillPicker();
    $("issue-list").replaceChildren();
    for (const i of graph.issues) $("issue-list").append(element("li", `${i.code}: ${i.message}${i.eventId ? ` [${i.eventId}]` : ""}`));
    if (!graph.issues.length) $("issue-list").append(element("li", "No structural gap detected by these checks. Completeness is not certified."));
    result = null; $("study-result").textContent = ""; $("download-result").hidden = true;
    if (mode === "provenance") setMode("provenance");
    else setMode("activity");
    fillPicker();
    renderActivity($("request-picker").value || "");
  }
  function filteredSteps(turn) {
    return tape.steps.filter(s => !turn || s.requestId === turn);
  }
  function renderActivity(turn) {
    const steps = filteredSteps(turn);
    rowButtons.clear();
    $("activity-list").replaceChildren();
    $("activity-summary").textContent = turn
      ? `${steps.length} steps in turn ${turn}`
      : `${steps.length} steps · ${tape.turns.length} turn${tape.turns.length === 1 ? "" : "s"}`;
    if (!steps.length) {
      $("activity-list").append(element("li", "No activity steps in this filter.", "empty"));
      clearDetail();
      return;
    }
    for (const step of steps) {
      const li = element("li");
      const btn = element("button", undefined, "activity-row");
      btn.type = "button";
      btn.setAttribute("aria-pressed", "false");
      btn.dataset.eventId = step.eventId;
      btn.append(
        element("span", clock(step.wallTime), "time"),
        element("span", step.phase, `phase ${step.phase}`),
        element("span", step.agentRuntime, "agent"),
        element("span", step.title, "title"),
        element("span", step.evidence, "evidence"),
      );
      btn.addEventListener("click", () => selectStep(step.eventId));
      li.append(btn);
      $("activity-list").append(li);
      rowButtons.set(step.eventId, btn);
    }
    const prefer = selectedStepId && steps.some(s => s.eventId === selectedStepId)
      ? selectedStepId
      : (steps.find(s => s.phase === "outcome") || steps[steps.length - 1]).eventId;
    selectStep(prefer);
  }
  function clearDetail() {
    selectedStepId = null;
    $("detail-title").textContent = "Select a step";
    $("detail-phase").textContent = "";
    $("detail-empty").hidden = false;
    $("detail-sections").hidden = true;
    $("detail-sections").replaceChildren();
  }
  function section(title, slot) {
    const wrap = element("section", undefined, `detail-section slot-${slot}`);
    wrap.append(element("h3", title));
    return wrap;
  }
  function dl(pairs) {
    const grid = element("dl", undefined, "details-grid");
    for (const [label, value] of pairs) {
      if (value == null || value === "") continue;
      grid.append(element("dt", label), element("dd", String(value)));
    }
    return grid;
  }
  function selectStep(id) {
    const step = tape.steps.find(s => s.eventId === id);
    if (!step) return;
    selectedStepId = id;
    for (const [key, btn] of rowButtons) btn.setAttribute("aria-pressed", String(key === id));
    $("detail-title").textContent = step.title;
    $("detail-phase").textContent = `${step.agentRuntime} · ${clock(step.wallTime)}`;
    $("detail-empty").hidden = true;
    $("detail-sections").hidden = false;
    const root = $("detail-sections");
    root.replaceChildren();

    const leadWrap = element("div", undefined, "detail-section slot-lead");
    const lead = element("div", undefined, "detail-lead");
    lead.append(element("span", step.phase, `badge ${step.phase}`));
    lead.append(element("span", step.evidence));
    if (step.requestId) lead.append(element("span", step.requestId));
    leadWrap.append(lead);

    const what = section("What", "what");
    what.append(dl([
      ["Agent", step.agentRuntime],
      ["Adapter", `${step.adapterId}${step.event?.adapterVersion ? ` ${step.event.adapterVersion}` : ""}`],
      ["Agent id", step.agentId],
      ["Boundary", step.boundary],
      ["Derived", step.derived ? "projected gap (not stored)" : "recorded event"],
    ]));

    const rangeLabel = step.range
      ? (step.range.unit === "line"
        ? `L${step.range.start}–L${step.range.end}`
        : `bytes [${step.range.start}, ${step.range.end})`)
      : "not recorded";
    const where = section("Where", "where");
    where.append(dl([
      ["Path", step.path || "—"],
      ["Span", rangeLabel],
      ["Span rule", step.range?.unit === "line" ? "runtime lines only" : step.range ? "bytes — not attention" : "no span from adapter"],
      ["Tool call", step.toolCallId || "—"],
      ["Request", step.requestId || "unknown"],
      ["Attempt", step.attemptId || "unknown"],
    ]));

    const message = section("Harness text", "message");
    const resolved = resolveStepText(step);
    if (resolved?.text) {
      const meta = element("p", undefined, "notice");
      meta.textContent = [
        resolved.source === "rawText" ? "From capture" : resolved.source === "embed" ? "Embedded at HTML build" : "Embedded by path",
        resolved.path ? `· ${resolved.path}` : "",
        resolved.truncated ? "· truncated" : "",
        `· ${resolved.bytes ?? resolved.text.length} bytes`,
      ].filter(Boolean).join(" ");
      message.append(meta);
      const body = resolved.text.length > 12000
        ? `${resolved.text.slice(0, 12000)}\n… truncated for display …`
        : resolved.text;
      message.append(element("pre", body, "message-box"));
    } else if (step.phase === "input" && (step.path || step.event?.sourceCategory === "system_input")) {
      message.append(element("p",
        step.event?.sourceCategory === "system_input"
          ? "Assembled system prompt was redacted at capture. Rebuild after ISEEAGENTS_PERSIST_HARNESS_TEXT=1, or enable that flag and /reload."
          : `Path known${step.path ? ` (${step.path})` : ""}, but text was not embedded. Rebuild with: npm run graph -- CAPTURE.jsonl --out VIEW.html`,
        "message-box"));
    } else if (step.phase === "outcome") {
      message.append(element("p",
        step.event?.rawText
          ? step.event.rawText
          : "Assistant text omitted (default policy). Metadata only.",
        "message-box"));
    } else {
      message.append(element("p",
        step.hasMessagePreview
          ? "Preview present under capture policy."
          : "No harness text for this step.",
        "message-box"));
    }

    const links = section("Links", "links");
    const ul = element("ul", undefined, "links");
    if (step.parentEventIds?.length) {
      for (const pid of step.parentEventIds) ul.append(element("li", `parent → ${pid}`));
    } else {
      ul.append(element("li", "No parent links."));
    }
    ul.append(element("li", `Turn ${step.requestId || "none"} · association, not influence`));
    if (step.phase === "boundary") ul.append(element("li", "Switch to Provenance for inclusion edges."));
    links.append(ul);

    const evidence = section("Evidence", "evidence");
    evidence.append(dl([
      ["Grade", step.evidence],
      ["Coverage", step.coverage],
      ["matchMethod", step.matchMethod || "—"],
      ["Ambiguity", step.ambiguity || "—"],
      ["Unsupported", step.unsupportedBoundary || "—"],
      ["Event ID", step.eventId],
    ]));

    const usage = section("Usage", "usage");
    const number = n => n == null ? "—" : String(n);
    usage.append(dl([
      ["Input", number(step.usageInputTokens)],
      ["Cached", number(step.usageCachedTokens)],
      ["Output", number(step.usageOutputTokens)],
    ]));
    usage.append(element("p", "Missing counters ≠ zero usage.", "notice"));

    const sg = data.sessiongraph;
    const sgSec = section("SessionGraph", "session");
    const sgList = element("ul", undefined, "links");
    if (!sg) sgList.append(element("li", "Not attached."));
    else {
      const nodeIds = new Set((sg.graph?.nodes || []).map(n => n.id));
      const joined = graph.events.filter(e => nodeIds.has(e.eventId)).length;
      sgList.append(element("li", `${joined}/${graph.events.length} eventIds joined · recorded structure only`));
      appendStructuralMetrics(sgList);
      for (const f of sg.findings || []) sgList.append(element("li", `${f.code}: ${f.summary}`));
      if (!sg.findings?.length) sgList.append(element("li", "No findings."));
    }
    sgSec.append(sgList);

    root.append(leadWrap, what, evidence, where, usage, message, links, sgSec);
  }

  function nodeButton(node) {
    const matched = view?.matches?.some(e => e.from === node.id), ancestor = view?.ancestors?.includes(node.id);
    const button = element("button", undefined, "node" + (matched ? " matched" : ancestor ? " ancestral" : ""));
    button.type = "button"; button.setAttribute("aria-pressed", "false");
    button.append(element("small", node.category), element("strong", node.label));
    const status = node.kind === "source" || node.kind === "transform"
      ? matched ? "Matched to this captured snapshot" : ancestor ? "Summary ancestor · not a direct match" : "Observed in session · inclusion unproven"
      : node.kind === "request" ? node.event.evidence === "final_dispatch" ? "Producer-declared final capture" : "Snapshot only · later changes possible"
      : "Response observed · raw text omitted";
    button.append(element("small", status));
    button.addEventListener("click", () => selectNode(node.id)); buttons.set(node.id, button); return button;
  }
  function showRequest(id) {
    view = inspectRequest(graph, id); buttons.clear();
    for (const part of ["source", "transform", "request", "response"]) $(`${part}-nodes`).replaceChildren();
    for (const node of view.candidates.filter(n => n.kind === "source")) $("source-nodes").append(nodeButton(node));
    for (const node of view.candidates.filter(n => n.kind === "transform" && view.ancestors.includes(n.id))) $("transform-nodes").append(nodeButton(node));
    $("request-nodes").append(nodeButton(view.request));
    for (const node of view.responses) $("response-nodes").append(nodeButton(node));
    if (!$("source-nodes").children.length) $("source-nodes").append(element("div", "No source observations recorded", "empty-node"));
    if (!$("transform-nodes").children.length) $("transform-nodes").append(element("div", "No linked transformation recorded", "empty-node"));
    if (!view.responses.length) $("response-nodes").append(element("div", "Output not recorded. Usage counters do not provide the result text.", "empty-node"));
    $("request-summary").textContent = `${view.matches.length} recorded match edge${view.matches.length === 1 ? "" : "s"} · ${view.request.event.boundary}`;
    $("output-summary").textContent = view.outputStatus;
    $("coverage-summary").textContent = `Payload coverage: ${view.request.event.coverage}. ${view.request.event.evidence === "final_dispatch" ? "The producer labels this capture final; this viewer does not independently verify transport." : "This snapshot may be changed by later handlers before dispatch."} Unlinked inputs are other observations in this session, not proof of inclusion or omission.`;
    $("usage-list").replaceChildren();
    const number = n => n == null ? "unknown" : String(n);
    for (const e of view.usage) $("usage-list").append(element("li", `${e.boundary}: input ${number(e.usageInputTokens)}, cached ${number(e.usageCachedTokens)}, output ${number(e.usageOutputTokens)}. Counter scope is supplied by the adapter.`));
    if (!view.usage.length) $("usage-list").append(element("li", "No usage record associated with this request identity."));
    fillSessiongraphFindings();
    selectNode(id); requestAnimationFrame(drawEdges);
  }
  function fillSessiongraphFindings() {
    $("sessiongraph-findings").replaceChildren();
    const sg = data.sessiongraph;
    if (!sg) $("sessiongraph-findings").append(element("li", "No SessionGraph analysis attached. Provenance checks above are local."));
    else {
      const nodeIds = new Set((sg.graph?.nodes || []).map(n => n.id));
      const joined = graph.events.filter(e => nodeIds.has(e.eventId)).length;
      $("sessiongraph-findings").append(element("li", `${joined}/${graph.events.length} event IDs joined. SessionGraph findings concern graph/session health, not semantic influence.`));
      appendStructuralMetrics($("sessiongraph-findings"));
      for (const f of sg.findings || []) $("sessiongraph-findings").append(element("li", `${f.code}: ${f.summary}`));
      if (!sg.findings?.length) $("sessiongraph-findings").append(element("li", "No SessionGraph finding; this does not prove capture completeness."));
    }
  }
  function appendStructuralMetrics(list) {
    const report = data.sessiongraphMetrics, m = report?.metrics;
    if (!m) {
      list.append(element("li", "No NetworkX structural metrics attached."));
      return;
    }
    const value = n => n == null ? "unknown" : String(n);
    const percent = n => typeof n === "number" ? `${Math.round(n * 100)}%` : "not measured";
    list.append(element("li", `Structure: ${value(m.declared_nodes)} nodes, ${value(m.edges)} edges, ${value(m.weakly_connected_components)} component(s), depth ${value(m.max_depth)}.`));
    list.append(element("li", `Cycles: ${value(m.cycle_nodes)} node(s); request→output coverage ${percent(m.request_output_coverage)}; changed-artifact verification ${percent(m.artifact_verification_coverage)}.`));
    const relations = Object.entries(m.relation_counts || {}).map(([name, count]) => `${name} ${count}`).join(", ");
    if (relations) list.append(element("li", `Recorded relations: ${relations}.`));
    list.append(element("li", "These measurements describe recorded provenance structure; they do not establish correctness, attention, or semantic influence."));
  }
  function selectNode(id) {
    selected = id; const node = graph.nodes.find(n => n.id === id); if (!node) return;
    for (const [key, button] of buttons) button.setAttribute("aria-pressed", String(key === id));
    $("prov-detail-title").textContent = node.label;
    $("node-detail").replaceChildren();
    const e = node.event;
    for (const [label, value] of [["Observation", e.observation], ["Evidence", e.evidence], ["Coverage", e.coverage], ["Boundary", e.boundary], ["Request / attempt", `${e.requestId || "unknown"} / ${e.attemptId || "unknown"}`], ["Adapter", `${e.adapterId} ${e.adapterVersion || ""}`], ["Source version", e.contentVersionKey || "not recorded"], ["Source estimate", e.estimatedTokens == null ? "unknown" : `${e.estimatedTokens} tokens (not request allocation)`], ["Event ID", e.eventId]]) {
      $("node-detail").append(element("dt", label), element("dd", String(value)));
    }
    $("edge-list").replaceChildren();
    for (const edge of graph.edges.filter(edge => edge.from === id || edge.to === id)) {
      const from = graph.nodes.find(n => n.id === edge.from), to = graph.nodes.find(n => n.id === edge.to);
      const evidence = graph.events.find(e => e.eventId === edge.evidenceId);
      const label = node => `${node.label} [${node.event.requestId || "request unknown"}; ${node.event.attemptId || "attempt unknown"}]`;
      let text = `${label(from)} → ${label(to)}: ${relation[edge.kind]}.`;
      if (edge.kind === "observed_text_match") text += ` ${evidence.matchMethod}; source bytes [${evidence.sourceSpan.start}, ${evidence.sourceSpan.end}), field bytes [${evidence.requestSpan.start}, ${evidence.requestSpan.end}).${edge.ambiguous ? " Ambiguous: another source matches this span." : ""}`;
      text += ` Evidence: ${edge.evidenceId}`;
      $("edge-list").append(element("li", text));
    }
    if (!$("edge-list").children.length) $("edge-list").append(element("li", "No recorded relationship. Position and timestamp do not establish input consumption."));
  }
  function showInventory(filterValue) {
    const turn = filterValue.startsWith("turn:") ? filterValue.slice(5) : filterValue;
    buttons.clear();
    for (const part of ["source", "transform", "request", "response"]) $(`${part}-nodes`).replaceChildren();
    const inTurn = n => !turn || n.event.requestId === turn;
    const sources = graph.nodes.filter(n => n.kind === "source" && inTurn(n));
    const transforms = graph.nodes.filter(n => n.kind === "transform" && inTurn(n));
    const responses = graph.nodes.filter(n => n.kind === "response" && inTurn(n));
    view = { matches: [], ancestors: [], request: null, responses, candidates: sources, usage: [], outputStatus: responses.length ? "Response observed; no payload snapshot to join" : "Output not recorded", unmatched: sources };
    for (const node of sources.slice(0, 80)) $("source-nodes").append(nodeButton(node));
    if (sources.length > 80) $("source-nodes").append(element("div", `Showing 80 of ${sources.length} source observations`, "empty-node"));
    for (const node of transforms.slice(0, 40)) $("transform-nodes").append(nodeButton(node));
    if (!sources.length) $("source-nodes").append(element("div", "No source observations recorded", "empty-node"));
    if (!transforms.length) $("transform-nodes").append(element("div", "No linked transformation recorded", "empty-node"));
    $("request-nodes").append(element("div", "No payload / dispatch snapshot in this capture. Observed loads and responses cannot prove what was sent to the model.", "empty-node"));
    for (const node of responses) $("response-nodes").append(nodeButton(node));
    if (!responses.length) $("response-nodes").append(element("div", "Output not recorded. Usage counters do not provide the result text.", "empty-node"));
    $("request-summary").textContent = turn
      ? `Inventory for turn ${turn}: ${sources.length} sources · ${responses.length} responses · 0 payload snapshots`
      : `Inventory mode: ${sources.length} sources · ${responses.length} responses · 0 payload snapshots`;
    $("output-summary").textContent = view.outputStatus;
    $("coverage-summary").textContent = "File loaded successfully, but this capture has no payload_snapshot / final_dispatch events. Use Activity mode for the chronological tape; provenance inclusion edges need before_provider_request.";
    $("usage-list").replaceChildren();
    $("usage-list").append(element("li", "No usage record associated with a payload snapshot."));
    fillSessiongraphFindings();
    $("prov-detail-title").textContent = "Select an observed input or response";
    $("node-detail").replaceChildren();
    $("edge-list").replaceChildren();
    $("edge-list").append(element("li", "No request-boundary edges without a payload snapshot."));
    $("connections").replaceChildren();
    if (sources[0]) selectNode(sources[0].id);
    else if (responses[0]) selectNode(responses[0].id);
  }
  function drawEdges() {
    $("connections").replaceChildren(); if (!view || window.innerWidth <= 780 || mode !== "provenance") return;
    const board = $("graph-board").getBoundingClientRect();
    $("connections").setAttribute("viewBox", `0 0 ${board.width} ${board.height}`);
    for (const edge of graph.edges) {
      if (!buttons.has(edge.from) || !buttons.has(edge.to)) continue;
      const a = buttons.get(edge.from).getBoundingClientRect(), b = buttons.get(edge.to).getBoundingClientRect();
      const x1 = a.right - board.left, y1 = (a.top + a.bottom) / 2 - board.top, x2 = b.left - board.left, y2 = (b.top + b.bottom) / 2 - board.top;
      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("d", `M${x1},${y1} C${(x1+x2)/2},${y1} ${(x1+x2)/2},${y2} ${x2},${y2}`);
      path.setAttribute("class", `connector ${edge.kind}`); $("connections").append(path);
    }
  }
  $("mode-activity").addEventListener("click", () => { setMode("activity"); fillPicker(); renderActivity($("request-picker").value || ""); });
  $("mode-provenance").addEventListener("click", () => { setMode("provenance"); fillPicker(); });
  $("request-picker").addEventListener("change", e => {
    const value = e.target.value;
    if (mode === "activity") renderActivity(value);
    else if (graph.requests.length) showRequest(value);
    else showInventory(value);
  });
  async function readLocalFile(file) {
    if (typeof file.text === "function") return file.text();
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || ""));
      reader.onerror = () => reject(reader.error || new Error("Could not read the selected file"));
      reader.readAsText(file);
    });
  }
  $("capture-file").addEventListener("change", async e => {
    const file = e.target.files?.[0]; if (!file) return;
    setStatus(`Reading ${file.name}…`);
    try {
      if (file.size > 8 * 1024 * 1024) throw new Error("Capture exceeds 8 MB local-view limit");
      const text = await readLocalFile(file);
      if (!text.trim()) throw new Error("Selected file is empty");
      const events = text.trim().startsWith("[")
        ? JSON.parse(text)
        : text.split(/\r?\n/).filter(line => line.trim()).map((line, i) => {
          try { return JSON.parse(line); }
          catch (err) { throw new Error(`Invalid JSONL on line ${i + 1}: ${err.message}`); }
        });
      if (!Array.isArray(events) || !events.length) throw new Error("Capture contained no events");
      load({ label: `Local capture: ${file.name}`, events });
    } catch (error) {
      $("error").textContent = error.message || String(error);
      $("error").hidden = false;
      setStatus(`Could not load ${file.name}`);
    }
  });
  // Splitter drag
  (() => {
    const split = $("activity-view"), handle = $("splitter");
    let dragging = false;
    const onMove = ev => {
      if (!dragging) return;
      const rect = split.getBoundingClientRect();
      const y = (ev.touches ? ev.touches[0].clientY : ev.clientY) - rect.top;
      const pct = Math.min(75, Math.max(25, (y / rect.height) * 100));
      split.style.gridTemplateRows = `minmax(120px, ${pct}%) 8px minmax(120px, ${100 - pct}%)`;
    };
    const stop = () => { dragging = false; };
    handle.addEventListener("mousedown", () => { dragging = true; });
    handle.addEventListener("touchstart", () => { dragging = true; }, { passive: true });
    window.addEventListener("mousemove", onMove);
    window.addEventListener("touchmove", onMove, { passive: true });
    window.addEventListener("mouseup", stop);
    window.addEventListener("touchend", stop);
  })();
  window.addEventListener("resize", drawEdges);
  const questions = [
    { id: "unlinked", prompt: "A file is visible but has no text-match edge to the selected request. What is supported?", answers: ["It was definitely sent", "The file was observed; inclusion is unproven", "The model ignored it"], correct: 1 },
    { id: "boundary", prompt: "Text matches a provisional payload snapshot. What does that establish?", answers: ["It appeared at that capture boundary", "It definitely reached the provider unchanged", "It influenced the answer"], correct: 0 },
    { id: "summary", prompt: "A summary has three ancestors and is matched to a resumed request. Are all originals also present?", answers: ["Yes, ancestry proves inclusion", "No, compaction always deletes originals", "Unknown without separate match evidence"], correct: 2 },
    { id: "output", prompt: "Output tokens are reported, but no response event exists. Can we inspect the result?", answers: ["Yes, usage proves we captured the output", "No, output text was not recorded", "The request must have failed"], correct: 1 },
    { id: "influence", prompt: "A source matches a request and a response is observed. Does this prove the source caused the answer?", answers: ["Yes", "Only if the session health is high", "No, semantic influence remains unknown"], correct: 2 },
  ];
  for (const question of questions) {
    const field = element("fieldset"); field.append(element("legend", question.prompt));
    question.answers.forEach((text, index) => { const label = element("label"), input = element("input"); input.type = "radio"; input.name = question.id; input.value = String(index); input.required = true; label.append(input, document.createTextNode(text)); field.append(label); });
    $("questions").append(field);
  }
  $("study-form").addEventListener("submit", e => {
    e.preventDefault(); const form = new FormData($("study-form"));
    const answers = questions.map(q => ({ question: q.id, choice: form.get(q.id) === null ? null : Number(form.get(q.id)), correct: form.get(q.id) !== null && Number(form.get(q.id)) === q.correct }));
    if (answers.some(a => a.choice === null)) { $("study-result").textContent = "Answer all five questions first."; return; }
    result = { schema: "iseeagents.interpretation-check.v1", dataset: data.label, requestEventId: view?.request?.id ?? selectedStepId ?? null, timestamp: new Date().toISOString(), answers, correct: answers.filter(a => a.correct).length, total: questions.length, participant: "not collected" };
    $("study-result").textContent = `${result.correct}/${result.total} correct in this local check. This is one response, not a population accuracy estimate.`;
    $("download-result").hidden = false;
  });
  $("download-result").addEventListener("click", () => {
    if (!result) return; const url = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], { type: "application/json" }));
    const link = element("a"); link.href = url; link.download = "iseeagents-interpretation-result.json"; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  load(data);
})();
