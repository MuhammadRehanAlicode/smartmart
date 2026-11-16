from django.db import migrations, models
import django.core.validators
import apps.store.models


def seed_existing_banners(apps, schema_editor):
    HeroBanner = apps.get_model("store", "HeroBanner")
    existing = [
        ("catalog/products/W&B General Store_ Shop Local, Live Better.png", "W&B General Store: shop local and live better"),
        ("catalog/products/W&B General Store_ Shop Smart, Live Better.png", "W&B General Store: shop smart and live better"),
        ("catalog/products/W&B General Store Promotional Banner (1).png", "W&B General Store: everything you need under one roof"),
        ("catalog/products/W&B General Store Promotional Banner.png", "W&B General Store: quality products and friendly service"),
    ]
    for order, (image, alt_text) in enumerate(existing):
        HeroBanner.objects.get_or_create(image=image, defaults={"alt_text": alt_text, "sort_order": order})


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="HeroBanner",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("image", models.ImageField(upload_to="hero_banners/", validators=[
                    django.core.validators.FileExtensionValidator(["jpg", "jpeg", "png", "webp"]),
                    apps.store.models.validate_banner_size,
                ])),
                ("alt_text", models.CharField(blank=True, default="W&B General Store banner", max_length=200)),
                ("sort_order", models.PositiveIntegerField(default=0)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["sort_order", "id"]},
        ),
        migrations.RunPython(seed_existing_banners, migrations.RunPython.noop),
    ]
