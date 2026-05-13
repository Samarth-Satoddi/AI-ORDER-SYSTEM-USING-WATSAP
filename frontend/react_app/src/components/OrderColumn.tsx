import type { Order, OrderStatus } from "../types";
import OrderCard from "./OrderCard";

interface OrderColumnProps {
  title: string;
  count: number;
  orders: Order[];
  onStatusChange: (orderId: number, status: OrderStatus) => void;
  busyOrderId: number | null;
}

export default function OrderColumn({ title, count, orders, onStatusChange, busyOrderId }: OrderColumnProps) {
  return (
    <section className="order-column">
      <header className="order-column__header">
        <h2>{title}</h2>
        <span>{count}</span>
      </header>
      <div className="order-list">
        {orders.length ? (
          orders.map((order) => (
            <OrderCard
              key={order.id}
              order={order}
              onStatusChange={onStatusChange}
              busy={busyOrderId === order.id}
            />
          ))
        ) : (
          <div className="empty-state">No orders</div>
        )}
      </div>
    </section>
  );
}

