import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";

import { createActorPool } from "./turnstile_glb_actor_pool.js?v=glb-demo-2";
import {
  rebuildStaticTurnstileScene,
  setupTurnstileLighting,
  worldToScene,
} from "./turnstile_glb_static_scene.js?v=glb-demo-2";

const DATA_URL = urlParam("data", "assets/turnstile_glb_probe_data.json");
const GLB_URL = urlParam(
  "glb",
  "../design_inspector/assets/quaternius/AnimationLibrary_Godot_Standard.glb",
);

const canvas = document.querySelector("#turnstileGlbScene");
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true });
const scene = new THREE.Scene();
const camera = new THREE.OrthographicCamera(-18, 18, 11, -11, 0.1, 200);
const controls = {
  runSelect: document.querySelector("#runSelect"),
  playButton: document.querySelector("#playButton"),
  speedSelect: document.querySelector("#speedSelect"),
  timeline: document.querySelector("#timeline"),
  runLabel: document.querySelector("#runLabel"),
  status: document.querySelector("#statusLine"),
  active: document.querySelector("#activeValue"),
  queue: document.querySelector("#queueValue"),
  service: document.querySelector("#serviceValue"),
  sink: document.querySelector("#sinkValue"),
  clock: document.querySelector("#clockValue"),
};
const state = {
  payload: null,
  runIndex: 0,
  frameValue: 0,
  playing: true,
  actorPool: null,
  lastNow: performance.now(),
};

setupTurnstileLighting(scene, camera);
bindControls();
resize();
window.addEventListener("resize", resize);

Promise.all([loadJson(DATA_URL), new GLTFLoader().loadAsync(GLB_URL)])
  .then(([payload, gltf]) => {
    state.payload = payload;
    populateRuns();
    buildRunScene();
    state.actorPool = createActorPool(
      scene,
      gltf.scene,
      gltf.animations || [],
      (point) => worldToScene(currentRun(), point),
    );
    controls.status.textContent = "GLB ready · Simulation tracks driving skeletons";
    window.__TURNSTILE_GLB_READY = true;
    renderer.setAnimationLoop(render);
  })
  .catch((error) => {
    controls.status.textContent = `GLB demo failed: ${error.message}`;
    window.__TURNSTILE_GLB_ERROR = error.message;
});

function bindControls() {
  controls.playButton.addEventListener("click", () => {
    state.playing = !state.playing;
    controls.playButton.textContent = state.playing ? "⏸" : "▶";
  });
  controls.timeline.addEventListener("input", () => {
    state.frameValue = Number(controls.timeline.value || 0);
    state.playing = false;
    controls.playButton.textContent = "▶";
  });
  controls.runSelect.addEventListener("change", () => {
    state.runIndex = Number(controls.runSelect.value || 0);
    state.frameValue = 0;
    state.playing = true;
    controls.playButton.textContent = "⏸";
    state.actorPool?.clear();
    buildRunScene();
  });
}

function populateRuns() {
  controls.runSelect.textContent = "";
  runs().forEach((run, index) => {
    const option = document.createElement("option");
    option.value = String(index);
    option.textContent = run.label || run.run_id || `run ${index + 1}`;
    controls.runSelect.append(option);
  });
}

function buildRunScene() {
  const run = currentRun();
  if (!run) return;
  controls.timeline.max = String(Math.max(0, frames().length - 1));
  controls.timeline.value = "0";
  controls.runLabel.textContent = run.label || run.run_id || "single run";
  rebuildStaticTurnstileScene(scene, run);
}

function render(now) {
  const elapsed = Math.min(0.08, Math.max(0, (now - state.lastNow) / 1000));
  state.lastNow = now;
  if (state.playing) advanceFrame(elapsed);
  const sampled = samplePassengers();
  state.actorPool?.update(sampled, elapsed);
  updateStats(sampled);
  renderer.render(scene, camera);
}

function advanceFrame(elapsed) {
  const maxFrame = Math.max(0, frames().length - 1);
  state.frameValue = Math.min(maxFrame, state.frameValue + elapsed * Number(controls.speedSelect.value || 1));
  if (state.frameValue >= maxFrame) {
    state.playing = false;
    controls.playButton.textContent = "▶";
  }
  controls.timeline.value = String(state.frameValue);
}

function samplePassengers() {
  const allFrames = frames();
  if (!allFrames.length) return [];
  const leftIndex = Math.max(0, Math.min(allFrames.length - 1, Math.floor(state.frameValue)));
  const rightIndex = Math.max(0, Math.min(allFrames.length - 1, leftIndex + 1));
  const left = allFrames[leftIndex];
  const right = allFrames[rightIndex];
  const t = Math.max(0, Math.min(1, state.frameValue - leftIndex));
  const leftById = new Map((left.passengers || []).map((item) => [item.id, item]));
  return (right.passengers || []).map((item) => {
    const start = leftById.get(item.id) || item;
    const x = lerp(start.x, item.x, t);
    const y = lerp(start.y, item.y, t);
    const speed = Math.hypot(item.x - start.x, item.y - start.y);
    return { ...item, x, y, speed, time_seconds: left.time_seconds || 0 };
  });
}

function updateStats(passengers) {
  const frame = frames()[Math.floor(state.frameValue)] || {};
  controls.active.textContent = String(passengers.filter((item) => item.state !== "departed").length);
  controls.queue.textContent = String(frame.queue_persons || 0);
  controls.service.textContent = String(frame.service_persons || 0);
  controls.sink.textContent = String(frame.sink_persons || 0);
  controls.clock.textContent = `${Math.round(frame.time_seconds || 0)}s`;
  window.__TURNSTILE_GLB_STATE = {
    active: controls.active.textContent,
    queue: controls.queue.textContent,
    service: controls.service.textContent,
  };
}

function resize() {
  const width = canvas.clientWidth || window.innerWidth;
  const height = canvas.clientHeight || window.innerHeight;
  const aspect = width / Math.max(1, height);
  const viewWidth = 37;
  camera.left = -viewWidth / 2;
  camera.right = viewWidth / 2;
  camera.top = viewWidth / aspect / 2;
  camera.bottom = -viewWidth / aspect / 2;
  camera.updateProjectionMatrix();
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setSize(width, height, false);
}

function runs() {
  return Array.isArray(state.payload?.runs) ? state.payload.runs : [];
}

function currentRun() {
  return runs()[state.runIndex];
}

function frames() {
  return Array.isArray(currentRun()?.frames) ? currentRun().frames : [];
}

function loadJson(url) {
  return fetch(url).then((response) => {
    if (!response.ok) throw new Error(`Could not load ${url}`);
    return response.json();
  });
}

function urlParam(key, fallback) {
  return new URLSearchParams(window.location.search).get(key) || fallback;
}

function lerp(a, b, t) {
  return Number(a || 0) + (Number(b || 0) - Number(a || 0)) * t;
}
