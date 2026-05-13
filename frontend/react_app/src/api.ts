import type { Hotel, Order, OrderStatus } from "./types";

export const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000/api";
export const WS_URL = import.meta.env.VITE_WS_URL ?? "ws://localhost:8000/api";
export const DASHBOARD_TOKEN = import.meta.env.VITE_DASHBOARD_TOKEN ?? "change-me-dashboard-token";

const dashboardHeaders = {
  "Content-Type": "application/json",
  "X-Dashboard-Token": DASHBOARD_TOKEN
};

export async function fetchHotels(): Promise<Hotel[]> {
  const response = await fetch(`${API_URL}/hotels`);
  if (!response.ok) {
    throw new Error("Unable to load hotels");
  }
  return response.json();
}

export async function fetchOrders(hotelId: number): Promise<Order[]> {
  const response = await fetch(`${API_URL}/orders?hotel_id=${hotelId}`, {
    headers: dashboardHeaders
  });
  if (!response.ok) {
    throw new Error("Unable to load orders");
  }
  return response.json();
}

export async function updateOrderStatus(orderId: number, status: OrderStatus): Promise<Order> {
  const response = await fetch(`${API_URL}/orders/${orderId}/status`, {
    method: "PATCH",
    headers: dashboardHeaders,
    body: JSON.stringify({ status })
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail ?? "Unable to update order");
  }
  return response.json();
}

