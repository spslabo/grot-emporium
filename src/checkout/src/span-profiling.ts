import { createHook, AsyncHook } from 'node:async_hooks';
import { Context, Span, trace, TraceFlags } from '@opentelemetry/api';
import { AsyncLocalStorageContextManager } from '@opentelemetry/context-async-hooks';
import { ReadableSpan, Span as RecordingSpan, SpanProcessor } from '@opentelemetry/sdk-trace-base';

type Labels = Record<string, string>;

/** Attribute wall samples to a sampled local entry span, including async continuations.
 * Labels are sample metadata, not exporter/Prometheus series labels.
 */
export class SpanProfiling extends AsyncLocalStorageContextManager implements SpanProcessor {
  private roots = new WeakMap<Span, Labels>();
  private labels: Labels = {};
  private writer?: (labels: Labels) => void;
  private hook?: AsyncHook;
  private stack: Labels[] = [];

  setWriter(writer?: (labels: Labels) => void): void {
    this.writer = writer;
  }

  private select(ctx: Context): Labels {
    const span = trace.getSpan(ctx);
    return (span && this.roots.get(span)) || {};
  }

  private apply(labels: Labels): void {
    this.labels = labels;
    this.writer?.(labels);
  }

  enable(): this {
    super.enable();
    if (!this.hook) {
      // AsyncLocalStorage carries OTel context through await/timers. Switch the
      // native sampler's labels at callback boundaries, not for a Promise lifetime.
      this.hook = createHook({
        before: () => {
          this.stack.push(this.labels);
          this.apply(this.select(this.active()));
        },
        after: () => this.apply(this.stack.pop() || {}),
      }).enable();
    }
    return this;
  }

  disable(): this {
    this.hook?.disable();
    this.hook = undefined;
    this.stack = [];
    this.apply({});
    super.disable();
    return this;
  }

  with<A extends unknown[], F extends (...args: A) => ReturnType<F>>(
    ctx: Context, fn: F, thisArg?: ThisParameterType<F>, ...args: A
  ): ReturnType<F> {
    return super.with(ctx, (() => {
      const previous = this.labels;
      this.apply(this.select(ctx));
      try { return fn.apply(thisArg, args); }
      finally { this.apply(previous); }
    }) as F);
  }

  onStart(span: RecordingSpan, parentContext: Context): void {
    if (!this.writer || !(span.spanContext().traceFlags & TraceFlags.SAMPLED)) return;
    const parent = trace.getSpan(parentContext);
    const inherited = parent && this.roots.get(parent);
    const root = inherited || {
      trace_id: span.spanContext().traceId,
      span_id: span.spanContext().spanId,
    };
    this.roots.set(span, root);
    if (!inherited) span.setAttribute('pyroscope.profile.id', root.span_id);
  }

  onEnd(_span: ReadableSpan): void {}
  async forceFlush(): Promise<void> {}
  async shutdown(): Promise<void> { this.disable(); }
}

export const spanProfiling = new SpanProfiling();
