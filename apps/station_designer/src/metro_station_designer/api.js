import { debugSessionId } from "./debug_event_log.js?v=debug-log-1";

export async function fetchJson(url, options) {
  const headers = new Headers(options?.headers || {});
  headers.set("X-Debug-Session", debugSessionId());
  const response = await fetch(url, { ...(options || {}), headers });
  const text = await response.text();
  let payload = {};
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch (exc) {
      if (response.ok) {
        throw new Error(`Invalid JSON response from ${url}: ${exc.message}`);
      }
      payload = { error: text.slice(0, 240) };
    }
  }
  if (!response.ok) {
    throw new Error(payload.error || `${response.status} ${response.statusText}`);
  }
  return payload;
}
