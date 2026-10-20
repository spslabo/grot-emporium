package middleware

import (
	"log/slog"
	"net/http"
	"strconv"
	"time"

	"github.com/gin-gonic/gin"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/codes"
	"go.opentelemetry.io/otel/trace"
)

// Request-local demo faults: no persistent state, global switches or health changes.
// This is a private synthetic demo facility, not an authentication mechanism.
func syntheticFault(c *gin.Context) bool {
	kind := c.GetHeader("X-Grot-Synthetic-Fault")
	if kind == "" {
		return false
	}
	if c.Request.Method != http.MethodGet || (kind != "error" && kind != "latency") {
		c.AbortWithStatusJSON(http.StatusBadRequest, gin.H{"error": "invalid synthetic fault"})
		return true
	}
	delay := 0
	if kind == "latency" {
		var err error
		delay, err = strconv.Atoi(c.GetHeader("X-Grot-Delay-Ms"))
		if err != nil || delay < 1 || delay > 5000 {
			c.AbortWithStatusJSON(http.StatusBadRequest, gin.H{"error": "synthetic delay must be 1–5000 ms"})
			return true
		}
	}
	span := trace.SpanFromContext(c.Request.Context())
	span.SetAttributes(attribute.Bool("grot.synthetic", true), attribute.String("grot.fault", kind))
	c.Header("X-Grot-Synthetic-Fault", kind)
	fields := []any{"synthetic", true, "fault", kind, "delay_ms", delay, "trace_id", span.SpanContext().TraceID().String()}
	if kind == "error" {
		span.SetStatus(codes.Error, "synthetic demo failure")
		slog.Error("Synthetic catalog failure", fields...)
		c.AbortWithStatusJSON(http.StatusInternalServerError, gin.H{"error": "synthetic demo failure", "synthetic": true})
		return true
	}
	slog.Info("Synthetic catalog latency", fields...)
	timer := time.NewTimer(time.Duration(delay) * time.Millisecond)
	defer timer.Stop()
	select {
	case <-timer.C:
		return false
	case <-c.Request.Context().Done():
		c.Abort()
		return true
	}
}
