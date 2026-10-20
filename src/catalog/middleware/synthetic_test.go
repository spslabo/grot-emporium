package middleware

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"go.opentelemetry.io/otel/codes"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/sdk/trace/tracetest"
)

func demoRouter() *gin.Engine {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	cc := NewChaosController()
	cc.SetupChaosRoutes(r)
	r.GET("/catalog/products", cc.ChaosMiddleware(), func(c *gin.Context) { c.JSON(200, gin.H{"ok": true}) })
	return r
}

func TestRequestScopedFaults(t *testing.T) {
	r := demoRouter()
	for _, tc := range []struct {
		kind, delay string
		status      int
	}{
		{"", "", 200}, {"error", "", 500}, {"latency", "20", 200}, {"latency", "5001", 400},
		{"latency", "-1", 400}, {"latency", "invalid", 400}, {"other", "", 400},
	} {
		t.Run(tc.kind+tc.delay, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodGet, "/catalog/products", nil)
			req.Header.Set("X-Grot-Synthetic-Fault", tc.kind)
			req.Header.Set("X-Grot-Delay-Ms", tc.delay)
			w := httptest.NewRecorder()
			start := time.Now()
			r.ServeHTTP(w, req)
			if w.Code != tc.status {
				t.Fatalf("got %d want %d", w.Code, tc.status)
			}
			if tc.kind == "latency" && tc.status == 200 && time.Since(start) < 20*time.Millisecond {
				t.Fatal("delay not applied")
			}
			// Faults leave no persistent settings on the next request.
			healthy := httptest.NewRecorder()
			r.ServeHTTP(healthy, httptest.NewRequest(http.MethodGet, "/catalog/products", nil))
			if healthy.Code != 200 || healthy.Header().Get("X-Grot-Synthetic-Fault") != "" {
				t.Fatal("fault leaked to unrelated request")
			}
		})
	}
}

func TestFaultMarksTraceAndHonorsCancellation(t *testing.T) {
	exporter := tracetest.NewInMemoryExporter()
	provider := sdktrace.NewTracerProvider(sdktrace.WithSyncer(exporter))
	defer provider.Shutdown(context.Background())
	ctx, span := provider.Tracer("test").Start(context.Background(), "catalog")
	req := httptest.NewRequest(http.MethodGet, "/catalog/products", nil).WithContext(ctx)
	req.Header.Set("X-Grot-Synthetic-Fault", "error")
	w := httptest.NewRecorder()
	demoRouter().ServeHTTP(w, req)
	span.End()
	spans := exporter.GetSpans()
	if len(spans) != 1 || spans[0].Status.Code != codes.Error {
		t.Fatal("synthetic 500 was not recorded as trace error")
	}
	found := false
	for _, a := range spans[0].Attributes {
		if string(a.Key) == "grot.synthetic" && a.Value.AsBool() {
			found = true
		}
	}
	if !found {
		t.Fatal("synthetic trace label missing")
	}
	cancelled, cancel := context.WithCancel(context.Background())
	cancel()
	req = httptest.NewRequest(http.MethodGet, "/catalog/products", nil).WithContext(cancelled)
	req.Header.Set("X-Grot-Synthetic-Fault", "latency")
	req.Header.Set("X-Grot-Delay-Ms", "5000")
	start := time.Now()
	demoRouter().ServeHTTP(httptest.NewRecorder(), req)
	if time.Since(start) > time.Second {
		t.Fatal("cancelled delay kept running")
	}
}
