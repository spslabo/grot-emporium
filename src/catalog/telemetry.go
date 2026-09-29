package main

import (
	"context"
	"fmt"
	"log/slog"
	"os"
	"strconv"
	"time"

	"github.com/gin-gonic/gin"
	otelpyroscope "github.com/grafana/otel-profiling-go"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp"
	"go.opentelemetry.io/otel/propagation"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/trace"
)

func catalogResource(ctx context.Context) (*resource.Resource, error) {
	// Defaults first; deployment-provided resource attributes override them.
	defaults := resource.NewSchemaless(attribute.String("service.name", "grot-catalog"), attribute.String("service.namespace", "grot-emporium"))
	configured, err := resource.New(ctx, resource.WithFromEnv(), resource.WithTelemetrySDK(), resource.WithProcess())
	if err != nil {
		return nil, err
	}
	return resource.Merge(defaults, configured)
}

func initTracer(ctx context.Context) (*sdktrace.TracerProvider, error) {
	res, err := catalogResource(ctx)
	if err != nil {
		return nil, fmt.Errorf("building telemetry resource: %w", err)
	}
	exporter, err := otlptracehttp.New(ctx)
	if err != nil {
		return nil, fmt.Errorf("creating OTLP exporter: %w", err)
	}
	tp := sdktrace.NewTracerProvider(sdktrace.WithBatcher(exporter), sdktrace.WithResource(res))
	otel.SetTextMapPropagator(propagation.NewCompositeTextMapPropagator(propagation.TraceContext{}, propagation.Baggage{}))
	if os.Getenv("PYROSCOPE_ENABLED") == "true" {
		// Attribute CPU samples to the local entry span. Avoid dynamic span-name
		// labels and keep IDs on profile samples, never Prometheus series.
		otel.SetTracerProvider(otelpyroscope.NewTracerProvider(tp,
			otelpyroscope.WithSpanNameLabelScope(otelpyroscope.ScopeNone)))
	} else {
		otel.SetTracerProvider(tp)
	}
	return tp, nil
}

func configureLogging() {
	service := os.Getenv("OTEL_SERVICE_NAME")
	if service == "" {
		service = "grot-catalog"
	}
	slog.SetDefault(slog.New(slog.NewJSONHandler(os.Stdout, nil)).With("service_name", service, "service_namespace", "grot-emporium"))
}

var requestDuration = promauto.NewHistogramVec(prometheus.HistogramOpts{
	Name:    "http_server_request_duration_seconds",
	Help:    "Catalog HTTP duration by bounded method, route, and status.",
	Buckets: []float64{.005, .01, .025, .05, .1, .25, .5, 1, 2.5, 5, 10},
}, []string{"method", "route", "status"})

func accessLog() gin.HandlerFunc {
	return func(c *gin.Context) {
		start := time.Now()
		c.Next()
		route := c.FullPath()
		if route == "/health" || route == "/metrics" {
			return
		}
		if route == "" {
			route = "unmatched"
		}
		method := c.Request.Method
		switch method {
		case "GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE", "CONNECT":
		default:
			method = "OTHER"
		}
		requestDuration.WithLabelValues(method, route, strconv.Itoa(c.Writer.Status())).Observe(time.Since(start).Seconds())
		sc := trace.SpanContextFromContext(c.Request.Context())
		attrs := []any{"method", c.Request.Method, "route", route, "status", c.Writer.Status(), "duration_ms", float64(time.Since(start).Microseconds()) / 1000}
		if sc.IsValid() {
			attrs = append(attrs, "trace_id", sc.TraceID().String(), "span_id", sc.SpanID().String())
		}
		// Never log raw URLs/query strings, request bodies, customer IDs, or database credentials.
		slog.Info("http_request", attrs...)
	}
}
