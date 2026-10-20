/*
 * Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
 * SPDX-License-Identifier: MIT-0
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy of this
 * software and associated documentation files (the "Software"), to deal in the Software
 * without restriction, including without limitation the rights to use, copy, modify,
 * merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
 * permit persons to whom the Software is furnished to do so.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
 * INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
 * PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
 * HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
 * OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
 * SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
 */

package com.amazon.sample.ui.web;

import com.amazon.sample.ui.chat.ChatTelemetry;
import java.util.UUID;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import reactor.core.publisher.Flux;

@RestController
@RequestMapping("/chat")
@ConditionalOnProperty(prefix = "retail.ui.chat", name = "enabled")
public class ChatController {

  private static class ChatRequest {

    @JsonProperty("message")
    @NotBlank
    @Size(max = 2000)
    private String message;

    @JsonProperty("conversationId")
    private String conversationId;

    public String safeConversationId() {
      try { return UUID.fromString(conversationId).toString(); }
      catch (RuntimeException ignored) { return UUID.randomUUID().toString(); }
    }

    public String getMessage() {
      return message;
    }

    @SuppressWarnings("unused")
    public void setMessage(String message) {
      this.message = message;
    }
  }

  private static class ResponseMessage {

    @JsonProperty("text")
    private String text;

    ResponseMessage(String text) {
      this.text = text;
    }

    @SuppressWarnings("unused")
    public String getText() {
      return text;
    }
  }

  @Value("${retail.ui.chat.prompt}")
  private String systemPrompt;

  @Value("${GROT_CHAT_SYNTHETIC_FAULTS_ENABLED:false}")
  private boolean syntheticFaultsEnabled;

  @Autowired
  private ChatClient client;

  @Autowired
  private ChatTelemetry telemetry;

  @PostMapping("/submit")
  public Flux<ServerSentEvent<String>> streamEvents(
    @Valid @RequestBody ChatRequest request,
    @org.springframework.web.bind.annotation.RequestHeader(value = "X-Grot-Synthetic-Fault", defaultValue = "") String fault
  ) {
    var objectMapper = new ObjectMapper();

    if (syntheticFaultsEnabled && "error".equals(fault)) {
      return telemetry.observe(Flux.<org.springframework.ai.chat.model.ChatResponse>error(
        new org.springframework.web.server.ResponseStatusException(org.springframework.http.HttpStatus.SERVICE_UNAVAILABLE,
          "Injected synthetic chat failure (not a Bedrock outage)")), request.safeConversationId(), true, systemPrompt, request.getMessage())
        .map(ignored -> ServerSentEvent.<String>builder().data("").build());
    }

    return telemetry.observe(this.client.prompt(request.getMessage())
      .system(this.systemPrompt)
      .stream()
      .chatResponse(), request.safeConversationId(), false, systemPrompt, request.getMessage())
      .filter(c -> c.getResult() != null && c.getResult().getOutput() != null && c.getResult().getOutput().getText() != null)
      .map(c -> {
        try {
          var response = new ResponseMessage(c.getResult().getOutput().getText());
          return ServerSentEvent.<String>builder()
            .data(objectMapper.writeValueAsString(response))
            .build();
        } catch (JsonProcessingException e) {
          throw new RuntimeException("Failed to serialize chat response", e);
        }
      });
  }
}
