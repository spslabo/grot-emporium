import { getNodeAutoInstrumentations } from '@opentelemetry/auto-instrumentations-node';
import { NodeSDK } from '@opentelemetry/sdk-node';
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http';
import { BatchSpanProcessor } from '@opentelemetry/sdk-trace-base';
import { spanProfiling } from './span-profiling';

const otelSDK = new NodeSDK({
  spanProcessors: [new BatchSpanProcessor(new OTLPTraceExporter()),
    ...(process.env.PYROSCOPE_ENABLED === 'true' ? [spanProfiling] : [])],
  ...(process.env.PYROSCOPE_ENABLED === 'true' ? { contextManager: spanProfiling } : {}),
  instrumentations: [getNodeAutoInstrumentations({
    '@opentelemetry/instrumentation-fs': { enabled: false },
  })],
});
// This module is imported before Nest/HTTP/database modules in main.ts.
if (process.env.OTEL_SDK_DISABLED === 'false') otelSDK.start();
export default otelSDK;
