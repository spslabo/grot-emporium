package com.amazon.sample.carts.config;

import io.opentelemetry.sdk.autoconfigure.spi.AutoConfigurationCustomizerProvider;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import static org.assertj.core.api.Assertions.assertThat;

class SpanProfilingConfigTest {
    private final ApplicationContextRunner context = new ApplicationContextRunner()
        .withUserConfiguration(SpanProfilingConfig.class);

    @Test void disabledWithoutProfiler() {
        context.run(application -> assertThat(application)
            .doesNotHaveBean(AutoConfigurationCustomizerProvider.class));
    }

    @Test void enabledWithProfiler() {
        context.withPropertyValues("pyroscope.enabled=true")
            .run(application -> assertThat(application)
                .hasSingleBean(AutoConfigurationCustomizerProvider.class));
    }
}
