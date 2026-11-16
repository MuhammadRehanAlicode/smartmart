from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models


def validate_banner_size(image):
    if image.size > 10 * 1024 * 1024:
        raise ValidationError("Banner image must be 10 MB or smaller.")


class HeroBanner(models.Model):
    image = models.ImageField(
        upload_to="hero_banners/",
        validators=[FileExtensionValidator(["jpg", "jpeg", "png", "webp"]), validate_banner_size],
    )
    alt_text = models.CharField(max_length=200, blank=True, default="W&B General Store banner")
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self):
        return self.alt_text or f"Hero banner {self.pk}"
