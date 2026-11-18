from decimal import Decimal
from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):
    dependencies = [("purchases", "0004_alter_purchaseitem_quantity")]
    def populate(apps, schema_editor):
        PurchaseItem = apps.get_model("purchases", "PurchaseItem")
        for item in PurchaseItem.objects.select_related("product").iterator():
            item.selling_price = item.product.selling_price
            item.save(update_fields=["selling_price"])

    operations = [
        migrations.AddField(model_name="purchaseitem", name="selling_price", field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
        migrations.RunPython(populate, migrations.RunPython.noop),
        migrations.AlterField(model_name="purchaseitem", name="selling_price", field=models.DecimalField(decimal_places=2, default=Decimal("0.01"), max_digits=12, validators=[django.core.validators.MinValueValidator(Decimal("0.01"))])),
    ]
