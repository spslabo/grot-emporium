package com.amazon.sample.ui.config.chat;

import com.grafana.agento11y.sdk.Agento11yClient;
import com.grafana.agento11y.sdk.Agento11yClientConfig;
import com.grafana.agento11y.sdk.ContentCaptureMode;
import io.opentelemetry.api.OpenTelemetry;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class AgentObservabilityConfig {
  @Bean(destroyMethod = "shutdown")
  @ConditionalOnProperty(name = "grot.agent-observability.enabled", havingValue = "true")
  public Agento11yClient agentObservability(OpenTelemetry telemetry,
      @org.springframework.beans.factory.annotation.Value("${AGENTO11Y_CONTENT_CAPTURE_MODE:metadata_only}") String captureMode) {
    // AGENTO11Y_* env vars configure authenticated generation export separately from OTLP.
    // Reuse Spring's OTel SDK. Content export requires an explicit capture setting.
    if (System.getenv("AGENTO11Y_ENDPOINT") == null || System.getenv("AGENTO11Y_ENDPOINT").isBlank()) {
      throw new IllegalStateException("AGENTO11Y_ENDPOINT is required when Agent Observability is enabled");
    }
    return new Agento11yClient(new Agento11yClientConfig()
      .setTracer(telemetry.getTracer("grot-shopping-assistant"))
      .setMeter(telemetry.getMeter("grot-shopping-assistant"))
      .setContentCapture(ContentCaptureMode.valueOf(captureMode.toUpperCase(java.util.Locale.ROOT))));
  }
}
