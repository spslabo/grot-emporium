package main

import "testing"

func TestProfilingIsOptIn(t *testing.T) {
	t.Setenv("PYROSCOPE_ENABLED", "false")
	profiler, err := startProfiling()
	if err != nil || profiler != nil {
		t.Fatalf("disabled profiling returned %v, %v", profiler, err)
	}
}

func TestEnabledProfilingRequiresAnEndpoint(t *testing.T) {
	t.Setenv("PYROSCOPE_ENABLED", "true")
	t.Setenv("PYROSCOPE_SERVER_ADDRESS", "")
	if _, err := startProfiling(); err == nil {
		t.Fatal("missing endpoint should fail fast")
	}
}
