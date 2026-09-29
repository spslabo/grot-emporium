package com.amazon.sample.carts.services;

import static org.junit.jupiter.api.Assertions.*;
import org.junit.jupiter.api.Test;

class InMemoryCartServiceTests {
  @Test
  void repeatedProductAddsIncreaseQuantityInsteadOfCreatingDuplicateRows() {
    var service = new InMemoryCartService();
    service.add("cart-a", "original-grot", 1, 20);
    service.add("cart-a", "cloud-grot", 1, 30);
    service.add("cart-a", "original-grot", 2, 20);
    assertEquals(2, service.items("cart-a").size());
    assertEquals(3, service.item("cart-a", "original-grot").orElseThrow().getQuantity());
  }

  @Test
  void deletingOneProductPreservesOtherProductsAndOtherCarts() {
    var service = new InMemoryCartService();
    service.add("cart-a", "original-grot", 1, 20);
    service.add("cart-a", "original-grot", 1, 20);
    service.add("cart-a", "cloud-grot", 2, 30);
    service.add("cart-b", "original-grot", 1, 20);
    service.deleteItem("cart-a", "original-grot");
    assertEquals(1, service.items("cart-a").size());
    assertEquals("cloud-grot", service.items("cart-a").get(0).getItemId());
    assertEquals(2, service.items("cart-a").get(0).getQuantity());
    assertEquals(1, service.items("cart-b").size());
    service.deleteItem("cart-a", "unknown-product");
    assertEquals(1, service.items("cart-a").size());
  }
}
