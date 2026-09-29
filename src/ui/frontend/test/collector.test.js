import test from 'node:test';
import assert from 'node:assert/strict';
import { collectorUrl } from '../src/collector.js';

test('same-origin proxy works over local HTTP or deployed HTTPS', () => {
  assert.equal(collectorUrl('/telemetry', 'http://localhost:8080'), 'http://localhost:8080/telemetry');
  assert.equal(collectorUrl('/telemetry', 'https://shop.example.invalid'), 'https://shop.example.invalid/telemetry');
});
test('absolute HTTPS collector is supported without credentials', () => {
  assert.equal(collectorUrl('https://collector.example.invalid/collect', 'https://shop.example.invalid'), 'https://collector.example.invalid/collect');
});
test('ambiguous, credential-bearing and insecure external collector URLs are rejected', () => {
  for (const value of ['//external.invalid/collect', '/\\external.invalid/collect', 'https://user:secret@example.invalid', 'https://example.invalid?token=secret', 'http://external.invalid/collect', 'javascript:alert(1)']) {
    assert.throws(() => collectorUrl(value, 'https://shop.example.invalid'));
  }
});
