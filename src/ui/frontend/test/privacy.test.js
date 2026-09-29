import test from 'node:test';
import assert from 'node:assert/strict';
import { safeUrl, sanitizeItem } from '../src/privacy.js';
const origin = 'https://grots.example.test';
test('URLs strip queries, fragments, and order identifiers', () => {
  assert.equal(safeUrl('/order/secret?email=private@example.com#card', origin), origin + '/order/:id');
  assert.equal(safeUrl('https://external.example/path?token=secret', origin), '[external]');
});
test('console contents are not exported', () => assert.equal(sanitizeItem({ type: 'log', payload: 'secret' }, origin), null));
test('error metadata remains useful without arbitrary messages or user details', () => {
  const result = sanitizeItem({ type: 'exception', meta: { user: { email: 'private' }, page: { url: origin + '/?token=secret' } }, payload: { type: 'TypeError', value: 'private', context: { input: 'secret' } } }, origin);
  assert.equal(result.payload.type, 'TypeError');
  assert.equal(result.payload.value, 'Browser error (message redacted)');
  assert.equal(result.meta.page.url, origin + '/');
  assert.equal(result.meta.user, undefined);
  assert.deepEqual(result.payload.context, {});
});
