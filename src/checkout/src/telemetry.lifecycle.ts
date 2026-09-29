import { Injectable, OnApplicationShutdown } from '@nestjs/common';
import otelSDK from './tracing';
import { stopProfiling } from './profiling';

@Injectable()
export class TelemetryLifecycle implements OnApplicationShutdown {
  async onApplicationShutdown(): Promise<void> {
    // Let Nest await flushing before it exits; no competing process.exit handler.
    const results = await Promise.allSettled([otelSDK.shutdown(), stopProfiling()]);
    if (results.some(result => result.status === 'rejected')) {
      console.warn(JSON.stringify({ event: 'telemetry_shutdown_failed', service_name: 'grot-checkout' }));
    }
  }
}
