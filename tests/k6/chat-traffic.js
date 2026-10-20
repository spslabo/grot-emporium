import http from 'k6/http';
import crypto from 'k6/crypto';
import exec from 'k6/execution';
import { check } from 'k6';
import { Rate, Counter } from 'k6/metrics';

const interval = Number(__ENV.GROT_CHAT_INTERVAL_SECONDS || 0);
const budget = Number(__ENV.GROT_CHAT_MAX_REQUESTS || 60);
const errorEvery = Number(__ENV.GROT_CHAT_ERROR_EVERY || 0);
if (!Number.isInteger(errorEvery) || (errorEvery !== 0 && (errorEvery < 2 || errorEvery > 1000))) throw new Error('Chat error cadence must be 0 (disabled) or 2–1000.');
export const enabled = interval > 0;
if (enabled && (__ENV.ALLOW_PAID_AI !== 'true' || !Number.isInteger(interval) || interval < 60 || interval > 3600 || !Number.isInteger(budget) || budget < 1 || budget > 1000)) throw new Error('Chat traffic requires explicit paid-model consent, a 60–3600 second interval, and a bounded request budget.');
const success = new Rate('chat_journey_success');
const skipped = new Counter('chat_requests_skipped_budget');
const injected = new Counter('chat_injected_errors');
export const scenario = enabled ? { chat: { executor: 'constant-arrival-rate', exec: 'chat', rate: 1, timeUnit: `${interval}s`, duration: __ENV.TRAFFIC_DURATION || '1h', preAllocatedVUs: 1, maxVUs: 1, gracefulStop: '30s', tags: { synthetic: 'true' } } } : {};

export function probe() {
  if (exec.scenario.iterationInTest >= budget) { skipped.add(1); return; }
  const bytes = new Uint8Array(crypto.randomBytes(16));
  bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes, v => v.toString(16).padStart(2, '0')).join('');
  const conversationId = `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
  const prompts = ['Which Grot makes a fun desk companion? Answer in one short sentence.', 'Suggest a Grot for someone who enjoys space. Keep it brief.', 'What makes Zen Grot a fun desk decoration? Keep it brief and do not invent prices.'];
  const expectError = errorEvery > 0 && (exec.scenario.iterationInTest + 1) % errorEvery === 0;
  const r = http.post(__ENV.BASE_URL.replace(/\/$/, '') + '/chat/submit', JSON.stringify({ conversationId, message: prompts[exec.scenario.iterationInTest % prompts.length] }), {
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream', ...(expectError ? { 'X-Grot-Synthetic-Fault': 'error' } : {}) },
    responseCallback: http.expectedStatuses(expectError ? 503 : 200),
    tags: { name: 'POST synthetic chat', synthetic: 'true', expected_fault: String(expectError) }, timeout: '25s',
  });
  let text = '';
  for (const line of (r.body || '').split('\n')) {
    if (line.startsWith('data:')) {
      try { const message = JSON.parse(line.slice(5)); if (typeof message.text === 'string') text += message.text; } catch (_) { /* incomplete/error stream */ }
    }
  }
  const ok = expectError ? r.status === 503 : r.status === 200 && !r.error && text.trim().length > 0 && !(r.body || '').includes('event:error');
  if (expectError && r.status === 503) injected.add(1);
  success.add(ok);
  check(ok, { 'Chat matched expected success/failure outcome': v => v });
  // Correlate with Agent Observability without logging prompts or completions.
  console.info(`Grot synthetic chat conversation=${conversationId} success=${ok} injected_error=${expectError}`);
}
