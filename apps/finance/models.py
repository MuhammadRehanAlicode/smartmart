from datetime import date
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class Expense(models.Model):
    class Category(models.TextChoices):
        RENT = "rent", "Rent"
        UTILITIES = "utilities", "Electricity / utilities"
        SALARIES = "salaries", "Salaries"
        TRANSPORT = "transport", "Transport / delivery"
        MAINTENANCE = "maintenance", "Repairs / maintenance"
        OTHER = "other", "Other"

    date = models.DateField(default=date.today, db_index=True)
    category = models.CharField(max_length=16, choices=Category.choices, default=Category.OTHER)
    description = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]
