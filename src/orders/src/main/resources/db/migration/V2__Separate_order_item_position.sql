-- V1's List mapping wrote the zero-based list index into product_id.
-- Preserve that position separately. Original product UUIDs already overwritten
-- by V1 cannot be reconstructed; do not pretend this migration repairs them.
-- Non-numeric legacy IDs indicate data outside that mapping and require review
-- rather than silently inventing a historical list order.
ALTER TABLE order_items ADD COLUMN item_position INTEGER;
UPDATE order_items SET item_position = CAST(product_id AS INTEGER);
ALTER TABLE order_items ALTER COLUMN item_position SET NOT NULL;
CREATE UNIQUE INDEX order_items_position ON order_items(order_id, item_position);
