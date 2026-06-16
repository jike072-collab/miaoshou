"""Built-in strict-fidelity prompts for GPT image generation."""

COMMON = """Create a square 1:1 ecommerce image using the supplied product image as the only product reference.
Strictly preserve the exact product color, shape, material, construction, logo position, hardware and included accessories.
Do not redesign the product. Do not add text, watermarks, brands, certification marks, functions, parts or details not visible in the reference.
The product must be complete, sharp and physically plausible, without duplicated parts, deformation or anatomy errors.
Use natural commercial lighting and a clean premium cross-border ecommerce style."""

CATEGORY = {
    "shoes": "Preserve the exact upper, outsole, laces, stitching and shoe silhouette.",
    "bag": "Preserve the exact number and position of straps, zippers, pockets, buckles and accessories.",
    "sportswear": "Preserve the exact top-and-bottom set composition, fit, colors, prints, seams and fabric appearance.",
}

SCENES = {
    "main": "Place the product alone on a pure white or very light gray seamless background, centered with balanced margins.",
    "scene": "Show the product in a bright realistic Southeast Asian urban, gym or light outdoor setting. Use a natural, diverse Southeast Asian adult model when appropriate, without national stereotypes.",
    "detail": "Create a truthful close-up using only a real visible material, seam, outsole, zipper, pocket or fabric detail from the reference. Do not invent hidden construction.",
}

PRESETS = {
    "basic": ["main"],
    "standard": ["main", "scene", "scene"],
    "detail": ["main", "scene", "scene", "detail", "detail"],
}


def category_key(category):
    text = (category or "").lower()
    if "鞋" in text or "shoe" in text or "sneaker" in text:
        return "shoes"
    if "包" in text or "bag" in text or "backpack" in text:
        return "bag"
    return "sportswear"


def build_prompts(category, preset="standard", custom=None, extra=""):
    kinds = list(custom or PRESETS.get(preset, PRESETS["standard"]))[:6]
    key = category_key(category)
    return ["\n".join(part for part in (COMMON, CATEGORY[key], SCENES.get(kind, SCENES["scene"]), extra.strip()) if part) for kind in kinds]

