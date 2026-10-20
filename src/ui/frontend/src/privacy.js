export function safeUrl(value, origin) {
  try {
    const url = new URL(value, origin);
    if (url.origin !== origin) return '[external]';
    return origin + url.pathname
      .replace(/\/[0-9a-f]{8}-[0-9a-f-]{27,}(?=\/|$)/gi, '/:id')
      .replace(/\/order\/[^/]+/g, '/order/:id');
  } catch { return '[redacted]'; }
}

function scrub(value, origin) {
  if (typeof value === 'string' && /^https?:\/\//.test(value)) return safeUrl(value, origin);
  if (Array.isArray(value)) return value.map(v => scrub(v, origin));
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value)
      .filter(([k]) => !/^(user|originalError|requestBody|responseBody|authorization|cookie)$/i.test(k))
      .map(([k, v]) => [k, scrub(v, origin)]));
  }
  return value;
}

export function sanitizeItem(item, origin) {
  if (item.type === 'log') return null; // Never forward arbitrary browser console contents.
  const clean = scrub(item, origin);
  if (clean.meta?.page?.url) clean.meta.page.url = safeUrl(clean.meta.page.url, origin);
  if (clean.meta?.page) clean.meta.page.attributes = {};
  if (clean.type === 'exception' && clean.payload) {
    clean.payload.value = 'Browser error (message redacted)';
    clean.payload.context = {};
  }
  return clean;
}
