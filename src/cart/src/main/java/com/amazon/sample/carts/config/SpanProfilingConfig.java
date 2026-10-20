package com.amazon.sample.carts.config;

import io.opentelemetry.sdk.autoconfigure.spi.AutoConfigurationCustomizerProvider;
import io.otel.pyroscope.PyroscopeOtelSpanProcessor;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/** Joins local entry spans to samples from the separately loaded Pyroscope agent. */
@Configuration(proxyBeanMethods = false)
@ConditionalOnProperty(name = "pyroscope.enabled", havingValue = "true")
public class SpanProfilingConfig {
    @Bean
    AutoConfigurationCustomizerProvider spanProfilingCustomizer() {
        return configuration -> configuration.addTracerProviderCustomizer((builder, properties) ->
            builder.addSpanProcessor(new PyroscopeOtelSpanProcessor()));
    }
}
