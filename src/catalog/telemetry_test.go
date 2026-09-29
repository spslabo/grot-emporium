package main

import (
	"context"
	"go.opentelemetry.io/otel/attribute"
	"testing"
)

func TestCatalogResourceReadsDeploymentIdentity(t *testing.T) {
	t.Setenv("OTEL_SERVICE_NAME", "grot-catalog")
	t.Setenv("OTEL_RESOURCE_ATTRIBUTES", "service.namespace=grot-emporium,deployment.environment.name=demo,service.version=test-sha")
	res, err := catalogResource(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	for key, want := range map[string]string{"service.name": "grot-catalog", "service.namespace": "grot-emporium", "deployment.environment.name": "demo", "service.version": "test-sha"} {
		got, ok := res.Set().Value(attribute.Key(key))
		if !ok || got.AsString() != want {
			t.Errorf("%s = %v; want %s", key, got, want)
		}
	}
}
