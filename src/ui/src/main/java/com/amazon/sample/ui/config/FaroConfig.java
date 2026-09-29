package com.amazon.sample.ui.config;

import java.net.URI;
import java.net.URISyntaxException;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Component;

/** Only explicitly public configuration may be rendered into browser HTML. */
@Component("faroConfig")
public class FaroConfig {
  private final boolean enabled;
  private final String url;

  public FaroConfig(Environment environment) {
    enabled = environment.getProperty("grot.faro.enabled", Boolean.class, false);
    if (!enabled) {
      url = ""; // Do not disclose an inactive destination in page source.
      return;
    }
    String configured = environment.getProperty("grot.faro.url", "");
    try {
      URI parsed = new URI(configured);
      boolean path = configured.startsWith("/") && !configured.startsWith("//")
        && !configured.contains("\\") && parsed.getRawAuthority() == null;
      boolean absolute = parsed.getHost() != null &&
        ("https".equalsIgnoreCase(parsed.getScheme()) ||
          ("http".equalsIgnoreCase(parsed.getScheme()) && "localhost".equals(parsed.getHost())));
      if ((!path && !absolute) || parsed.getRawUserInfo() != null ||
          parsed.getRawQuery() != null || parsed.getRawFragment() != null) {
        throw new IllegalArgumentException("Faro requires a same-origin path or an allowed public collector URL");
      }
      if (absolute && !environment.getProperty("grot.faro.public-url-acknowledged", Boolean.class, false)) {
        throw new IllegalArgumentException("Absolute Faro URLs are browser-visible; acknowledge public exposure or use a same-origin proxy");
      }
      url = configured;
    } catch (URISyntaxException ignored) {
      // URI parser exceptions include the input; never attach one as a cause.
      throw new IllegalArgumentException("Invalid Faro collector URL");
    }
  }

  public boolean isEnabled() { return enabled; }
  public String getUrl() { return url; }
}
