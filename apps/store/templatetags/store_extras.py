"""Template helpers for product and category artwork."""
from urllib.parse import urljoin

from django import template
from django.conf import settings
from django.templatetags.static import static

register = template.Library()

PRODUCT_ART = (("banana", "banana"), (("cola", "coke", "pepsi", "soda", "sprite", "fanta"), "cola"), ("milk", "milk"),
               (("bread", "bun", "toast"), "bread"), (("chip", "lay"), "chips"), ("tomato", "tomato"),
               (("apple",), "apples"), (("orange",), "oranges"),
               (("shirt", "clothing", "apparel", "scarf", "socks"), "cat-clothing"),
               (("watch", "timepiece"), "cat-watch"))
CATEGORY_ART = (
    (("fruit", "veg"), "category-fruits-vegetables.jpg"),
    (("beverage", "drink", "juice", "water"), "category-beverages.jpg"),
    (("dairy", "milk", "egg"), "category-dairy-eggs.jpg"),
    (("snack", "biscuit", "chocolate", "sweet"), "category-snacks.jpg"),
    (("personal", "beauty", "care"), "category-personal-care.jpg"),
    (("household", "clean", "home", "detergent"), "category-household.jpg"),
    (("baby",), "cat-baby"), (("bakery", "bread"), "category-bakery.jpg"),
    (("meat", "seafood", "fish", "chicken"), "cat-meat"),
    (("organic", "healthy"), "category-organic-healthy.jpg"),
    (("grain", "rice", "flour", "atta"), "cat-grains"),
    (("pantry", "oil", "spice", "cooking"), "cat-pantry"),
    (("clothing", "apparel", "fashion"), "cat-clothing"),
    (("watch", "timepiece"), "cat-watch"),
)
FEATURED_PRODUCT_ART = {
    "bread": "featured-bread.jpg",
    "coca cola": "featured-coca-cola.jpg",
    "fresh bananas": "featured-bananas.jpg",
    "oranges": "featured-oranges.jpg",
    "tomatoes": "featured-tomatoes.jpg",
    "lay's chips": "img/store/category-snacks.jpg",
}
PRODUCT_PHOTO_ART = {
    "baby diapers pack": "baby-diapers.webp",
    "baby wipes pack": "baby-wipes.webp",
    "breakfast cereal 375g": "breakfast-cereal.webp",
    "baking powder 100g": "baking-powder.webp",
    "basmati rice 1kg": "organic-rice.webp",
    "basmati rice 5kg": "organic-rice.webp",
    "black pepper 100g": "black-pepper.webp",
    "black tea 450g": "black-tea.webp",
    "bread": "bread.webp",
    "brown bread": "brown-bread.webp",
    "butter croissants": "croissants.webp",
    "carrots": "vegetables.webp",
    "cheddar cheese": "cheddar-cheese.webp",
    "chana dal 1kg": "chana-dal.webp",
    "chia seeds": "chia-seeds.webp",
    "chickpeas 1kg": "chickpeas.webp",
    "chocolate bar": "chocolate.webp",
    "chocolate cookies": "cookies-cream.webp",
    "coca cola": "coca-cola.webp",
    "colgate toothpaste": "toothpaste.webp",
    "corn flour 300g": "corn-flour.webp",
    "cooking oil 1l": "cooking-oil.webp",
    "cucumbers": "cucumbers.webp",
    "custard powder 300g": "custard-powder.webp",
    "desi ghee 1kg": "desi-ghee.webp",
    "dishwashing liquid": "dishwashing-liquid.webp",
    "dove beauty bar": "dove-soap.webp",
    "facial tissue box": "facial-tissue.webp",
    "family body lotion": "body-lotion.webp",
    "farm fresh eggs": "eggs.webp",
    "fresh bananas": "bananas.webp",
    "fresh cream": "fresh-cream.webp",
    "garlic": "vegetables.webp",
    "fresh ginger": "vegetables.webp",
    "green apples": "fruit-platter.webp",
    "green chilies": "vegetables.webp",
    "green tea": "green-tea.webp",
    "ground coffee": "coffee.webp",
    "hand wash": "hand-soap.webp",
    "herbal shampoo": "shampoo.webp",
    "instant noodles pack": "instant-noodles.webp",
    "iodized salt 800g": "iodized-salt.webp",
    "kitchen sponge pack": "sponge.webp",
    "kidney beans 1kg": "kidney-beans.webp",
    "laundry detergent": "detergent.webp",
    "laundry soap bar": "sunlight-soap.webp",
    "lay's chips": "chips.webp",
    "lifebuoy soap": "lifebuoy-soap.webp",
    "mango juice": "juice-pack.webp",
    "mangoes": "fruit-platter.webp",
    "macaroni 400g": "macaroni.webp",
    "mayonnaise 500g": "mayonnaise.webp",
    "milk": "milk-carton.webp",
    "milk powder 500g": "milk-powder.webp",
    "moong dal 1kg": "moong-dal.webp",
    "mineral water": "mineral-water.webp",
    "mixed nuts": "mixed-nuts.webp",
    "mixed spice pack": "spices.webp",
    "mint toothpaste": "toothpaste.webp",
    "orange juice": "orange-juice.webp",
    "oranges": "orange.webp",
    "paper towels": "paper-towels.webp",
    "pasta 400g": "pasta.webp",
    "potatoes": "vegetables.webp",
    "red apples": "fruit-platter.webp",
    "red lentils 1kg": "lentils.webp",
    "red onions": "vegetables.webp",
    "rolled oats": "oats.webp",
    "salted biscuits": "biscuits.webp",
    "seedless grapes": "fruit-platter.webp",
    "spinach": "vegetables.webp",
    "sprite": "sprite.webp",
    "strawberries": "fruit-platter.webp",
    "tomato ketchup": "ketchup.webp",
    "tomato paste 400g": "tomato-sauce.webp",
    "haldi": "turmeric.webp",
    "tomatoes": "tomatoes.webp",
    "turmeric powder 100g": "turmeric.webp",
    "vermicelli 200g": "vermicelli.webp",
    "watermelon": "fruit-platter.webp",
    "white vinegar 500ml": "white-vinegar.webp",
    "wheat flour 5kg": "wheat-flour.webp",
    "white sugar 1kg": "sugar.webp",
    "whole wheat rusk": "rusks.webp",
    "cakes": "croissants.webp",
}
BEST_SELLER_PRODUCT_ART = {
    "bread": "featured-bread.jpg",
    "coca cola": "featured-coca-cola.jpg",
    "fresh bananas": "featured-bananas.jpg",
    "lay's chips": "img/store/category-snacks.jpg",
    "milk": "milk-carton.webp",
}


def _match(text, table):
    text = (text or "").lower()
    for words, art in table:
        words = (words,) if isinstance(words, str) else words
        if any(w in text for w in words):
            return art
    return None


@register.filter
def category_art(category):
    name = getattr(category, "name", category)
    art = _match(name, CATEGORY_ART) or "cat-generic"
    return f"img/store/{art if art.endswith('.jpg') else art + '.svg'}"


def _media_product_art(filename):
    return urljoin(settings.MEDIA_URL, f"catalog/products/{filename}")


@register.filter
def product_art(product):
    photo = PRODUCT_PHOTO_ART.get((product.name or "").strip().lower())
    if photo:
        return f"catalog/products/{photo}"
    art = _match(product.name, PRODUCT_ART)
    if art is None and product.category_id:
        return category_art(product.category)
    return f"img/store/{art or 'generic'}.svg"


@register.filter
def product_art_url(product):
    art = product_art(product)
    if art.startswith("catalog/products/"):
        return urljoin(settings.MEDIA_URL, art)
    return static(art)


@register.filter
def featured_product_art(product):
    name = (getattr(product, "name", "") or "").strip().lower()
    photo = PRODUCT_PHOTO_ART.get(name)
    if photo:
        return _media_product_art(photo)
    photo = FEATURED_PRODUCT_ART.get(name)
    if not photo:
        return ""
    return static(photo) if photo.startswith("img/") else _media_product_art(photo)


@register.filter
def best_seller_product_art(product):
    name = (getattr(product, "name", "") or "").strip().lower()
    photo = PRODUCT_PHOTO_ART.get(name)
    if photo:
        return _media_product_art(photo)
    photo = BEST_SELLER_PRODUCT_ART.get(name)
    if not photo:
        return ""
    return static(photo) if photo.startswith("img/") else _media_product_art(photo)


@register.simple_tag
def nav_categories():
    from apps.products.models import Category
    return list(Category.objects.filter(is_active=True)[:14])
