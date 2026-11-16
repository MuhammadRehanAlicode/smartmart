from decimal import Decimal

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("purchases", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="purchaseitem",
            name="box_cost",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                default=Decimal("0.00"),
                max_digits=12,
                validators=[django.core.validators.MinValueValidator(Decimal("0"))],
            ),
        ),
    ]
