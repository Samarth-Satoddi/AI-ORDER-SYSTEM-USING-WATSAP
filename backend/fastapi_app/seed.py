from decimal import Decimal
from typing import TypedDict

from sqlalchemy import select
from sqlalchemy.orm import Session

from fastapi_app.db.session import SessionLocal
from fastapi_app.models.hotel import Hotel
from fastapi_app.models.menu_item import MenuItem


class SeedResult(TypedDict):
    hotels: int
    menu_items: int


HOTELS = [
    (
        "grand-south-tiffins",
        "Grand South Tiffins",
        [
            ("Idli Sambar", "Steamed rice cakes served with sambar and chutney", "55.00"),
            ("Medu Vada", "Crispy lentil vada with coconut chutney", "65.00"),
            ("Masala Dosa", "Crisp dosa with spiced potato filling", "95.00"),
            ("Mysore Masala Dosa", "Spicy chutney dosa with potato masala", "115.00"),
            ("Onion Uttapam", "Thick dosa topped with onions and herbs", "105.00"),
            ("Filter Coffee", "Traditional South Indian hot coffee", "40.00"),
        ],
    ),
    (
        "punjab-darbar",
        "Punjab Darbar",
        [
            ("Paneer Butter Masala", "Paneer cubes in rich tomato-butter gravy", "210.00"),
            ("Dal Makhani", "Slow-cooked black lentils with butter", "180.00"),
            ("Chole Bhature", "Spiced chickpeas with fried bread", "150.00"),
            ("Butter Naan", "Soft tandoor naan brushed with butter", "45.00"),
            ("Jeera Rice", "Basmati rice tempered with cumin", "120.00"),
            ("Lassi Sweet", "Chilled sweet yogurt drink", "80.00"),
        ],
    ),
    (
        "royal-biryani-house",
        "Royal Biryani House",
        [
            ("Chicken Dum Biryani", "Hyderabadi-style chicken biryani with raita", "240.00"),
            ("Mutton Biryani", "Fragrant rice with tender mutton pieces", "310.00"),
            ("Veg Biryani", "Aromatic rice with vegetables and spices", "180.00"),
            ("Egg Biryani", "Biryani rice topped with boiled eggs", "190.00"),
            ("Chicken 65", "Spicy fried chicken bites", "220.00"),
            ("Double Ka Meetha", "Bread pudding with nuts and saffron", "110.00"),
        ],
    ),
    (
        "china-town-wok",
        "China Town Wok",
        [
            ("Veg Fried Rice", "Wok-tossed rice with vegetables", "140.00"),
            ("Chicken Fried Rice", "Wok-tossed rice with chicken and egg", "180.00"),
            ("Veg Hakka Noodles", "Stir-fried noodles with vegetables", "150.00"),
            ("Chicken Schezwan Noodles", "Spicy noodles with chicken", "190.00"),
            ("Gobi Manchurian", "Crispy cauliflower in Manchurian sauce", "160.00"),
            ("Chilli Chicken", "Chicken tossed with peppers and chilli sauce", "230.00"),
        ],
    ),
    (
        "tandoor-flames",
        "Tandoor Flames",
        [
            ("Tandoori Chicken Half", "Char-grilled chicken with tandoori spices", "260.00"),
            ("Chicken Tikka", "Boneless tandoori chicken pieces", "240.00"),
            ("Paneer Tikka", "Tandoori paneer with capsicum and onion", "220.00"),
            ("Seekh Kebab", "Minced meat kebabs cooked in tandoor", "250.00"),
            ("Garlic Naan", "Tandoor naan topped with garlic", "60.00"),
            ("Rumali Roti", "Thin soft roomali roti", "35.00"),
        ],
    ),
    (
        "coastal-curry",
        "Coastal Curry",
        [
            ("Fish Curry Meals", "Fish curry served with rice and sides", "260.00"),
            ("Prawn Masala", "Prawns cooked in coastal spice masala", "320.00"),
            ("Kerala Parotta", "Layered flaky flatbread", "35.00"),
            ("Chicken Chettinad", "Peppery Chettinad chicken curry", "240.00"),
            ("Appam", "Soft rice appam", "30.00"),
            ("Lemon Soda", "Fresh lemon soda served chilled", "55.00"),
        ],
    ),
    (
        "garden-veg-cafe",
        "Garden Veg Cafe",
        [
            ("Veg Meals", "Rice meal with sambar, rasam, curry, and curd", "140.00"),
            ("Curd Rice", "Rice mixed with curd and tempering", "95.00"),
            ("Tomato Rice", "Tangy tomato rice with spices", "110.00"),
            ("Aloo Paratha", "Stuffed potato paratha with curd", "120.00"),
            ("Mushroom Pepper Fry", "Mushrooms tossed with pepper masala", "170.00"),
            ("Fresh Lime Juice", "Fresh lime juice with sugar or salt", "50.00"),
        ],
    ),
    (
        "urban-burger-grill",
        "Urban Burger Grill",
        [
            ("Classic Veg Burger", "Veg patty burger with lettuce and sauce", "130.00"),
            ("Crispy Chicken Burger", "Crispy chicken burger with mayo", "170.00"),
            ("Peri Peri Fries", "Fries tossed with peri peri seasoning", "120.00"),
            ("Cheese Sandwich", "Grilled cheese sandwich", "110.00"),
            ("Chicken Club Sandwich", "Triple-layer chicken club sandwich", "190.00"),
            ("Chocolate Milkshake", "Thick chocolate milkshake", "130.00"),
        ],
    ),
    (
        "breakfast-bowl",
        "Breakfast Bowl",
        [
            ("Poori Bhaji", "Fried poori with potato bhaji", "85.00"),
            ("Set Dosa", "Soft dosas served with sambar and chutney", "90.00"),
            ("Upma", "Semolina breakfast with vegetables", "70.00"),
            ("Pongal", "Rice and lentil pongal with ghee", "85.00"),
            ("Bread Omelette", "Toasted bread with masala omelette", "90.00"),
            ("Tea", "Hot milk tea", "25.00"),
        ],
    ),
    (
        "midnight-paratha",
        "Midnight Paratha",
        [
            ("Paneer Paratha", "Stuffed paneer paratha with curd", "140.00"),
            ("Gobi Paratha", "Stuffed cauliflower paratha", "120.00"),
            ("Egg Paratha", "Layered paratha with egg", "130.00"),
            ("Chicken Keema Paratha", "Paratha stuffed with chicken keema", "180.00"),
            ("Rajma Chawal", "Kidney bean curry with rice", "150.00"),
            ("Masala Chaas", "Spiced buttermilk", "45.00"),
        ],
    ),
    (
        "sweet-and-snack-corner",
        "Sweet And Snack Corner",
        [
            ("Samosa", "Crispy samosa with potato filling", "25.00"),
            ("Kachori", "Spiced crispy kachori", "30.00"),
            ("Pav Bhaji", "Buttery pav with mashed vegetable bhaji", "130.00"),
            ("Dahi Puri", "Crispy puri with curd and chutneys", "90.00"),
            ("Gulab Jamun", "Warm milk-solid dumplings in syrup", "60.00"),
            ("Jalebi", "Crispy spiral sweet", "70.00"),
        ],
    ),
    (
        "healthy-harvest",
        "Healthy Harvest",
        [
            ("Sprouts Salad", "Fresh sprouts with onion, tomato, and lemon", "110.00"),
            ("Paneer Protein Bowl", "Paneer, rice, vegetables, and sauce", "220.00"),
            ("Chicken Protein Bowl", "Grilled chicken, rice, vegetables, and sauce", "260.00"),
            ("Veg Clear Soup", "Light vegetable clear soup", "100.00"),
            ("Fruit Bowl", "Seasonal cut fruits", "130.00"),
            ("Watermelon Juice", "Fresh watermelon juice", "80.00"),
        ],
    ),
]


def seed(db: Session | None = None) -> SeedResult:
    owns_session = db is None
    db = db or SessionLocal()
    hotel_count = 0
    menu_item_count = 0

    try:
        for slug, name, menu in HOTELS:
            hotel = db.scalar(select(Hotel).where(Hotel.slug == slug))
            if not hotel:
                hotel = Hotel(slug=slug, name=name)
                db.add(hotel)
                db.flush()
                hotel_count += 1

            hotel.name = name
            hotel.telegram_label = name
            hotel.is_active = True

            for item_name, description, price in menu:
                menu_item = db.scalar(
                    select(MenuItem).where(MenuItem.hotel_id == hotel.id, MenuItem.name == item_name)
                )
                if not menu_item:
                    menu_item = MenuItem(hotel_id=hotel.id, name=item_name)
                    db.add(menu_item)
                    menu_item_count += 1

                menu_item.description = description
                menu_item.price = Decimal(price)
                menu_item.is_available = True

        db.commit()
        return {"hotels": hotel_count, "menu_items": menu_item_count}
    except Exception:
        db.rollback()
        raise
    finally:
        if owns_session:
            db.close()


if __name__ == "__main__":
    result = seed()
    print(f"Seed data inserted. New hotels: {result['hotels']}, new menu items: {result['menu_items']}.")
