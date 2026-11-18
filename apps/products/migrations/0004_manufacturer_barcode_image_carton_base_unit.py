from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("products", "0003_product_base_unit_alter_product_low_stock_threshold_and_more")]

    operations = [
        migrations.AddField(model_name="product", name="manufacturer", field=models.CharField(blank=True, max_length=160)),
        migrations.AddField(model_name="product", name="barcode_image", field=models.ImageField(blank=True, upload_to="product_barcodes/")),
        migrations.AlterField(model_name="product", name="base_unit", field=models.CharField(choices=[("PCS", "Piece (PCS)"), ("CTN", "Carton (CTN)"), ("KG", "Kilogram (KG)")], default="PCS", max_length=3)),
    ]
