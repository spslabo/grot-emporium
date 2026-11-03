package com.amazon.sample.orders.services;

import static org.junit.jupiter.api.Assertions.assertEquals;

import com.amazon.sample.orders.entities.OrderEntity;
import com.amazon.sample.orders.entities.OrderItemEntity;
import com.amazon.sample.orders.entities.ShippingAddressEntity;
import com.amazon.sample.orders.repositories.OrderRepository;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.annotation.Transactional;

@SpringBootTest
@Transactional
class OrderItemPersistenceTests {
  @Autowired OrderRepository repository;
  @Autowired JdbcTemplate jdbc;

  @Test
  void preservesProductIdentityPriceAndListOrderOnDatabaseRoundTrip() {
    String first = "cc789f85-1476-452a-8100-9e74502198e0";
    String second = "87e89b11-d319-446d-b9be-50adcca5224a";
    OrderEntity order = new OrderEntity(
      List.of(new OrderItemEntity(first, 2, 15, 30), new OrderItemEntity(second, 1, 20, 20)),
      new ShippingAddressEntity("Demo", "Probe", "probe@example.test", "1 Example Street", "", "Demo", "90210", "CA")
    );
    String id = repository.save(order).getId();
    // Reload: repository.save's returned object does not prove persisted values.
    OrderEntity reloaded = repository.findById(id).orElseThrow();
    assertEquals(List.of(first, second), reloaded.getItems().stream().map(OrderItemEntity::getProductId).toList());
    assertEquals(List.of(15, 20), reloaded.getItems().stream().map(OrderItemEntity::getUnitCost).toList());
    assertEquals(List.of(2, 1), reloaded.getItems().stream().map(OrderItemEntity::getQuantity).toList());
    assertEquals(List.of(30, 20), reloaded.getItems().stream().map(OrderItemEntity::getTotalCost).toList());
    assertEquals(first, jdbc.queryForObject("SELECT product_id FROM order_items WHERE order_id = ? AND unit_cost = 15", String.class, id));
  }
}
