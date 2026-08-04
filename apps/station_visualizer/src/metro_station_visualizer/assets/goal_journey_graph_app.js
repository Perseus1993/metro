(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const datasets = window.GOAL_JOURNEY_DEMO_DATASETS || {};
  if (!datasets.natural_full_journey || !datasets.crowded_full_journey) {
    throw new Error("Goal journey visualization datasets are missing");
  }

  const canvas = $("journeyCanvas");
  const timeline = $("timeline");
  const playButton = $("playButton");
  const resetButton = $("resetButton");
  const speedSelect = $("speedSelect");
  const modeSelect = $("modeSelect");
  const graphNodes = $("graphNodes");
  let data = datasets[modeSelect.value];
  let duration = data.duration_seconds;
  let path = [];
  let time = 0;
  let playing = true;
  let previousTimestamp = performance.now();
  let visibleEventCount = -1;

  const nodeLabels = {
    approach_entry_gate_decision: "接近闸机决策区", use_entry_gate: "选择并通过闸机",
    enter_paid_hall: "进入付费区", approach_vertical_decision: "接近楼梯决策区",
    use_vertical_transfer: "选择并使用楼梯", enter_platform_landing: "抵达站台层",
    approach_boarding_decision: "接近车门决策区", use_boarding_door: "排队并上车",
    complete: "旅程完成",
  };
  const eventLabels = {
    start: "旅程启动", entered_region: "进入区域", candidates_updated: "更新候选设施",
    reached_queue_capture: "抵达队列捕获区", queue_joined: "加入实体队列",
    service_started: "开始设施服务", service_completed: "完成设施服务",
    progress_stalled: "检测到停滞", facility_unavailable: "设施不可用",
  };
  const stateLabels = {
    entering_station: "进入车站", walking_to_vertical: "前往楼梯", queueing_gate: "闸机排队",
    passing_gate: "通过闸机", queueing_vertical: "楼梯排队", riding_vertical: "楼梯行程",
    walking_to_platform: "站台内步行", queueing_door: "车门排队", boarding_train: "正在上车",
    departed: "已上车",
  };

  const graphPath = () => {
    const bySource = new Map(data.graph.transitions.map((item) => [item.source, item.target]));
    const path = []; let id = data.graph.entry_node_id;
    while (id) { path.push(id); id = bySource.get(id); }
    return path;
  };
  const buildGraph = () => {
    graphNodes.replaceChildren();
    const nodeById = new Map(data.graph.nodes.map((node) => [node.id, node]));
    path.forEach((id, index) => {
      const node = nodeById.get(id); const item = document.createElement("div");
      item.className = "graph-node"; item.dataset.nodeId = id;
      const icon = node.kind === "use_facility_stage" ? "F" : node.kind === "complete" ? "✓" : "R";
      item.innerHTML = `<span class="icon">${icon}</span><div><b>${nodeLabels[id] || id}</b><small>${node.kind} · ${String(index + 1).padStart(2, "0")}</small></div>`;
      graphNodes.appendChild(item);
    });
  };

  const traceAt = (value) => {
    let current = data.traces[0];
    data.traces.forEach((trace) => { if (trace.time_seconds <= value + 1e-6) current = trace; });
    return current;
  };

  const splitState = (label) => {
    const [node, interaction] = label.split("/");
    return { node, interaction: interaction || "—" };
  };

  const updateGraph = (trace) => {
    const state = splitState(trace.after_graph_state);
    const activeIndex = path.indexOf(state.node);
    graphNodes.querySelectorAll(".graph-node").forEach((item, index) => {
      item.classList.toggle("done", index < activeIndex || state.node === "complete" && index <= activeIndex);
      item.classList.toggle("active", index === activeIndex);
    });
    $("currentNode").textContent = nodeLabels[state.node] || state.node;
    $("interactionState").textContent = state.interaction;
    $("commitmentValue").textContent = trace.committed_facility_id || "—";
    $("eventValue").textContent = eventLabels[trace.event_kind] || trace.event_kind;
  };

  const buildEvents = () => {
    $("eventTimeline").replaceChildren();
    data.traces.forEach((trace) => {
      const item = document.createElement("div");
      item.className = "event-chip"; item.dataset.time = trace.time_seconds;
      const state = splitState(trace.after_graph_state);
      item.innerHTML = `<time>${trace.time_seconds.toFixed(2)} s</time><b>${eventLabels[trace.event_kind] || trace.event_kind}</b><small>${nodeLabels[state.node] || state.node}</small>`;
      $("eventTimeline").appendChild(item);
    });
  };

  const updateEvents = () => {
    const chips = [...document.querySelectorAll(".event-chip")];
    let latest = null;
    let count = 0;
    chips.forEach((chip) => {
      const visible = Number(chip.dataset.time) <= time + 1e-6;
      chip.classList.toggle("visible", visible);
      if (visible) { latest = chip; count += 1; }
    });
    if (count !== visibleEventCount) {
      visibleEventCount = count;
      latest?.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "end" });
    }
  };

  const render = () => {
    const frame = window.GoalJourneyScene.draw(canvas, data, time);
    const trace = traceAt(time);
    $("timeValue").textContent = `${time.toFixed(2)} s`;
    $("levelValue").textContent = frame.level_id === "platform" ? "站台层" : "站厅层";
    $("passengerState").textContent = stateLabels[frame.passenger_state] || frame.passenger_state;
    $("serviceCount").textContent = `${frame.service_event_count} / 3`;
    $("crowdCount").textContent = String(1 + (frame.crowd?.length || 0));
    timeline.value = String(time);
    updateGraph(trace); updateEvents();
  };

  const loadDataset = (scenarioId) => {
    data = datasets[scenarioId];
    duration = data.duration_seconds;
    path = graphPath();
    time = 0;
    visibleEventCount = -1;
    timeline.max = String(duration);
    $("scenarioDescription").textContent = scenarioId === "crowded_full_journey"
      ? "拥挤模式：92 名流动背景旅客与 36 名局部阻塞旅客，共同触发闸机、楼梯、车门的重新选择。"
      : "清场模式：只保留研究对象，用于观察无干扰时的 Graph 基准过程。";
    buildGraph();
    buildEvents();
    render();
  };

  const animate = (timestamp) => {
    const elapsed = Math.min(0.1, (timestamp - previousTimestamp) / 1000);
    previousTimestamp = timestamp;
    if (playing) {
      time = Math.min(duration, time + elapsed * Number(speedSelect.value));
      if (time >= duration) { playing = false; playButton.textContent = "播放"; }
    }
    render(); requestAnimationFrame(animate);
  };

  playButton.addEventListener("click", () => {
    if (time >= duration) time = 0;
    playing = !playing; playButton.textContent = playing ? "暂停" : "播放";
  });
  resetButton.addEventListener("click", () => { time = 0; playing = true; playButton.textContent = "暂停"; });
  timeline.addEventListener("input", () => { time = Number(timeline.value); playing = false; playButton.textContent = "播放"; render(); });
  modeSelect.addEventListener("change", () => {
    loadDataset(modeSelect.value);
    playing = true;
    playButton.textContent = "暂停";
  });
  window.addEventListener("resize", render);

  loadDataset(modeSelect.value);
  requestAnimationFrame(animate);
})();
