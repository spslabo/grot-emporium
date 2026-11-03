package com.amazon.sample.orders.services;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.sql.DriverManager;
import java.util.UUID;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.Test;

class OrderItemMigrationTests {
  @Test
  void migratesExistingPositionsWithoutClaimingToRestoreLostProductIds() throws Exception {
    String url = "jdbc:h2:mem:" + UUID.randomUUID() + ";DB_CLOSE_DELAY=-1";
    Flyway.configure().dataSource(url, "sa", "").target("1").load().migrate();
    try (var connection = DriverManager.getConnection(url, "sa", "");
         var statement = connection.createStatement()) {
      statement.execute("INSERT INTO orders(id) VALUES ('legacy')");
      for (int index = 0; index < 12; index++) {
        statement.execute("INSERT INTO order_items(product_id, quantity, unit_cost, total_cost, order_id) VALUES ('" + index + "', 1, 15, 15, 'legacy')");
      }
      Flyway.configure().dataSource(url, "sa", "").load().migrate();
      try (var rows = statement.executeQuery("SELECT product_id, item_position FROM order_items ORDER BY item_position")) {
        int index = 0;
        while (rows.next()) {
          assertEquals(String.valueOf(index), rows.getString(1));
          assertEquals(index++, rows.getInt(2));
        }
        assertEquals(12, index);
      }
    }
  }
}
