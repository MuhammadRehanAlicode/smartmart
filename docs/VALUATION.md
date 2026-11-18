# Inventory valuation method: latest received purchase cost

- Each product stores `cost_price` as the unit cost per base unit from its latest received purchase.
- A pending or cancelled purchase does not change stock or product prices. Receiving a purchase updates stock, cost, and selling price together.
- A carton purchase cost is converted to a base-unit cost using its configured conversion factor. The purchase line keeps its original cost and quantity for history.
- POS and delivered online order lines copy the product's current cost at the time of sale, so later receipts do not rewrite historical COGS.
- Current stock value is `stock_quantity × cost_price`; it reflects the latest purchase cost, not a weighted average of remaining batches.
- Stock adjustments and returns change quantity only; they do not change product cost or selling price.
