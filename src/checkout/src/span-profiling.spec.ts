import { ROOT_CONTEXT, trace, Span } from '@opentelemetry/api';
import { BasicTracerProvider, AlwaysOffSampler } from '@opentelemetry/sdk-trace-base';
import { SpanProfiling } from './span-profiling';

const delay = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

describe('span sample attribution', () => {
  let profiling: SpanProfiling;
  let provider: BasicTracerProvider;
  let labels: Record<string, string>;
  beforeEach(() => {
    labels = {};
    profiling = new SpanProfiling().enable();
    profiling.setWriter(value => { labels = value; });
    provider = new BasicTracerProvider({ spanProcessors: [profiling] });
  });
  afterEach(async () => { await provider.shutdown(); });

  function assertRoot(span: Span) {
    expect(labels).toEqual({ trace_id: span.spanContext().traceId, span_id: span.spanContext().spanId });
  }

  it('keeps simultaneous requests isolated across await and synchronous child scopes', async () => {
    const tracer = provider.getTracer('test');
    const a = tracer.startSpan('request-a', {}, ROOT_CONTEXT);
    const b = tracer.startSpan('request-b', {}, ROOT_CONTEXT);
    await Promise.all([a, b].map((root, i) => profiling.with(trace.setSpan(ROOT_CONTEXT, root), async () => {
      assertRoot(root);
      await delay(i ? 1 : 4);
      assertRoot(root);
      const child = tracer.startSpan('child', {}, profiling.active());
      profiling.with(trace.setSpan(profiling.active(), child), () => assertRoot(root));
      child.end();
      await delay(i ? 4 : 1);
      assertRoot(root);
      root.end();
    })));
    expect(labels).toEqual({});
  });

  it('restores labels after exceptions, including nested scopes', () => {
    const root = provider.getTracer('test').startSpan('request', {}, ROOT_CONTEXT);
    expect(() => profiling.with(trace.setSpan(ROOT_CONTEXT, root), () => {
      assertRoot(root);
      throw new Error('test');
    })).toThrow('test');
    expect(labels).toEqual({});
    root.end();
  });

  it('does not attribute unsampled spans', async () => {
    const off = new BasicTracerProvider({ sampler: new AlwaysOffSampler(), spanProcessors: [profiling] });
    const root = off.getTracer('test').startSpan('unsampled', {}, ROOT_CONTEXT);
    profiling.with(trace.setSpan(ROOT_CONTEXT, root), () => expect(labels).toEqual({}));
    root.end();
    await off.shutdown();
  });

  it('only marks local root spans and is inert without an active profiler', () => {
    const tracer = provider.getTracer('test');
    const root = tracer.startSpan('request', {}, ROOT_CONTEXT);
    const child = tracer.startSpan('child', {}, trace.setSpan(ROOT_CONTEXT, root));
    expect((root as any).attributes['pyroscope.profile.id']).toBe(root.spanContext().spanId);
    expect((child as any).attributes['pyroscope.profile.id']).toBeUndefined();
    profiling.setWriter(undefined);
    const disabled = tracer.startSpan('disabled', {}, ROOT_CONTEXT);
    expect((disabled as any).attributes['pyroscope.profile.id']).toBeUndefined();
    root.end(); child.end(); disabled.end();
  });
});
