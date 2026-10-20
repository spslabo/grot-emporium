package main

import (
	"context"
	"net/http"
	"net/http/httptest"
	"runtime/pprof"
	"testing"

	"go.opentelemetry.io/otel"
)

func TestSpanProfilingAttributesLocalEntry(t *testing.T) {
	sink := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(200) }))
	defer sink.Close()
	t.Setenv("OTEL_EXPORTER_OTLP_ENDPOINT", sink.URL)
	t.Setenv("PYROSCOPE_ENABLED", "true")
	old := otel.GetTracerProvider()
	defer otel.SetTracerProvider(old)
	tp, err := initTracer(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	defer tp.Shutdown(context.Background())
	tracer := otel.Tracer("test")
	ctx, root := tracer.Start(context.Background(), "request")
	spanID, ok := pprof.Label(ctx, "span_id")
	if !ok || spanID != root.SpanContext().SpanID().String() {
		t.Fatal("missing exact root span label")
	}
	traceID, _ := pprof.Label(ctx, "trace_id")
	if traceID != root.SpanContext().TraceID().String() {
		t.Fatal("missing trace label")
	}
	if _, ok := pprof.Label(ctx, "span_name"); ok {
		t.Fatal("dynamic span names must not become profile labels")
	}
	childCtx, child := tracer.Start(ctx, "child")
	childLabel, _ := pprof.Label(childCtx, "span_id")
	if childLabel != spanID {
		t.Fatal("child samples must remain attributed to local entry span")
	}
	child.End()
	root.End()
}
