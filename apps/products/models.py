from decimal import ROUND_HALF_UP, Decimal
import secrets

from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.text import slugify

MONEY = {"max_digits": 12, "decimal_places": 2}


def validate_image_size(f):
    if f.size > 2 * 1024 * 1024:
        raise ValidationError("Image must be 2 MB or smaller.")


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=110, unique=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or "category"
            slug, n = base, 2
            while Category.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug, n = f"{base}-{n}", n + 1
            self.slug = slug
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Product(models.Model):
    class Unit(models.TextChoices):
        PCS = "PCS", "Piece (PCS)"
        CTN = "CTN", "Carton (CTN)"
        KG = "KG", "Kilogram (KG)"

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.SET_NULL, related_name="products")
    sku = models.CharField("SKU", max_length=50, unique=True)
    barcode = models.CharField(max_length=64, unique=True, null=True, blank=True)
    has_manufacturer_barcode = models.BooleanField(default=False)
    product_code = models.CharField(max_length=32, unique=True, blank=True, default="")
    base_unit = models.CharField(max_length=3, choices=(("PCS", "Piece (PCS)"), ("KG", "Kilogram (KG)")), default="PCS")
    image = models.ImageField(
        upload_to="products/", blank=True,
        validators=[FileExtensionValidator(["jpg", "jpeg", "png", "webp"]), validate_image_size],
    )
    # cost_price is the weighted-average cost (see docs/VALUATION.md).
    cost_price = models.DecimalField(**MONEY, default=Decimal("0.00"), validators=[MinValueValidator(Decimal("0"))])
    selling_price = models.DecimalField(**MONEY, validators=[MinValueValidator(Decimal("0.01"))])
    discount_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
    )
    # Never edited directly: changed only through inventory.services.change_stock.
    stock_quantity = models.DecimalField(max_digits=14, decimal_places=6, default=Decimal("0.000000"), editable=False)
    low_stock_threshold = models.DecimalField(max_digits=14, decimal_places=6, default=Decimal("5.000000"))
    is_online = models.BooleanField("Available online", default=True)
    is_archived = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def save(self, *args, **kwargs):
        self.barcode = (self.barcode or "").strip() or None
        creating = self._state.adding
        if creating and self.barcode:
            self.has_manufacturer_barcode = True
        if creating and not self.barcode:
            self.has_manufacturer_barcode = False
            super().save(*args, **kwargs)
            self.product_code = f"LOCAL-{self.pk:06d}"
            while True:
                candidate = "SM" + secrets.token_hex(6).upper()
                if not Product.objects.filter(barcode=candidate).exists():
                    self.barcode = candidate
                    break
            super().save(update_fields=["product_code", "barcode", "has_manufacturer_barcode", "updated_at"])
            return
        if not creating and not self.has_manufacturer_barcode and not self.barcode:
            while True:
                candidate = "SM" + secrets.token_hex(6).upper()
                if not Product.objects.filter(barcode=candidate).exclude(pk=self.pk).exists():
                    self.barcode = candidate
                    break
        if creating and not self.product_code:
            # A product's primary key gives it a stable, human-readable identifier.
            super().save(*args, **kwargs)
            self.product_code = f"LOCAL-{self.pk:06d}"
            super().save(update_fields=["product_code", "updated_at"])
            return
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.sku})"

    @property
    def discounted_price(self):
        factor = (Decimal("100") - self.discount_percent) / Decimal("100")
        return (self.selling_price * factor).quantize(Decimal("0.01"), ROUND_HALF_UP)

    @property
    def is_out_of_stock(self):
        return self.stock_quantity == 0

    @property
    def is_low_stock(self):
        return 0 < self.stock_quantity <= self.low_stock_threshold

    @property
    def stock_value(self):
        return self.cost_price * self.stock_quantity

    @property
    def base_unit_label(self):
        return self.get_base_unit_display()

    @property
    def equivalent_cartons(self):
        carton = self.unit_options.filter(unit_code=self.Unit.CTN, conversion_factor__gt=0).first()
        return self.stock_quantity / carton.conversion_factor if carton else None

    def price_for_unit(self, unit_code):
        option = self.unit_options.filter(unit_code=unit_code, sales_enabled=True).first()
        return option.selling_price if option else None


class ProductUnit(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="unit_options")
    unit_code = models.CharField(max_length=3, choices=Product.Unit.choices)
    conversion_factor = models.DecimalField(max_digits=12, decimal_places=6, validators=[MinValueValidator(Decimal("0.000001"))])
    purchase_enabled = models.BooleanField(default=False)
    sales_enabled = models.BooleanField(default=False)
    selling_price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(Decimal("0"))])

    class Meta:
        constraints = [models.UniqueConstraint(fields=("product", "unit_code"), name="unique_product_unit_code")]
        ordering = ["unit_code"]

    def __str__(self):
        return f"{self.product.name} — {self.get_unit_code_display()}"
