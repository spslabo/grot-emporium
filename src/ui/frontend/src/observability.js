import { initializeFaro, getWebInstrumentations } from '@grafana/faro-web-sdk';
import { TracingInstrumentation } from '@grafana/faro-web-tracing';
import { sanitizeItem } from './privacy.js';
import { collectorUrl } from './collector.js';

const config = window.grotTelemetry;
if (config?.enabled && config.url) {
  try {
    // A same-origin path supports an operator-managed proxy without exposing
    // the private upstream collector URL to the browser.
    const collector = collectorUrl(config.url, location.origin);
    const faro = initializeFaro({
      url: collector,
      app: { name: 'grot-emporium-web', version: config.version, environment: config.environment },
      instrumentations: [
        ...getWebInstrumentations({ captureConsole: false }),
        new TracingInstrumentation({
          resourceAttributes: { 'service.namespace': 'grot-emporium', 'deployment.environment.name': config.environment },
          instrumentationOptions: { propagateTraceHeaderCorsUrls: [new RegExp('^' + location.origin.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '/')] },
        }),
      ],
      beforeSend: item => sanitizeItem(item, location.origin),
    });
    const paths = { '/': 'home', '/home': 'home', '/catalog': 'catalog', '/cart': 'cart', '/checkout': 'checkout' };
    faro.api.pushEvent('grot_page_view', { page: paths[location.pathname] || 'other' });
    document.addEventListener('click', event => {
      const button = event.target.closest('#add-to-cart, #checkout, #checkout-submit, #shop-now');
      if (button) faro.api.pushEvent('grot_journey_click', { control: button.id });
    });
  } catch {
    // Observability must never prevent the storefront from loading.
    console.warn('Grot frontend telemetry could not initialize.');
  }
}
