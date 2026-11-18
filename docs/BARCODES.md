# Barcode management

SmartMart keeps one unique `Product.barcode` value. Existing manufacturer codes stay unchanged when a product is edited;
new local products receive an internal `SM…` identifier, rendered as Code 128. No barcode table or duplicate field is used.

## Staff workflow

- Open **Products → Barcode management** at `/dashboard/products/barcodes/` to search by name, SKU, or barcode, inspect its
  source, preview Code 128, copy its value, or download SVG/PNG.
- Owners can generate internal values for legacy products whose barcode is blank. This action skips all registered values.
- Select products and enter a label count for each one, then choose **Preview and print A4 sheet**. Set page scale to 100%
  (no “fit to page”) in the print dialog. The sheet defaults to 50 × 30 mm labels and 5 mm margins; label dimensions,
  margins, gaps, SKU, and price are configurable.
- Product details also retain the one-product print flow.
- **Inventory → Barcode lookup** at `/dashboard/inventory/barcode-lookup/` resolves a barcode to product, SKU, base unit, and
  current stock. Staff can view details. Owners see the existing stock adjustment workflow; adjustments continue through
  `adjust_stock()` and `change_stock()` and keep their stock-movement ledger.

## POS scanning

USB HID scanners act like keyboards: focus the **Scan product barcode** field, scan, and let the scanner submit its usual
Enter key. The existing POS lookup adds the exact product; repeat scans increase quantity using the base unit and current
unit prices. Checkout still uses the existing idempotency key, sale service, and inventory stock deduction.

Camera scanning is bundled locally with `@zxing/browser`. Run `npm install && npm run build:js` during development (the
Railway build does this automatically). Select a camera when more than one is available. Camera access requires HTTPS or
localhost and browser permission. A code is accepted once until it leaves the camera frame; USB scanning remains available.

The browser's IndexedDB has a `barcodeProducts` cache. Product searches and storefront catalog visits update this with the
last visible barcode, stock, and price. If the POS or inventory lookup page is already open and the network drops, it can
identify a matching cached product and marks that information as a stale snapshot. Product availability, stock, and price
must be checked online before completing a sale. The service worker deliberately does not cache private dashboard pages,
and the existing offline order queue is for customer COD orders, not POS sales; offline barcode lookup never creates a
pending sale or changes stock.

## Printer output

The A4 print preview uses browser printing and CSS millimetre dimensions. Use the correct physical sticker stock, set scale
to 100%, and test a page before a full run; browser/printer margins and label die-cuts vary.

Thermal export downloads a raw `.tspl` or `.zpl` command file and includes the chosen label size and product copies. TSPL is
used by TSC printers and compatible devices; ZPL II is used by Zebra printers and compatible devices. [TSC's TSPL/TSPL2
manual](https://fs.tscprinters.com/system/files/31-0000001-00_tspl_tspl2_programming_g.pdf) documents label `SIZE`, Code 128
`BARCODE`, and `PRINT` commands. [Zebra's ZPL II `^BC` reference](https://docs.zebra.com/us/en/printers/software/zpl-pg/c-zpl-zpl-commands/r-zpl-bc.html)
documents Code 128 fields. The ZPL job assumes 203 dpi for dot dimensions; verify the printer's actual resolution and
calibrate label gap/media sensing. Select the matching printer language, stock dimensions, gap, and driver/spool workflow.

The export is not sent to a printer and direct printing is not implemented. Send raw files only through a printer/driver
workflow known to support that language. If the printer does not accept TSPL or ZPL II, use A4 browser printing or configure
the manufacturer's conversion/driver tool. Thermal command output currently rejects barcode values that are not printable
ASCII, and TSPL rejects values containing a double quote; SVG/PNG and browser printing remain available for those values.

## Routes

- `/dashboard/products/barcodes/` — staff management, bulk A4 preview and thermal export; only owners can generate missing IDs.
- `/dashboard/products/barcode-image/<product-id>.svg` and `.png` — authenticated downloadable Code 128 image.
- `/dashboard/inventory/barcode-lookup/` — staff barcode lookup UI.
- `/dashboard/inventory/barcode-lookup/search/?barcode=<value>` — staff-authenticated JSON lookup, exact match only; owner
  results include an `adjust_url` for the existing adjustment workflow.
- `/dashboard/sales/pos/search/?q=<barcode>&scan=1` — existing POS exact-match search, including stock and enabled sale units.

No database migration is required.
