package com.amazon.sample.orders.services;

import static org.junit.jupiter.api.Assertions.assertSame;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.amazon.sample.orders.entities.OrderEntity;
import com.amazon.sample.orders.entities.OrderItemEntity;
import com.amazon.sample.orders.repositories.OrderRepository;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class OrderServiceProductIdTests {
  @Mock OrderRepository repository;
  @InjectMocks OrderService service;

  @Test void acceptsUuidProductIdentifiersWithoutNumericCoercion() {
    OrderEntity order = new OrderEntity().addItem(
      new OrderItemEntity("cc789f85-1476-452a-8100-9e74502198e0", 1, 1299, 1299));
    when(repository.save(order)).thenReturn(order);
    assertSame(order, service.create(order));
    verify(repository).save(order);
  }
}
