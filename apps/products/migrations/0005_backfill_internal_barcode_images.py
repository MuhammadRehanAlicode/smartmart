from io import BytesIO
import re
import uuid

from django.core.files.base import ContentFile
from django.db import migrations
from django.utils.text import slugify


INTERNAL = re.compile(r"SM[0-9A-F]{12}")


def populate_internal_images(apps, schema_editor):
    Product = apps.get_model("products", "Product")
    from barcode import get as get_barcode
    from barcode.writer import ImageWriter

    for product in Product.objects.all().iterator():
        value = (product.barcode or "").strip()
        if not value:
            value = f"SM{product.pk:012d}"
            while Product.objects.filter(barcode=value).exclude(pk=product.pk).exists():
                value = "SM" + uuid.uuid4().hex[:12].upper()
            product.barcode = value
            product.has_manufacturer_barcode = False
        elif INTERNAL.fullmatch(value):
            product.has_manufacturer_barcode = False
        if not product.has_manufacturer_barcode and not product.barcode_image:
            image = get_barcode("code128", value, writer=ImageWriter()).render(
                {"module_width": 0.28, "module_height": 14, "quiet_zone": 2, "write_text": False}
            )
            output = BytesIO()
            image.save(output, format="PNG")
            product.barcode_image.save(
                f"{slugify(product.sku) or product.pk}-barcode.png",
                ContentFile(output.getvalue()), save=False,
            )
        product.save(update_fields=["barcode", "has_manufacturer_barcode", "barcode_image"])


class Migration(migrations.Migration):
    dependencies = [("products", "0004_manufacturer_barcode_image_carton_base_unit")]
    operations = [migrations.RunPython(populate_internal_images, migrations.RunPython.noop)]
