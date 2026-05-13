export type OrderStatus = "NEW" | "ACCEPTED" | "PREPARING" | "READY" | "COMPLETED" | "CANCELLED";

export interface Hotel {
  id: number;
  name: string;
  slug: string;
  telegram_label?: string | null;
  is_active: boolean;
}

export interface Customer {
  id: number;
  telegram_user_id: number;
  telegram_chat_id: number;
  first_name?: string | null;
  last_name?: string | null;
  username?: string | null;
  display_name: string;
}

export interface OrderItem {
  id: number;
  menu_item_id: number;
  item_name_snapshot: string;
  quantity: number;
  unit_price: string;
  line_total: string;
}

export interface Order {
  id: number;
  hotel_id: number;
  customer_id: number;
  status: OrderStatus;
  total_amount: string;
  pickup_time?: string | null;
  customer_note?: string | null;
  source: string;
  created_at: string;
  updated_at: string;
  customer: Customer;
  items: OrderItem[];
}

export interface RealtimeEvent {
  type: "order.created" | "order.status_changed";
  order: Order;
}

