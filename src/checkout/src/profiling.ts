import { spanProfiling } from './span-profiling';

let profiler: typeof import('@pyroscope/nodejs') | undefined;

export async function startProfiling(): Promise<void> {
  if (process.env.PYROSCOPE_ENABLED !== 'true') return;
  if (!process.env.PYROSCOPE_SERVER_ADDRESS) throw new Error('PYROSCOPE_SERVER_ADDRESS is required');
  // Lazy load the native profiler so unprofiled development needs no native module.
  profiler = await import('@pyroscope/nodejs');
  profiler.init({
    appName: process.env.OTEL_SERVICE_NAME || 'grot-checkout',
    serverAddress: process.env.PYROSCOPE_SERVER_ADDRESS,
    tags: { service_namespace: 'grot-emporium', deployment_environment: process.env.DEPLOYMENT_ENVIRONMENT || 'demo' },
  });
  profiler.start();
  spanProfiling.setWriter(labels => profiler!.default.setLabels(labels));
}
export async function stopProfiling(): Promise<void> {
  spanProfiling.setWriter(undefined);
  if (profiler) await profiler.stop();
}
