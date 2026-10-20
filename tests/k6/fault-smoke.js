// Maintainer test against an isolated, updated catalog—not the running demo.
import { preflight, probe } from './faults.js';
export const options = {
  scenarios: { faults: { executor: 'shared-iterations', vus: 1, iterations: 100, maxDuration: '30s' } },
  thresholds: { checks: ['rate==1'], synthetic_fault_probe_success: ['rate==1'] },
};
export function setup() { preflight(); }
export default function () { probe(); }
