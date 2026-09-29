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

import com.amazon.sample.events.orders.OrderCreatedEvent;
import com.amazon.sample.orders.entities.OrderItemEntity;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import org.springframework.stereotype.Component;
import org.springframework.transaction.event.TransactionalEventListener;

@Component
public class OrdersMetrics {

  private final Counter orderCreatedCounter;
  private final Counter itemCounter;
  private final Counter orderValueCounter;

  public OrdersMetrics(MeterRegistry meterRegistry) {
    this.orderCreatedCounter = Counter.builder("grot.orders.created")
      .description("The number of orders placed")
      .register(meterRegistry);
    this.itemCounter = Counter.builder("grot.orders.items")
      .description("Total items ordered; no customer or product ID labels")
      .register(meterRegistry);
    this.orderValueCounter = Counter.builder("grot.orders.value")
      .description("Total order item value in application price units")
      .register(meterRegistry);
  }

  @TransactionalEventListener
  public void onOrderCreated(OrderCreatedEvent event) {
    this.orderCreatedCounter.increment();
    for (OrderItemEntity orderentity : event.getOrder().getOrderItems()) {
      itemCounter.increment(Math.max(0, orderentity.getQuantity()));
    }
    int totalPrice = event
      .getOrder()
      .getOrderItems()
      .stream()
      .map(x -> x.getTotalCost())
      .reduce(0, Integer::sum);
    this.orderValueCounter.increment(Math.max(0, totalPrice));
  }
}
