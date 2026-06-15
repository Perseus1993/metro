export async function fetchJson(url, options) {
  const response = await fetch(url, options);
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
