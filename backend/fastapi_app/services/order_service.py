from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from fastapi_app.models.customer import Customer
from fastapi_app.models.hotel import Hotel
from fastapi_app.models.menu_item import MenuItem
from fastapi_app.models.order import Order, OrderItem, OrderStatus
from fastapi_app.schemas.order import OrderCreate, OrderOut


ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    OrderStatus.NEW.value: {OrderStatus.ACCEPTED.value, OrderStatus.PREPARING.value, OrderStatus.CANCELLED.value},
    OrderStatus.ACCEPTED.value: {OrderStatus.PREPARING.value, OrderStatus.READY.value, OrderStatus.CANCELLED.value},
    OrderStatus.PREPARING.value: {OrderStatus.READY.value, OrderStatus.CANCELLED.value},
    OrderStatus.READY.value: {OrderStatus.COMPLETED.value},
    OrderStatus.COMPLETED.value: set(),
    OrderStatus.CANCELLED.value: set(),
}


def create_order(db: Session, payload: OrderCreate) -> Order:
    hotel = db.get(Hotel, payload.hotel_id)
    if not hotel or not hotel.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Hotel not found or inactive")

    customer = db.get(Customer, payload.customer_id)
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")

    if not payload.items:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Order must contain at least one item")

    order = Order(
        hotel_id=payload.hotel_id,
        customer_id=payload.customer_id,
        status=OrderStatus.NEW.value,
        pickup_time=payload.pickup_time,
        customer_note=payload.customer_note,
        total_amount=Decimal("0.00"),
    )
    db.add(order)
    db.flush()

    total = Decimal("0.00")
    for item in payload.items:
        menu_item = db.get(MenuItem, item.menu_item_id)
        if not menu_item or menu_item.hotel_id != payload.hotel_id or not menu_item.is_available:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid menu item")

        line_total = Decimal(menu_item.price) * item.quantity
        total += line_total
        db.add(
            OrderItem(
                order_id=order.id,
                menu_item_id=menu_item.id,
                item_name_snapshot=menu_item.name,
                quantity=item.quantity,
                unit_price=menu_item.price,
                line_total=line_total,
            )
        )

    order.total_amount = total
    db.commit()
    return get_order_or_404(db, order.id)


def get_order_or_404(db: Session, order_id: int) -> Order:
    order = db.scalar(
        select(Order)
        .where(Order.id == order_id)
        .options(selectinload(Order.customer), selectinload(Order.items))
    )
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return order


def list_orders(db: Session, hotel_id: int | None = None, order_status: str | None = None) -> list[Order]:
    query = select(Order).options(selectinload(Order.customer), selectinload(Order.items)).order_by(Order.created_at.desc())
    if hotel_id:
        query = query.where(Order.hotel_id == hotel_id)
    if order_status:
        query = query.where(Order.status == order_status)
    return list(db.scalars(query).all())


def update_order_status(db: Session, order_id: int, new_status: OrderStatus) -> Order:
    order = get_order_or_404(db, order_id)
    current_status = order.status
    target_status = new_status.value

    if current_status == target_status:
        return order

    allowed_targets = ALLOWED_TRANSITIONS.get(current_status, set())
    if target_status not in allowed_targets:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot move order from {current_status} to {target_status}",
        )

    order.status = target_status
    db.commit()
    return get_order_or_404(db, order.id)


def serialize_order(order: Order) -> dict:
    return OrderOut.model_validate(order).model_dump(mode="json")


def status_message(order: Order) -> str:
    if order.status == OrderStatus.ACCEPTED.value:
        return f"Order #{order.id} accepted. The restaurant has accepted your order."
    if order.status == OrderStatus.PREPARING.value:
        return f"Order #{order.id} is being prepared. Please come to the restaurant."
    if order.status == OrderStatus.READY.value:
        return f"Order #{order.id} is ready. Please come and pick it up."
    if order.status == OrderStatus.COMPLETED.value:
        return f"Order #{order.id} completed. Thank you for ordering."
    if order.status == OrderStatus.CANCELLED.value:
        return f"Sorry, order #{order.id} was not accepted. Please try another hotel."
    return f"Order #{order.id} status: {order.status}."
