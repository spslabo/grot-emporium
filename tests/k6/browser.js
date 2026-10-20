import { browser } from 'k6/browser';
import { check } from 'k6';
import { Rate } from 'k6/metrics';
const journeySuccess = new Rate('browser_journey_success');
const faroDelivery = new Rate('faro_delivery_success');
const products = JSON.parse(open('../../src/catalog/grots.json'));

const base = (__ENV.BASE_URL || '').replace(/\/$/, '');
if (!/^https?:\/\//.test(base) || __ENV.TARGET_AUTHORIZED !== 'true') throw new Error('Set BASE_URL and TARGET_AUTHORIZED=true for your own demo.');
export const options = {
  scenarios: { browser: { executor: 'shared-iterations', vus: 1, iterations: 1, maxDuration: '2m', options: { browser: { type: 'chromium' } } } },
  tags: { app: 'grot-emporium', service_namespace: 'grot-emporium', environment: 'demo', test: 'browser' },
  systemTags: ['status', 'method', 'name', 'scenario', 'group', 'check', 'expected_response'],
  thresholds: { checks: ['rate==1'], browser_journey_success: ['rate==1'], browser_web_vital_lcp: ['p(95)<4000'], ...(__ENV.EXPECT_FARO === 'true' ? { faro_delivery_success: ['rate==1'] } : {}) },
};
export default async function () {
  const page = await browser.newPage();
  let completed = false;
  let faroAccepted = 0;
  let faroRejected = 0;
  page.on('response', response => {
    if (response.url().split('?')[0].endsWith('/telemetry')) {
      if (response.status() >= 200 && response.status() < 300) faroAccepted++;
      else faroRejected++;
    }
  });
  try {
    await page.goto(base + '/catalog');
    await page.locator('#menu-catalog').waitFor();
    check(await page.title(), { 'Grot storefront loaded': title => title === 'Grot Emporium' });
    await page.goto(base + '/catalog/cc789f85-1476-452a-8100-9e74502198e0');
    await Promise.all([page.waitForNavigation(), page.locator('#add-to-cart').click()]);
    if (await page.locator('.cart-item-image').count() === 0 || await page.locator('.item-quantity').count() === 0) {
      throw new Error('GROT_VERIFY_UI_OUTDATED');
    }
    // Repeated adds must merge quantities; deleting one SKU must preserve others.
    for (const id of [products[1].id, products[0].id]) {
      await page.goto(base + '/catalog/' + id);
      await Promise.all([page.waitForNavigation(), page.locator('#add-to-cart').click()]);
    }
    const original = '.cart-item:has(input[value="' + products[0].id + '"])';
    if (!check(await page.locator('.cart-item').count(), { 'One cart row per product': count => count === 2 })) {
      throw new Error('GROT_VERIFY_CART_DUPLICATES');
    }
    check(await page.locator(original + ' .item-quantity').textContent(), { 'Repeated add increases quantity': text => text.trim() === '2' });
    for (const width of [1280, 375]) {
      await page.setViewportSize({ width, height: 800 });
      const imagesFit = await page.evaluate(() => {
        const images = Array.from(document.querySelectorAll('.cart-item-image'));
        return images.length === 2 && images.every(image => {
          const box = image.getBoundingClientRect();
          return image.complete && image.naturalWidth > 0 && Math.abs(box.width - box.height) < 1 &&
            box.width >= 64 && getComputedStyle(image).objectFit === 'contain' && box.right <= innerWidth;
        });
      });
      check(imagesFit, { ['Cart images fit at viewport ' + width]: value => value });
    }
    await page.setViewportSize({ width: 1280, height: 800 });
    await Promise.all([page.waitForNavigation(), page.locator(original + ' .remove-item').click()]);
    check(await page.locator('.cart-item').count(), { 'Deleting a product preserves the other row': count => count === 1 });
    check(await page.locator('.cart-item input[name="productId"]').getAttribute('value'), { 'Other product is retained': id => id === products[1].id });
    await page.goto(base + '/checkout');
    for (const [id, value] of Object.entries({ firstName: 'Demo', lastName: 'Grot', address1: '1 Example Street', city: 'Demo City', state: 'CA', zipCode: '90210', email: 'grot@example.test' })) {
      await page.locator('#' + id).fill(value);
    }
    await Promise.all([page.waitForNavigation(), page.locator('#checkout-submit').click()]);
    // The radio itself is sr-only; interact with its visible enclosing label.
    await page.locator('#checkoutForm fieldset label').first().click();
    await Promise.all([page.waitForNavigation(), page.locator('#checkout-submit').click()]);
    for (const [id, value] of Object.entries({ cardHolder: 'Demo Grot', cardNumber: '4242424242424242', expiryDate: '12/35', cvc: '123' })) {
      await page.locator('#' + id).fill(value);
    }
    await Promise.all([page.waitForNavigation(), page.locator('#checkout-submit').click()]);
    completed = check(await page.locator('#order-subtotal').isVisible(), { 'Order created': visible => visible });
    if (__ENV.VERIFY_TELEMETRY === 'true') {
      // Explicit synthetic probes: form navigations do not exercise fetch tracing.
      await page.evaluate(function () {
        setTimeout(function () { throw new Error('Grot synthetic telemetry probe'); }, 0);
        return fetch('/catalog').then(function (response) { return response.status; });
      });
    }
    // Allow batched Faro telemetry to flush before the browser context closes.
    await page.waitForTimeout(__ENV.VERIFY_TELEMETRY === 'true' || __ENV.TRAFFIC_DURATION ? 6000 : 2000);
    if (__ENV.EXPECT_FARO === 'true' && (faroAccepted === 0 || faroRejected > 0)) {
      throw new Error('GROT_VERIFY_FARO_FAILED');
    }
  } finally {
    journeySuccess.add(completed);
    if (__ENV.EXPECT_FARO === 'true') faroDelivery.add(faroAccepted > 0 && faroRejected === 0);
    await page.close();
  }
}
