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
      assertTrue(exported.get(0).getOutput().stream().flatMap(m -> m.getParts().stream())
        .allMatch(p -> p.getText() == null || p.getText().isEmpty()));
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

  @Test void fullCaptureAggregatesStreamAndPreservesSeparateMetadataChunks() throws Exception {
    List<Generation> exported = new ArrayList<>();
    try (Agento11yClient client = new Agento11yClient(new Agento11yClientConfig()
        .setContentCapture(ContentCaptureMode.FULL_WITH_METADATA_SPANS)
        .setTags(java.util.Map.of("cluster", "test-cluster"))
        .setGenerationExporter(request -> { exported.addAll(request.getGenerations()); return new ExportGenerationsResponse(); }))) {
      DefaultListableBeanFactory beans = new DefaultListableBeanFactory(); beans.registerSingleton("client", client);
      ChatTelemetry telemetry = new ChatTelemetry(beans.getBeanProvider(Agento11yClient.class), "bedrock", "requested-model", "test-version");
      ChatResponse first = new ChatResponse(List.of(new org.springframework.ai.chat.model.Generation(new AssistantMessage("Hello "))),
        ChatResponseMetadata.builder().id("response-123").model("actual-model").build());
      ChatResponse last = new ChatResponse(List.of(new org.springframework.ai.chat.model.Generation(new AssistantMessage("world"),
        org.springframework.ai.chat.metadata.ChatGenerationMetadata.builder().finishReason("STOP").build())));
      ChatResponse usage = new ChatResponse(List.of(), ChatResponseMetadata.builder().usage(new DefaultUsage(11, 7)).build());
      telemetry.observe(Flux.just(first, last, usage), UUID.randomUUID().toString(), false, "system instructions", "user question").blockLast();
      client.flush();
      assertEquals(1, exported.size());
      Generation g = exported.get(0);
      assertEquals("Hello world", g.getOutput().get(0).getParts().get(0).getText());
      assertEquals("user question", g.getInput().get(0).getParts().get(0).getText());
      assertEquals("system instructions", g.getSystemPrompt());
      assertEquals("response-123", g.getResponseId());
      assertEquals("actual-model", g.getResponseModel());
      assertEquals("STOP", g.getStopReason());
      assertEquals("requested-model", g.getTags().get("requested_model"));
      assertEquals("bedrock", g.getModel().getProvider());
      assertEquals("test-cluster", g.getTags().get("cluster"));
      assertEquals(11, g.getUsage().getInputTokens());
      assertEquals(7, g.getUsage().getOutputTokens());
      assertEquals(300, g.getMaxTokens());
      assertEquals(0.6, g.getTemperature());
    }
  }

  @Test void injectedErrorsAreTagged() throws Exception {
    List<Generation> exported = new ArrayList<>();
    try (Agento11yClient client = new Agento11yClient(new Agento11yClientConfig()
        .setGenerationExporter(request -> { exported.addAll(request.getGenerations()); return new ExportGenerationsResponse(); }))) {
      DefaultListableBeanFactory beans = new DefaultListableBeanFactory();
      beans.registerSingleton("client", client);
      ChatTelemetry telemetry = new ChatTelemetry(beans.getBeanProvider(Agento11yClient.class), "bedrock", "test", "test");
      assertThrows(IllegalStateException.class, () -> telemetry.observe(Flux.error(new IllegalStateException("Injected synthetic chat failure")), UUID.randomUUID().toString(), true).blockLast());
      client.flush();
      assertEquals(1, exported.size());
      assertEquals("injected_error", exported.get(0).getTags().get("fault"));
      assertEquals("true", exported.get(0).getTags().get("synthetic"));
    }
  }

  @Test void disabledInstrumentationPreservesTheStream() {
    DefaultListableBeanFactory beans = new DefaultListableBeanFactory();
    ChatTelemetry telemetry = new ChatTelemetry(beans.getBeanProvider(Agento11yClient.class), "mock", "test", "local");
    Flux<ChatResponse> source = Flux.empty();
    assertSame(source, telemetry.observe(source, UUID.randomUUID().toString()));
  }
}
