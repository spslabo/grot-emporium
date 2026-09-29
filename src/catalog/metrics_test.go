package main

import (
	"github.com/gin-gonic/gin"
	"github.com/prometheus/client_golang/prometheus"
	"net/http/httptest"
	"testing"
)

func TestRequestHistogramUsesBoundedLabels(t *testing.T) {
	requestDuration.Reset()
	router := gin.New()
	router.Use(accessLog())
	router.GET("/catalog/products/:id", func(c *gin.Context) { c.Status(200) })
	for _, path := range []string{"/catalog/products/first", "/catalog/products/second"} {
		router.ServeHTTP(httptest.NewRecorder(), httptest.NewRequest("GET", path, nil))
	}
	for _, method := range []string{"CUSTOMA", "CUSTOMB"} {
		request := httptest.NewRequest(method, "/unknown/private-path", nil)
		request.Host = "untrusted-host.example"
		router.ServeHTTP(httptest.NewRecorder(), request)
	}
	families, err := prometheus.DefaultGatherer.Gather()
	if err != nil {
		t.Fatal(err)
	}
	for _, family := range families {
		if family.GetName() != "http_server_request_duration_seconds" {
			continue
		}
		if len(family.Metric) != 2 {
			t.Fatalf("expected 2 bounded series, got %d", len(family.Metric))
		}
		for _, metric := range family.Metric {
			if metric.GetHistogram().GetSampleCount() != 2 {
				t.Fatal("expected two requests per series")
			}
			for _, label := range metric.Label {
				if label.GetName() == "route" && label.GetValue() != "/catalog/products/:id" && label.GetValue() != "unmatched" {
					t.Fatal("raw path leaked into metric")
				}
				if label.GetName() == "host" {
					t.Fatal("unbounded host label")
				}
			}
		}
		return
	}
	t.Fatal("HTTP histogram not registered")
}
