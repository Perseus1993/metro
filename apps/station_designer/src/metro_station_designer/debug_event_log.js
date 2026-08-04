const SESSION_KEY = "metro-station-debug-session";
const SEQUENCE_KEY = "metro-station-debug-sequence";
const OUTBOX_KEY = "metro-station-debug-outbox";
const RETRY_DELAY_MS = 1_000;

let memorySessionId = "";
let memorySequence = 0;
let memoryOutbox = null;
let flushPromise = null;
let retryTimer = null;

export function debugSessionId() {
  if (memorySessionId) return memorySessionId;
  const stored = readSessionValue(SESSION_KEY);
  memorySessionId = stored || createSessionId();
  writeSessionValue(SESSION_KEY, memorySessionId);
  return memorySessionId;
}

export function recordDebugEvent(action, details = {}, status = "info") {
  const sequence = nextSequence();
  const event = {
    action,
    status,
    sequence,
    details: {
      ...details,
      client_timestamp: new Date().toISOString(),
    },
  };
  debugOutbox().push(event);
  persistOutbox();
  return flushDebugOutbox();
}

export function debugEventsUrl({ allSessions = false, limit = 100 } = {}) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (!allSessions) params.set("session_id", debugSessionId());
  return `/api/debug/events?${params.toString()}`;
}

export function debugExportUrl({ allSessions = false } = {}) {
  const params = new URLSearchParams();
  if (!allSessions) params.set("session_id", debugSessionId());
  const query = params.toString();
  return `/api/debug/export${query ? `?${query}` : ""}`;
}

function nextSequence() {
  const stored = Number(readSessionValue(SEQUENCE_KEY));
  memorySequence = Math.max(memorySequence, Number.isFinite(stored) ? stored : 0) + 1;
  writeSessionValue(SEQUENCE_KEY, String(memorySequence));
  return memorySequence;
}

function flushDebugOutbox() {
  if (flushPromise) return flushPromise;
  if (!debugOutbox().length) return Promise.resolve(true);
  flushPromise = flushQueuedEvents()
    .catch((error) => {
      console.warn("Unable to persist design debug events", error);
      scheduleRetry();
      return false;
    })
    .finally(() => {
      flushPromise = null;
      if (debugOutbox().length) scheduleRetry();
    });
  return flushPromise;
}

async function flushQueuedEvents() {
  while (debugOutbox().length) {
    const event = debugOutbox()[0];
    const body = JSON.stringify(event);
    const response = await fetch("/api/debug/events", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Debug-Session": debugSessionId(),
      },
      body,
      keepalive: body.length < 60_000,
    });
    if (!response.ok) {
      throw new Error(`${response.status} ${response.statusText}`);
    }
    debugOutbox().shift();
    persistOutbox();
  }
  return true;
}

function scheduleRetry() {
  if (retryTimer !== null || typeof globalThis.setTimeout !== "function") return;
  retryTimer = globalThis.setTimeout(() => {
    retryTimer = null;
    flushDebugOutbox();
  }, RETRY_DELAY_MS);
}

function debugOutbox() {
  if (memoryOutbox !== null) return memoryOutbox;
  try {
    const parsed = JSON.parse(readSessionValue(OUTBOX_KEY) || "[]");
    memoryOutbox = Array.isArray(parsed) ? parsed : [];
  } catch {
    memoryOutbox = [];
  }
  return memoryOutbox;
}

function persistOutbox() {
  writeSessionValue(OUTBOX_KEY, JSON.stringify(debugOutbox()));
}

function createSessionId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `session-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

function readSessionValue(key) {
  try {
    return globalThis.sessionStorage?.getItem(key) || "";
  } catch {
    return "";
  }
}

function writeSessionValue(key, value) {
  try {
    globalThis.sessionStorage?.setItem(key, value);
  } catch {
    // Memory fallback is sufficient when storage is unavailable.
  }
}

if (typeof globalThis.window !== "undefined") {
  scheduleRetry();
}
