package com.amazon.sample.ui.config;

import org.junit.jupiter.api.Test;
import org.springframework.mock.env.MockEnvironment;
import static org.junit.jupiter.api.Assertions.*;

class FaroConfigTest {
  @Test void disabledTelemetryNeverDisclosesItsConfiguredUrl() {
    var config = new FaroConfig(new MockEnvironment().withProperty("grot.faro.url", "https://private.example.invalid/collect"));
    assertFalse(config.isEnabled());
    assertEquals("", config.getUrl());
  }

  @Test void acceptsSameOriginProxyWithoutPublishingUpstream() {
    var config = new FaroConfig(new MockEnvironment().withProperty("grot.faro.enabled", "true").withProperty("grot.faro.url", "/telemetry"));
    assertEquals("/telemetry", config.getUrl());
  }

  @Test void absoluteUrlNeedsExplicitPublicAcknowledgement() {
    var env = new MockEnvironment().withProperty("grot.faro.enabled", "true")
      .withProperty("grot.faro.url", "https://public.example.invalid/collect");
    assertThrows(IllegalArgumentException.class, () -> new FaroConfig(env));
    env.withProperty("grot.faro.public-url-acknowledged", "true");
    assertTrue(new FaroConfig(env).isEnabled());
  }

  @Test void invalidDestinationsNeverAppearInErrors() {
    for (String value : new String[]{"https://user:private-marker@example.invalid", "//private-marker.example.invalid", "http://private-marker.example.invalid", "https://example.invalid/?token=private-marker", "private-marker with spaces"}) {
      var env = new MockEnvironment().withProperty("grot.faro.enabled", "true")
        .withProperty("grot.faro.url", value).withProperty("grot.faro.public-url-acknowledged", "true");
      var error = assertThrows(IllegalArgumentException.class, () -> new FaroConfig(env));
      assertFalse(error.toString().contains("private-marker"));
      assertNull(error.getCause());
    }
  }
}
