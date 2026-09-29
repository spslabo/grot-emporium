import http from 'k6/http';
import { check, fail, sleep } from 'k6';
import { Rate } from 'k6/metrics';

const base = (__ENV.BASE_URL || '').replace(/\/$/, '');
if (!/^https?:\/\//.test(base)) throw new Error('Set BASE_URL to your Grot Emporium deployment.');
if (__ENV.TARGET_AUTHORIZED !== 'true') throw new Error('Set TARGET_AUTHORIZED=true only for your own demo deployment.');
const profile = __ENV.PROFILE || 'smoke';
const profiles = {
  smoke: { executor: 'shared-iterations', vus: 1, iterations: 1, maxDuration: '2m' },
  steady: { executor: 'constant-arrival-rate', rate: 1, timeUnit: '30s', duration: '30m', preAllocatedVUs: 2, maxVUs: 5 },
  baseline: { executor: 'constant-vus', vus: 5, duration: '5m' },
  spike: { executor: 'ramping-vus', startVUs: 1, stages: [{ duration: '30s', target: 10 }, { duration: '1m', target: 10 }, { duration: '30s', target: 0 }] },
};
if (!profiles[profile]) throw new Error('Unknown PROFILE');
if (profile === 'spike' && __ENV.ALLOW_SPIKE !== 'true') throw new Error('Spike testing requires ALLOW_SPIKE=true.');
export const options = {
  scenarios: { shopping: profiles[profile] },
  tags: { app: 'grot-emporium', service_namespace: 'grot-emporium', environment: 'demo', test: 'shopping', profile },
  systemTags: ['status', 'method', 'name', 'scenario', 'group', 'check', 'expected_response'],
  thresholds: { checks: ['rate>0.99'], http_req_failed: ['rate<0.01'], http_req_duration: ['p(95)<2000'], journey_success: ['rate>0.99'] },
};
const success = new Rate('journey_success');
const ids = JSON.parse(open('../../src/catalog/grots.json')).map(p => p.id);
function request(method, path, data, name) {
  const r = http.request(method, base + path, data, { tags: { name }, redirects: 5, timeout: '15s' });
  if (!check(r, { 'HTTP succeeded': v => v.status === 200 })) fail('Shopping request failed: ' + name);
  return r;
}
function stage(response, selector, name) {
  if (!check(response, { [name]: r => r.html().find(selector).size() > 0 })) fail('Unexpected shopping stage: ' + name);
}
export default function () {
  // A new isolated cookie jar for each shopping session; no real customer data.
  http.cookieJar().clear(base);
  let completed = false;
  try {
    request('GET', '/', null, 'GET home');
    request('GET', '/catalog', null, 'GET catalog');
    sleep(1);
    const id = ids[Math.floor(Math.random() * ids.length)];
    request('GET', '/catalog/' + id, null, 'GET product');
    request('POST', '/cart', { productId: id, quantity: '1' }, 'POST cart');
    stage(request('GET', '/cart', null, 'GET cart'), '#checkout', 'Cart contains item');
    stage(request('GET', '/checkout', null, 'GET checkout'), '#firstName', 'Shipping form loaded');
    const delivery = request('POST', '/checkout', { firstName: 'Demo', lastName: 'Grot', address1: '1 Example Street', city: 'Demo City', state: 'CA', zipCode: '90210', email: 'grot@example.test' }, 'POST shipping');
    const token = delivery.html().find('input[type="radio"]').first().attr('value');
    if (!token) fail('No delivery option returned');
    stage(request('POST', '/checkout/delivery', { token }, 'POST delivery'), '#cardNumber', 'Payment form loaded');
    sleep(1);
    const order = request('POST', '/checkout/payment', { cardHolder: 'Demo Grot', cardNumber: '4242424242424242', expiryDate: '12/35', cvc: '123' }, 'POST payment');
    stage(order, '#order-subtotal', 'Order created');
    completed = true;
  } finally { success.add(completed); }
  sleep(2);
}
