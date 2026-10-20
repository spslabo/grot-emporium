import http from 'k6/http';
import exec from 'k6/execution';
import { check } from 'k6';
import { Rate, Counter } from 'k6/metrics';

export const enabled = __ENV.GROT_FAILURES === 'true';
const errors = Number(__ENV.GROT_ERROR_PERCENT || 1);
const slow = Number(__ENV.GROT_SLOW_PERCENT || 5);
const delay = Number(__ENV.GROT_DELAY_MS || 2000);
const rate = Number(__ENV.GROT_FAULT_RATE || 60);
const base = (__ENV.GROT_FAULT_BASE_URL || '').replace(/\/$/, '');
if (enabled && (!/^http:\/\/catalog(?::(?:80|8080))?$/.test(base) || ![errors, slow, delay, rate].every(Number.isInteger) || errors < 0 || slow < 0 || errors > 50 || slow > 50 || errors + slow > 100 || delay < 1 || delay > 5000 || rate < 1 || rate > 600)) throw new Error('Invalid synthetic fault settings');
const success = new Rate('synthetic_fault_probe_success');
const injected = new Counter('synthetic_fault_events');

export const scenario = enabled ? { faults: { executor: 'constant-arrival-rate', exec: 'fault', rate, timeUnit: '1m', duration: __ENV.TRAFFIC_DURATION || '1h', preAllocatedVUs: Math.min(60, Math.max(3, Math.ceil(rate * delay / 60000) + 2)), maxVUs: 60, gracefulStop: '10s', tags: { synthetic: 'true' } } } : {};

export function preflight() {
  if (!enabled) return;
  const r = http.get(base + '/chaos/capabilities', { tags: { name: 'GET synthetic fault capabilities', synthetic: 'true' }, timeout: '10s' });
  let supported = false;
  try { supported = r.status === 200 && r.json('request_scoped_faults') === true; } catch (_) { /* old image */ }
  if (!supported) throw new Error('Catalog image does not support request-scoped faults. Deploy the updated catalog image first; no global chaos controls were changed.');
}

export function probe() {
  // Reproducible distribution over each 100 probes, independent of healthy shopping.
  const slot = exec.scenario.iterationInTest % 100;
  const kind = slot < errors ? 'error' : slot < errors + slow ? 'latency' : 'none';
  const headers = kind === 'none' ? {} : { 'X-Grot-Synthetic-Fault': kind, ...(kind === 'latency' ? { 'X-Grot-Delay-Ms': String(delay) } : {}) };
  const r = http.get(base + '/catalog/products', { headers, timeout: '10s', tags: { name: 'GET catalog synthetic probe', synthetic: 'true', synthetic_fault: kind } });
  const ok = r.status === (kind === 'error' ? 500 : 200) && (kind === 'none' || r.headers['X-Grot-Synthetic-Fault'] === kind) && (kind !== 'latency' || r.timings.duration >= delay - 10);
  success.add(ok, { synthetic_fault: kind });
  check(ok, { 'Synthetic fault matched requested behavior': value => value });
  if (kind !== 'none' && ok) injected.add(1, { synthetic_fault: kind });
}
