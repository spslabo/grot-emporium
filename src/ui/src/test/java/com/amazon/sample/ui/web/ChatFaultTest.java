package com.amazon.sample.ui.web;

import com.amazon.sample.ui.chat.ChatTelemetry;
import org.junit.jupiter.api.Test;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.beans.factory.support.DefaultListableBeanFactory;
import com.grafana.agento11y.sdk.Agento11yClient;
import org.springframework.test.util.ReflectionTestUtils;
import static org.junit.jupiter.api.Assertions.*;
import reactor.core.publisher.Flux;
import java.util.List;
import static org.mockito.Mockito.*;

class ChatFaultTest {
  private void request(boolean enabled, String header, boolean expectedError) throws Exception {
    ChatController controller = new ChatController();
    ChatClient model = mock(ChatClient.class, RETURNS_DEEP_STUBS);
    when(model.prompt("test").system("test").stream().chatResponse()).thenReturn(Flux.just(
      new ChatResponse(List.of(new org.springframework.ai.chat.model.Generation(new AssistantMessage("hello"))))));
    clearInvocations(model);
    ReflectionTestUtils.setField(controller, "client", model);
    ReflectionTestUtils.setField(controller, "systemPrompt", "test");
    ReflectionTestUtils.setField(controller, "syntheticFaultsEnabled", enabled);
    ReflectionTestUtils.setField(controller, "telemetry", new ChatTelemetry(new DefaultListableBeanFactory().getBeanProvider(Agento11yClient.class), "bedrock", "test", "test"));
    var requestType = Class.forName(ChatController.class.getName() + "$ChatRequest");
    var constructor = requestType.getDeclaredConstructor();
    constructor.setAccessible(true);
    Object request = constructor.newInstance();
    ReflectionTestUtils.setField(request, "message", "test");
    Flux<?> result = (Flux<?>) ChatController.class.getDeclaredMethod("streamEvents", requestType, String.class).invoke(controller, request, header);
    if (expectedError) {
      var error = assertThrows(org.springframework.web.server.ResponseStatusException.class, result::blockLast);
      assertEquals(503, error.getStatusCode().value()); verifyNoInteractions(model);
    } else { assertNotNull(result.blockLast()); verify(model).prompt("test"); }
  }
  @Test void onlyExplicitlyEnabledFlaggedRequestsFail() throws Exception { request(true, "error", true); }
  @Test void ordinaryChatsAreUnaffected() throws Exception { request(true, "", false); }
  @Test void faultHeaderIsInertByDefault() throws Exception { request(false, "error", false); }
}
