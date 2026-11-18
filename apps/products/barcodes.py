"""Barcode rendering and printer-language exports used by dashboard labels."""
from barcode import get as get_barcode
from barcode.errors import BarcodeError
from barcode.writer import ImageWriter, SVGWriter


def render_barcode(value, image_format="svg"):
    """Return a scannable Code 128 image as bytes without altering the stored value."""
    if not value:
        raise ValueError("This product does not have a barcode.")
    if image_format == "png":
        image = get_barcode("code128", value, writer=ImageWriter()).render(
            {"module_width": 0.28, "module_height": 14, "quiet_zone": 2, "write_text": False}
        )
        from io import BytesIO
        output = BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()
    if image_format == "svg":
        return get_barcode("code128", value, writer=SVGWriter()).render(
            {"module_width": 0.28, "module_height": 14, "quiet_zone": 2, "write_text": False}
        )
    raise ValueError("Choose SVG or PNG.")


def _thermal_value(value, printer):
    # Printer command languages have control characters which can change the job.
    if not value or any(ord(char) < 32 or ord(char) > 126 for char in value):
        raise ValueError("Thermal output supports printable ASCII barcode values only.")
    if printer == "zpl":
        return "".join(f"_{ord(char):02X}" if char in "^~_\\" else char for char in value)
    if '"' in value:
        raise ValueError('TSPL output cannot safely encode a barcode containing a double quote.')
    return value


def thermal_job(labels, *, printer, width_mm, height_mm):
    """Build a downloadable TSPL or ZPL job; it is not sent directly to a printer."""
    if printer not in {"tspl", "zpl"}:
        raise ValueError("Choose TSPL or ZPL.")
    if not (20 <= width_mm <= 104 and 10 <= height_mm <= 150):
        raise ValueError("Label size is outside the supported range.")

    lines = []
    if printer == "tspl":
        lines.extend([f"SIZE {width_mm:g} mm,{height_mm:g} mm", "GAP 2 mm,0", "CLS"])
    else:
        # 203 dpi is the common desktop-printer default; verify/set DPI on the target printer.
        lines.extend(["^XA", f"^PW{round(width_mm * 8)}", f"^LL{round(height_mm * 8)}"])
    for index, item in enumerate(labels):
        value = _thermal_value(item["barcode"], printer)
        name = "".join(char for char in item["name"] if 32 <= ord(char) <= 126)[:32]
        if printer == "tspl":
            lines.extend(["CLS", f'TEXT 20,12,"0",0,1,1,"{name.replace(chr(34), "")}"',
                          f'BARCODE 20,42,"128",80,1,0,2,2,"{value}"',
                          f'TEXT 20,135,"0",0,1,1,"{value}"', "PRINT 1,1"])
        else:
            escaped_name = _thermal_value(name, "zpl")
            lines.extend([f"^FO16,16^A0N,24,24^FH_^FD{escaped_name}^FS",
                          "^FO16,48^BY2", "^BCN,80,Y,N,N", f"^FH_^FD{value}^FS",
                          f"^FO16,145^A0N,20,20^FH_^FD{value}^FS"])
            if index + 1 < len(labels):
                lines.append("^XZ\n^XA")
    if printer == "zpl":
        lines.append("^PQ1,0,1,N^XZ")
    return ("\n".join(lines) + "\n").encode("ascii")


def valid_code128_value(value):
    """Whether the installed Code 128 renderer can encode this product value."""
    try:
        render_barcode(value, "svg")
        return True
    except (BarcodeError, ValueError, UnicodeError, TypeError):
        return False
