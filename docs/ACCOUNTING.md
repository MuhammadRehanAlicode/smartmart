# Accounting rules (Phase 3)

Implemented in `apps/finance/calculations.py`; every figure is aggregated from database rows.

| Term | Definition |
|---|---|
| Revenue | Sum of sale totals (after product discounts) created in the date range |
| Refunds | Refunds from returns recorded in the range |
| Net revenue | Revenue − refunds |
| COGS | Cost snapshot of units sold in the range, minus cost of units returned **and restocked** in the range |
| Gross profit | Net revenue − COGS |
| Expenses | Recorded expenses dated in the range (rent, wages, etc.). Buying stock is **not** an expense |
| Net profit | Gross profit − expenses |
| Purchase spend | Value of purchases marked received in the range |
| Inventory value | Σ stock × weighted-average cost, right now |

- Cash basis: a return counts in the period it is recorded, not the period of the original sale.
- Returns without restock (damaged goods) refund the customer but keep the cost in COGS, i.e. the loss shows in profit.
- Each sale line stores price, discount, cost and product name at sale time, so later price edits never change history.
- Online orders: stock is reserved when the order is placed; revenue and COGS are recognised when the order is marked Delivered
  (cash on delivery is collected then). Delivery fees count as revenue; courier costs are recorded as expenses.
  Cancelled orders restock and never touch revenue.
