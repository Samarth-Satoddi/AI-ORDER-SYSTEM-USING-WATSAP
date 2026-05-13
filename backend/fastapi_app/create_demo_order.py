import argparse
from decimal import Decimal

from sqlalchemy import select

from fastapi_app.db.session import SessionLocal
from fastapi_app.models.customer import Customer
from fastapi_app.models.hotel import Hotel
from fastapi_app.models.menu_item import MenuItem
from fastapi_app.models.order import Order, OrderItem, OrderStatus


def create_demo_order(hotel_id: int, query: str, quantity: int) -> Order:
    db = SessionLocal()
    try:
        hotel = db.get(Hotel, hotel_id)
        if hotel is None:
            raise ValueError(f"Hotel {hotel_id} was not found")

        menu_item = db.scalar(
            select(MenuItem)
            .where(
                MenuItem.hotel_id == hotel_id,
                MenuItem.is_available.is_(True),
                MenuItem.name.ilike(f"%{query}%"),
            )
            .order_by(MenuItem.name.asc())
        )
        if menu_item is None:
            raise ValueError(f"No available menu item matched {query!r} for hotel {hotel_id}")

        customer = db.scalar(select(Customer).where(Customer.telegram_user_id == 900001))
        if customer is None:
            customer = Customer(
                telegram_user_id=900001,
                telegram_chat_id=900001,
                first_name="Demo",
                last_name="Customer",
                username="demo_customer",
            )
            db.add(customer)
            db.flush()

        line_total = Decimal(menu_item.price) * quantity
        order = Order(
            hotel_id=hotel.id,
            customer_id=customer.id,
            status=OrderStatus.NEW.value,
            total_amount=line_total,
            customer_note="Demo order created from local dev helper",
            source="demo",
        )
        db.add(order)
        db.flush()
        db.add(
            OrderItem(
                order_id=order.id,
                menu_item_id=menu_item.id,
                item_name_snapshot=menu_item.name,
                quantity=quantity,
                unit_price=menu_item.price,
                line_total=line_total,
            )
        )
        db.commit()
        db.refresh(order)
        print(
            f"Created order #{order.id}: {quantity} x {menu_item.name} "
            f"for {hotel.name}. Customer ID: {customer.id}."
        )
        return order
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a demo order for the kitchen dashboard.")
    parser.add_argument("--hotel-id", type=int, default=1)
    parser.add_argument("--query", default="Idli")
    parser.add_argument("--quantity", type=int, default=2)
    args = parser.parse_args()

    create_demo_order(args.hotel_id, args.query, args.quantity)


if __name__ == "__main__":
    main()
