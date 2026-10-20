// Sustained synthetic demo traffic; Cloud credentials are injected by the runner.
import shopping from './shopping.js';
import browserJourney from './browser.js';
import { enabled, scenario, preflight, probe } from './faults.js';
import { enabled as chatEnabled, scenario as chatScenario, probe as chatProbe } from './chat-traffic.js';
const rate = Number(__ENV.JOURNEYS_PER_MINUTE || 6);
const browserRate = Number(__ENV.BROWSER_JOURNEYS_PER_MINUTE || 1);
const duration = __ENV.TRAFFIC_DURATION || '1h';
if (!Number.isInteger(rate) || rate < 1 || rate > 600 || !Number.isInteger(browserRate) || browserRate < 0 || browserRate > 10) throw new Error('Invalid traffic rate');
export const options = {
  ...(__ENV.K6_CLOUD_PROJECT_ID ? { cloud: { projectID: Number(__ENV.K6_CLOUD_PROJECT_ID), name: __ENV.GROT_K6_TEST_NAME } } : {}),
  scenarios: {
    ...scenario,
    ...chatScenario,
    shopping: { executor: 'constant-arrival-rate', exec: 'shop', rate, timeUnit: '1m', duration, preAllocatedVUs: Math.max(2, Math.ceil(rate / 6)), maxVUs: Math.min(100, Math.max(5, Math.ceil(rate / 3))), gracefulStop: '30s' },
    ...(browserRate ? { browser: { executor: 'constant-arrival-rate', exec: 'browse', rate: browserRate, timeUnit: '1m', duration, preAllocatedVUs: 1, maxVUs: 3, gracefulStop: '30s', options: { browser: { type: 'chromium' } } } } : {}),
  },
  tags: { app: 'grot-emporium', test: 'demo-traffic', traffic_preset: __ENV.TRAFFIC_PRESET || 'custom' },
  systemTags: ['status', 'method', 'error', 'name', 'scenario', 'group', 'check', 'expected_response'],
  thresholds: { ...(chatEnabled ? { chat_journey_success: ['rate>0.95'], 'http_req_failed{scenario:chat}': ['rate<0.05'] } : {}), checks: ['rate>0.95'], ...(enabled ? { 'http_req_failed{scenario:shopping}': ['rate<0.05'], synthetic_fault_probe_success: ['rate>0.99'] } : { http_req_failed: ['rate<0.05'] }), journey_success: ['rate>0.95'], dropped_iterations: ['count==0'], ...(browserRate ? { browser_journey_success: ['rate>0.95'], browser_http_req_failed: ['rate<0.05'] } : {}), ...(browserRate && __ENV.EXPECT_FARO === 'true' ? { faro_delivery_success: ['rate>0.95'] } : {}) },
};
export function chat() { chatProbe(); }
export function setup() { preflight(); }
export function fault() { probe(); }
export function shop() { shopping(); }
export async function browse() { await browserJourney(); }
