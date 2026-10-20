import http from 'k6/http';
import { check } from 'k6';
import crypto from 'k6/crypto';

const base = (__ENV.BASE_URL || '').replace(/\/$/, '');
if (!/^https?:\/\//.test(base) || __ENV.TARGET_AUTHORIZED !== 'true' || __ENV.ALLOW_PAID_AI !== 'true') {
  throw new Error('Real model smoke test requires BASE_URL, TARGET_AUTHORIZED=true, and ALLOW_PAID_AI=true.');
}
export const options = {
  scenarios: { chat: { executor: 'shared-iterations', vus: 1, iterations: 2, maxDuration: '2m' } },
  tags: { app: 'grot-emporium', environment: 'demo', test: 'chat' },
  systemTags: ['status', 'method', 'name', 'scenario', 'check', 'expected_response'],
  thresholds: { checks: ['rate==1'], http_req_failed: ['rate<0.01'] },
};
export default function () {
  const bytes = new Uint8Array(crypto.randomBytes(16));
  bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes, v => v.toString(16).padStart(2, '0')).join('');
  const conversationId = `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
  const response = http.post(base + '/chat/submit', JSON.stringify({ conversationId, message: 'Which Grot squishy would make a fun desk companion? Keep your answer short.' }), {
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    tags: { name: 'POST chat' }, timeout: '45s',
  });
  check(response, { 'Chat stream succeeded': r => r.status === 200 && r.body.includes('data:') });
}
