# Inventory valuation method: weighted average cost

- Each product stores one `cost_price`: the weighted-average unit cost of the units on hand.
- When a purchase is **received**: `new_cost = (old_qty × old_cost + received_qty × unit_cost) ÷ (old_qty + received_qty)`, rounded to 2 decimals (half-up).
- Sales and online orders (Phases 3 and 5) copy the product's current `cost_price` onto each sale line, so
  cost of goods sold (COGS) never changes when later purchases change the average.
- Stock value = Σ(stock_quantity × cost_price). Gross profit = revenue − COGS. Net profit = gross profit − recorded expenses.
- Stock adjustments and returns change quantity only; they do not alter the average cost.
- Rounding note: because the average is rounded to 2 decimals, stock value can differ from true purchase spend by a few paisa.
