"""
BudgetBy — Product Category Classifier Engine
Classifies product titles and attributes into one of the 17 standard departments:
- fashion, beauty, electronics, home, sports, footwear, watches, bags, health,
  jewellery, gaming, toys_kids, books, grocery, automotive, pets, miscellaneous.
"""

import re
from typing import Optional

CATEGORY_RULES = [
    # 1. Pets (highest priority to catch feeds, pet supplies)
    ("pets", [
        r"\b(dog food|cat food|puppy food|kitten food|pet food|pedigree|whiskas|drools|purepet|royal canin|me-o|dog treats?|cat treats?)\b",
        r"\b(cat litter|dog leash|pet leash|dog collar|cat collar|pet collar|pet harness|dog bed|pet bed|chew bones?|chew toy|pet shampoo|murgi dana|bird food|hen food|aquarium|fish food|poultry bird)\b",
    ]),
    # 2. Footwear (shoes, sneakers, clogs, heels, slippers)
    ("footwear", [
        r"\b(sneakers?|running shoes?|sports shoes?|walking shoes?|casual shoes?|formal shoes?|loafers?|oxfords?|derby shoes?|monk strap)\b",
        r"\b(slippers?|flip[\s-]?flops?|slides?|chappals?|sandals?|floaters?|high heels?|block heels?|wedges?|stilettos?|pumps?)\b",
        r"\b(boots?|ankle boots?|chelsea boots?|clogs?|crocs|mules?|moccasins?|footwear)\b",
    ]),
    # 3. Watches (wrist watches, smartwatches, bands)
    ("watches", [
        r"\b(smartwatch(es)?|smart watch(es)?|fitness band|smart band|activity tracker)\b",
        r"\b(wrist\s*watch(es)?|analog watch(es)?|digital watch(es)?|chronograph|casio|g-shock|fastrack watch|titan watch|timex|fossil watch)\b",
        r"\bwatch(es)?\b.*\b(dial|strap|water resistant|quartz|automatic|analogue)\b",
        r"\b(couple watch(es)?|kids watch(es)?|men watch|women watch)\b",
    ]),
    # 4. Bags & Luggage
    ("bags", [
        r"\b(handbags?|tote bags?|shoulder bags?|sling bags?|crossbody bags?|satchels?|clutches?)\b",
        r"\b(backpacks?|rucksacks?|duffel bags?|gym bags?|school bags?|laptop backpacks?)\b",
        r"\b(wallets?|card\s*holders?|purses?|money clips?|leather belts?|formal belts?|casual belts?)\b",
        r"\b(trolley bags?|suitcases?|cabin luggage|check-in luggage|travel luggage|travel bags?|luggage)\b",
    ]),
    # 5. Jewellery & Accessories
    ("jewellery", [
        r"\b(earrings?|jhumkas?|stud earrings?|hoop earrings?|drop earrings?|chandbalis?)\b",
        r"\b(necklaces?|pendants?|chokers?|mangalsutras?|silver chains?|gold plated chain)\b",
        r"\b(finger rings?|solitaire rings?|bangles?|bracelets?|kadas?|cufflinks?|anklets?|payal)\b",
        r"\b(sunglasses?|shades eyewear|aviators? sunglasses|wayfarers? sunglasses|polarized sunglasses)\b",
    ]),
    # 6. Gaming & PC
    ("gaming", [
        r"\b(ps5|ps4|playstation|xbox|nintendo switch|gamepad|gaming controllers?|joysticks?)\b",
        r"\b(mechanical keyboards?|rgb gaming|gaming mouse|gaming headsets?|gaming monitors?|graphics cards?|rtx \d{4}|gtx \d{4})\b",
    ]),
    # 7. Health & Nutrition
    ("health", [
        r"\b(whey protein|protein powder|plant protein|isolate protein|gold standard whey|mass gainer)\b",
        r"\b(creatine|pre[\s-]?workout|bcaa|glutamine|multivitamin|vitamin [a-z]\d?|omega[\s-]?3|fish oil|biotin|calcium tablets|zinc tablets)\b",
        r"\b(peanut butter|protein bars?|energy bars?|muesli|granola|chia seeds|apple cider vinegar)\b",
    ]),
    # 8. Automotive
    ("automotive", [
        r"\b(motorcycle helmets?|bike helmets?|full face helmets?|riding gloves|riding jackets?|bike face mask)\b",
        r"\b(car mobile holder|car mounts?|car chargers?|car vacuum|tire inflators?|car body covers?|bike body covers?|car perfume|car air freshener|car shampoo)\b",
    ]),
    # 9. Beauty & Skincare
    ("beauty", [
        r"\b(face\s*wash|cleansers?|face\s*scrub|sunscreen|sun\s*block|spf\s*\d+|face\s*serum|niacinamide|salicylic acid|vitamin c serum|retinol)\b",
        r"\b(moisturizers?|body\s*lotions?|night\s*cream|day\s*cream|cold\s*cream|face\s*cream)\b",
        r"\b(perfumes?|eau\s*de\s*parfum|deodorants?|body\s*sprays?|body\s*mists?|attar|cologne)\b",
        r"\b(shampoos?|hair\s*conditioners?|hair\s*oils?|hair\s*masks?|hair\s*serums?|hair\s*dyes?|hair\s*colors?)\b",
        r"\b(lipsticks?|lip\s*balms?|lip\s*gloss|kajals?|eyeliners?|foundations?|compact\s*powders?|mascaras?|blush|makeup)\b",
        r"\b(beard\s*trimmers?|hair\s*clippers?|shavers?|shaving\s*creams?|after\s*shaves?|razors?|beard\s*oils?)\b",
    ]),
    # 10. Electronics & Gadgets
    ("electronics", [
        r"\b(earbuds?|tws|airbuds?|airdopes?|wireless earbuds?|true wireless)\b",
        r"\b(headphones?|neckbands?|earphones?|bluetooth speakers?|soundbars?|party speakers?)\b",
        r"\b(power\s*banks?|fast\s*chargers?|adapters?|type[\s-]c cables?|charging cables?|usb cables?|otg cables?)\b",
        r"\b(smartphones?|mobile phones?|android phones?|iphones?|5g phones?|laptops?|notebooks? pc|tablets?|ipads?)\b",
        r"\b(pen\s*drives?|memory\s*cards?|external hard disks?|ssds?|routers?|wifi extenders?)\b",
    ]),
    # 11. Home & Kitchen
    ("home", [
        r"\b(water\s*bottles?|flasks?|thermos|lunch\s*boxes?|sippers?|tiffin\s*boxes?)\b",
        r"\b(cookwares?|frying\s*pans?|kadhais?|tawa\s*pans?|pressure\s*cookers?|non[\s-]?stick|triply|casseroles?)\b",
        r"\b(storage\s*containers?|airtight jars?|spice racks?|kitchen organizers?|storage box(es)?|masala box(es)?)\b",
        r"\b(dustbins?|garbage bins?|mops?|spin mops?|brooms?|wipers?|cleaning cloth)\b",
        r"\b(bedsheets?|bed covers?|curtains?|pillow covers?|pillows?|blankets?|quilts?|comforters?|bath towels?)\b",
        r"\b(electric kettles?|air fryers?|mixer grinders?|juicers?|choppers?|sandwich makers?|induction cooktops?|toasters?|irons?|steam irons?)\b",
    ]),
    # 12. Sports & Fitness
    ("sports", [
        r"\b(dumbbells?|barbells?|weight plates?|resistance bands?|gym shakers?|gym gloves?|ab rollers?)\b",
        r"\b(yoga mats?|exercise mats?|skipping ropes?|foam rollers?)\b",
        r"\b(badminton|shuttlecocks?|badminton racquets?|squash|table tennis|tennis racquets?)\b",
        r"\b(cricket bats?|cricket balls?|batting gloves|cricket kits?|cricket helmets?)\b",
        r"\b(footballs?|soccer balls?|basketballs?|volleyballs?|shin guards|goalkeeper gloves)\b",
        r"\b(bicycles?|cycles?|cycling gloves|cycle locks?|camping tents?|trekking)\b",
        r"\b(swimwear|swimsuits?|swim caps?|swimming goggles?)\b",
    ]),
    # 13. Toys & Baby
    ("toys_kids", [
        r"\b(board games?|puzzles?|monopoly|uno cards?|chess boards?|rubik'?s? cubes?)\b",
        r"\b(lego|building blocks?|action figures?|rc cars?|remote control cars?|dolls?|soft toys?|die[\s-]?cast)\b",
        r"\b(diapers?|pampers|mamy poko|huggies|baby wipes?|baby lotions?|baby shampoos?|baby oils?|baby soaps?|feeding bottles?|prams?|strollers?)\b",
    ]),
    # 14. Books & Stationery
    ("books", [
        r"\b(paperback|hardcover|novels?|fiction|bestsellers?|biograph(y|ies)|self[\s-]?help books?)\b",
        r"\b(fountain pens?|gel pens?|ball pens?|notebooks?|diaries|planners?|sketchbooks?|highlighters?|geometry box(es)?)\b",
    ]),
    # 15. Grocery & Gourmet
    ("grocery", [
        r"\b(green tea|black tea|tea bags?|coffee powders?|instant coffee|filter coffee)\b",
        r"\b(almonds?|badam|cashews?|kaju|walnuts?|akhrot|raisins?|kismis|pistachios?|pista|dry fruits?)\b",
        r"\b(dark chocolates?|chocolates?|cookies?|biscuits?|wafers?|sweets?|mithai|honey|olive oil|ghee)\b",
    ]),
    # 16. Fashion & Apparel (General clothing fallback)
    ("fashion", [
        r"\b(t[\s-]?shirts?|polos?|shirts?|kurtas?|kurtis?|sarees?|lehengas?|anarkalis?|sherwanis?|nehru jackets?|ethnic wear)\b",
        r"\b(jeans|denims?|trousers?|chinos?|cargos?|cargo pants?|track pants?|joggers?|shorts?)\b",
        r"\b(dresses?|maxi dresses?|tops?|crop tops?|tunics?|jumpsuits?|blouses?|gowns?|frocks?|skirts?)\b",
        r"\b(jackets?|hoodies?|sweatshirts?|sweaters?|cardigans?|blazers?|coats?|shrugs?)\b",
        r"\b(boxers?|briefs?|trunks?|innerwear|bras?|brassiere|panties?|nightsuits?|nightgowns?|pyjamas?|loungewear)\b",
    ]),
]

NORM_CATEGORY_MAP = {
    "shoes": "footwear",
    "shoe": "footwear",
    "footwear": "footwear",
    "watches": "watches",
    "watch": "watches",
    "bags": "bags",
    "bag": "bags",
    "luggage": "bags",
    "jewellery": "jewellery",
    "jewelry": "jewellery",
    "accessories_fashion": "jewellery",
    "gaming": "gaming",
    "health": "health",
    "nutrition": "health",
    "pets": "pets",
    "pet": "pets",
    "pet_supplies": "pets",
    "automotive": "automotive",
    "car": "automotive",
    "bike": "automotive",
    "beauty": "beauty",
    "skincare": "beauty",
    "personal_care": "beauty",
    "electronics": "electronics",
    "smartphones": "electronics",
    "laptops": "electronics",
    "home": "home",
    "kitchen": "home",
    "appliances": "home",
    "appliances_home": "home",
    "sports": "sports",
    "fitness": "sports",
    "toys": "toys_kids",
    "baby": "toys_kids",
    "toys_kids": "toys_kids",
    "books": "books",
    "stationery": "books",
    "grocery": "grocery",
    "gourmet": "grocery",
    "fashion": "fashion",
    "clothing": "fashion",
    "apparel": "fashion",
    "miscellaneous": "miscellaneous",
    "other": "miscellaneous",
    "misc": "miscellaneous",
    "more": "miscellaneous",
    "general": "miscellaneous",
}


def classify_product(title: str, existing_cat: Optional[str] = None) -> str:
    """Classifies a product into one of the 17 standard departments."""
    title_lower = (title or "").lower()
    
    # 1. Match against precision rules in priority order
    for cat_name, patterns in CATEGORY_RULES:
        for pat in patterns:
            if re.search(pat, title_lower):
                return cat_name
                
    # 2. If existing category is already valid, normalize it
    if existing_cat:
        norm_cat = existing_cat.lower().strip()
        if norm_cat in NORM_CATEGORY_MAP:
            return NORM_CATEGORY_MAP[norm_cat]

    # 3. Fallback to miscellaneous
    return "miscellaneous"
