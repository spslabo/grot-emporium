package com.amazon.sample.ui.chat;

import com.grafana.agento11y.sdk.*;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.metadata.ChatResponseMetadata;
import org.springframework.ai.chat.metadata.DefaultUsage;
import org.springframework.beans.factory.support.DefaultListableBeanFactory;
import reactor.core.publisher.Flux;
import static org.junit.jupiter.api.Assertions.*;

class ChatTelemetryTest {
  @Test void completedStreamExportsMetadataWithoutResponseText() throws Exception {
    List<Generation> exported = new ArrayList<>();
    try (Agento11yClient client = new Agento11yClient(new Agento11yClientConfig()
        .setContentCapture(ContentCaptureMode.METADATA_ONLY)
        .setGenerationExporter(request -> { exported.addAll(request.getGenerations()); return new ExportGenerationsResponse(); }))) {
      DefaultListableBeanFactory beans = new DefaultListableBeanFactory();
      beans.registerSingleton("client", client);
      ChatTelemetry telemetry = new ChatTelemetry(beans.getBeanProvider(Agento11yClient.class), "openai", "test-model", "test-version");
      String conversationId = UUID.randomUUID().toString();
      ChatResponse response = new ChatResponse(
        List.of(new org.springframework.ai.chat.model.Generation(new AssistantMessage("private model text"))),
        ChatResponseMetadata.builder().model("reported-test-model").usage(new DefaultUsage(11, 7)).build());
      assertSame(response, telemetry.observe(Flux.just(response), conversationId).blockLast());
      client.flush();
      assertEquals(1, exported.size());
      assertEquals(conversationId, exported.get(0).getConversationId());
      assertEquals("grot-shopping-assistant", exported.get(0).getAgentName());
      assertTrue(exported.get(0).getOutput().isEmpty());
      assertTrue(exported.get(0).getInput().isEmpty());
      assertEquals(11, exported.get(0).getUsage().getInputTokens());
      assertEquals(7, exported.get(0).getUsage().getOutputTokens());
      assertEquals("reported-test-model", exported.get(0).getResponseModel());
    }
  }

  @Test void errorsAndCancellationExportExactlyOnce() throws Exception {
    List<Generation> exported = new ArrayList<>();
    try (Agento11yClient client = new Agento11yClient(new Agento11yClientConfig()
        .setContentCapture(ContentCaptureMode.METADATA_ONLY)
        .setGenerationExporter(request -> { exported.addAll(request.getGenerations()); return new ExportGenerationsResponse(); }))) {
      DefaultListableBeanFactory beans = new DefaultListableBeanFactory();
      beans.registerSingleton("client", client);
      ChatTelemetry telemetry = new ChatTelemetry(beans.getBeanProvider(Agento11yClient.class), "openai", "test-model", "test-version");
      assertThrows(IllegalStateException.class, () -> telemetry.observe(Flux.error(new IllegalStateException("private provider detail")), UUID.randomUUID().toString()).blockLast());
      var subscription = telemetry.observe(Flux.never(), UUID.randomUUID().toString()).subscribe();
      subscription.dispose();
      client.flush();
      assertEquals(2, exported.size());
      assertTrue(exported.stream().allMatch(g -> g.getOutput().isEmpty() && g.getInput().isEmpty()));
    }
  }

  @Test void disabledInstrumentationPreservesTheStream() {
    DefaultListableBeanFactory beans = new DefaultListableBeanFactory();
    ChatTelemetry telemetry = new ChatTelemetry(beans.getBeanProvider(Agento11yClient.class), "mock", "test", "local");
    Flux<ChatResponse> source = Flux.empty();
    assertSame(source, telemetry.observe(source, UUID.randomUUID().toString()));
  }
}
