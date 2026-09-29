package main

import (
	"fmt"
	"github.com/grafana/pyroscope-go"
	"os"
)

func startProfiling() (*pyroscope.Profiler, error) {
	if os.Getenv("PYROSCOPE_ENABLED") != "true" {
		return nil, nil
	}
	server := os.Getenv("PYROSCOPE_SERVER_ADDRESS")
	if server == "" {
		return nil, fmt.Errorf("PYROSCOPE_SERVER_ADDRESS is required when profiling is enabled")
	}
	app := os.Getenv("OTEL_SERVICE_NAME")
	if app == "" {
		app = "grot-catalog"
	}
	environment := os.Getenv("DEPLOYMENT_ENVIRONMENT")
	if environment == "" {
		environment = "demo"
	}
	return pyroscope.Start(pyroscope.Config{
		ApplicationName: app,
		Logger:          pyroscope.StandardLogger,
		ServerAddress:   server,
		Tags:            map[string]string{"service_name": app, "service_namespace": "grot-emporium", "deployment_environment": environment},
		ProfileTypes:    []pyroscope.ProfileType{pyroscope.ProfileCPU, pyroscope.ProfileAllocObjects, pyroscope.ProfileAllocSpace, pyroscope.ProfileInuseObjects, pyroscope.ProfileInuseSpace, pyroscope.ProfileGoroutines},
	})
}
