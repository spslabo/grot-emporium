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

package com.amazon.sample.orders.metrics;

import static org.assertj.core.api.BDDAssertions.then;

import com.amazon.sample.events.orders.Order;
import com.amazon.sample.events.orders.OrderCreatedEvent;
import com.amazon.sample.orders.entities.OrderItemEntity;
import io.micrometer.core.instrument.*;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import java.util.ArrayList;
import java.util.List;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

public class OrdersMetricsTests {

  private MeterRegistry meterRegistry;
  private final String PRODUCT_1 = "Product1";
  private final String PRODUCT_2 = "Product2";

  @BeforeEach
  void setUp() {
    meterRegistry = new SimpleMeterRegistry();
    Metrics.globalRegistry.add(meterRegistry);
  }

  @AfterEach
  void tearDown() {
    meterRegistry.clear();
    Metrics.globalRegistry.clear();
  }

  @Test
  void testCreateCounterAndIncrement() {
    OrdersMetrics ordersMetrics = new OrdersMetrics(meterRegistry);

    OrderCreatedEvent event = new OrderCreatedEvent();
    Order order = new Order();
    order.setId("id");

    List<OrderItemEntity> orderItems = new ArrayList<>();
    orderItems.add(new OrderItemEntity(PRODUCT_1, 5, 100, 500));
    orderItems.add(new OrderItemEntity(PRODUCT_2, 2, 50, 100));

    order.setOrderItems(orderItems);
    event.setOrder(order);
    ordersMetrics.onOrderCreated(event);

    then(meterRegistry.get("grot.orders.created").counter().count()).isEqualTo(1);
    then(meterRegistry.get("grot.orders.items").counter().count()).isEqualTo(7);
    then(meterRegistry.get("grot.orders.value").counter().count()).isEqualTo(600);
    ordersMetrics.onOrderCreated(event);
    then(meterRegistry.get("grot.orders.value").counter().count()).isEqualTo(1200);
    // Cardinality must remain constant even when product identifiers change.
    for (int i = 0; i < 100; i++) {
      order.setOrderItems(List.of(new OrderItemEntity("arbitrary-" + i, 1, 10, 10)));
      ordersMetrics.onOrderCreated(event);
    }
    then(meterRegistry.getMeters()).hasSize(3);
    then(meterRegistry.getMeters()).allSatisfy(meter -> then(meter.getId().getTags()).isEmpty());
  }
}
