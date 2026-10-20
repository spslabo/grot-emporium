package com.amazon.sample.ui.chat;

import com.grafana.agento11y.sdk.*;
import io.opentelemetry.context.Context;
import io.opentelemetry.context.Scope;
import java.time.Instant;
import java.util.Map;
import java.util.concurrent.CancellationException;
import java.util.concurrent.atomic.AtomicReference;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.slf4j.LoggerFactory;
import reactor.core.publisher.Flux;
import reactor.core.publisher.SignalType;

@Component
public class ChatTelemetry {
  private final ObjectProvider<Agento11yClient> clients;
  private final String provider;
  private final String model;
  private final String version;
  @Value("${retail.ui.chat.max-tokens:300}") private long maxTokens = 300;
  @Value("${retail.ui.chat.temperature:0.6}") private double temperature = 0.6;

  public ChatTelemetry(ObjectProvider<Agento11yClient> clients,
      @Value("${retail.ui.chat.provider:mock}") String provider,
      @Value("${retail.ui.chat.model:unknown}") String model,
      @Value("${SERVICE_VERSION:local}") String version) {
    this.clients = clients; this.provider = provider; this.model = model; this.version = version;
  }

  public Flux<ChatResponse> observe(Flux<ChatResponse> source, String conversationId) {
    return observe(source, conversationId, false);
  }

  public Flux<ChatResponse> observe(Flux<ChatResponse> source, String conversationId, boolean syntheticFailure) {
    return observe(source, conversationId, syntheticFailure, "", "");
  }

  public Flux<ChatResponse> observe(Flux<ChatResponse> source, String conversationId,
      boolean syntheticFailure, String systemPrompt, String userMessage) {
    Agento11yClient client = clients.getIfAvailable();
    if (client == null || "mock".equals(provider)) return source;
    Context parent = Context.current();
    return Flux.defer(() -> {
      Instant started = Instant.now();
      AtomicReference<Instant> first = new AtomicReference<>();
      AtomicReference<ChatResponse> usageResponse = new AtomicReference<>();
      AtomicReference<Throwable> failure = new AtomicReference<>();
      StringBuffer answer = new StringBuffer();
      AtomicReference<String> responseId = new AtomicReference<>();
      AtomicReference<String> responseModel = new AtomicReference<>();
      AtomicReference<String> stopReason = new AtomicReference<>();
      return source.doOnNext(response -> {
        if (response.getResult() != null && response.getResult().getOutput() != null
            && response.getResult().getOutput().getText() != null
            && !response.getResult().getOutput().getText().isEmpty()) {
          first.compareAndSet(null, Instant.now());
          answer.append(response.getResult().getOutput().getText());
        }
        // Finish/identity metadata can arrive on a different chunk from token usage.
        if (response.getMetadata() != null) {
          String id = response.getMetadata().getId();
          if (id != null && !id.isBlank()) responseId.set(id);
          String actualModel = response.getMetadata().getModel();
          if (actualModel != null && !actualModel.isBlank()) responseModel.set(actualModel);
        }
        if (response.getResult() != null && response.getResult().getMetadata() != null) {
          String reason = response.getResult().getMetadata().getFinishReason();
          if (reason != null && !reason.isBlank()) stopReason.set(reason);
        }
        if (response.getMetadata() != null && response.getMetadata().getUsage() != null
            && response.getMetadata().getUsage().getTotalTokens() > 0) usageResponse.set(response);
      }).doOnError(failure::set).doFinally(signal -> {
        // Record with explicit timestamps on ONE thread. A recorder owns a thread-local
        // content-capture scope; keeping it open across Reactor threads would leak context.
        try (Scope scope = parent.makeCurrent()) {
          GenerationStart start = new GenerationStart().setConversationId(conversationId)
            .setAgentName("grot-shopping-assistant").setAgentVersion(version)
            .setModel(new ModelRef().setProvider(provider).setName(model))
            .setStartedAt(started).setSystemPrompt(systemPrompt)
            .setMaxTokens(maxTokens).setTemperature(temperature)
            .setTags(syntheticFailure
              ? Map.of("app", "grot-emporium", "environment", "demo", "model_provider", provider, "requested_model", model,
                  "synthetic", "true", "fault", "injected_error")
              : Map.of("app", "grot-emporium", "environment", "demo", "model_provider", provider, "requested_model", model));
          try (GenerationRecorder recorder = client.startStreamingGeneration(start)) {
            GenerationResult result = new GenerationResult().setCompletedAt(Instant.now())
              .setResponseId(responseId.get()).setResponseModel(responseModel.get()).setStopReason(stopReason.get())
              .setMetadata(Map.of("stream_outcome", signal.name()));
            if (userMessage != null && !userMessage.isEmpty()) result.setInput(java.util.List.of(
              new Message().setRole(MessageRole.USER).setParts(java.util.List.of(MessagePart.text(userMessage)))));
            if (!answer.isEmpty()) result.setOutput(java.util.List.of(
              new Message().setRole(MessageRole.ASSISTANT).setParts(java.util.List.of(MessagePart.text(answer.toString())))));
            ChatResponse response = usageResponse.get();
            if (response != null) {
              var usage = response.getMetadata().getUsage();
              result.setUsage(new TokenUsage().setInputTokens(usage.getPromptTokens())
                .setOutputTokens(usage.getCompletionTokens()).setTotalTokens(usage.getTotalTokens()));
            }
            recorder.setResult(result);
            if (first.get() != null) recorder.setFirstTokenAt(first.get());
            if (failure.get() != null) recorder.setCallError(failure.get());
            if (signal == SignalType.CANCEL) recorder.setCallError(new CancellationException("stream cancelled"));
          }
        } catch (RuntimeException ignored) {
          // Never include the provider exception text, prompt, or credentials in logs.
          LoggerFactory.getLogger(ChatTelemetry.class).warn("Generation telemetry failed: {}", ignored.getClass().getSimpleName());
        }
      });
    });
  }
}
