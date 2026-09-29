// Browser-visible configuration only. Authentication tokens never belong here.
export function collectorUrl(value, origin) {
  if (typeof value !== 'string' || value.startsWith('//') || value.includes('\\')) {
    throw new Error('Invalid collector URL');
  }
  const url = new URL(value, origin);
  const sameOriginPath = value.startsWith('/') && url.origin === origin;
  if (url.username || url.password || url.search || url.hash ||
      (url.protocol !== 'https:' && !(url.protocol === 'http:' && (url.hostname === 'localhost' || sameOriginPath)))) {
    throw new Error('Invalid collector URL');
  }
  return url.href;
}
