import { BellRing, Check, ChefHat, Flame, X } from "lucide-react";

import type { Order, OrderStatus } from "../types";

interface OrderCardProps {
  order: Order;
  onStatusChange: (orderId: number, status: OrderStatus) => void;
  busy: boolean;
}

export default function OrderCard({ order, onStatusChange, busy }: OrderCardProps) {
  const createdAt = new Date(order.created_at).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit"
  });

  return (
    <article className="order-card">
      <div className="order-card__top">
        <div>
          <div className="order-id">#{order.id}</div>
          <div className="customer-name">{order.customer.display_name}</div>
        </div>
        <span className={`status-pill status-pill--${order.status.toLowerCase()}`}>{order.status}</span>
      </div>

      <div className="order-items">
        {order.items.map((item) => (
          <div className="order-item" key={item.id}>
            <span>{item.item_name_snapshot}</span>
            <strong>x{item.quantity}</strong>
          </div>
        ))}
      </div>

      <div className="order-meta">
        <span>{createdAt}</span>
        <span>INR {Number(order.total_amount).toFixed(2)}</span>
      </div>

      {order.customer_note ? <p className="order-note">{order.customer_note}</p> : null}

      <div className="order-actions">
        {order.status === "NEW" ? (
          <>
            <button
              className="action-button action-button--accept"
              onClick={() => onStatusChange(order.id, "ACCEPTED")}
              disabled={busy}
              title="Accept"
            >
              <Check size={16} />
              <span>Accept</span>
            </button>
            <button
              className="action-button action-button--reject"
              onClick={() => onStatusChange(order.id, "CANCELLED")}
              disabled={busy}
              title="Reject"
            >
              <X size={16} />
              <span>Reject</span>
            </button>
          </>
        ) : null}
        {order.status === "NEW" || order.status === "ACCEPTED" ? (
          <button
            className="action-button action-button--prepare"
            onClick={() => onStatusChange(order.id, "PREPARING")}
            disabled={busy}
            title="Mark Preparing"
          >
            <Flame size={16} />
            <span>Preparing</span>
          </button>
        ) : null}
        {order.status === "ACCEPTED" || order.status === "PREPARING" ? (
          <button
            className="action-button action-button--ready"
            onClick={() => onStatusChange(order.id, "READY")}
            disabled={busy}
            title="Mark Ready"
          >
            <BellRing size={16} />
            <span>Ready</span>
          </button>
        ) : null}
        {order.status === "READY" ? (
          <button
            className="action-button action-button--complete"
            onClick={() => onStatusChange(order.id, "COMPLETED")}
            disabled={busy}
            title="Mark picked up and paid"
          >
            <ChefHat size={16} />
            <span>Pickup</span>
          </button>
        ) : null}
      </div>
    </article>
  );
}
