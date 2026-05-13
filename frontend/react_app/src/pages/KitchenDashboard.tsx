import { RefreshCw, Wifi, WifiOff } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { DASHBOARD_TOKEN, WS_URL, fetchHotels, fetchOrders, updateOrderStatus } from "../api";
import OrderColumn from "../components/OrderColumn";
import type { Hotel, Order, OrderStatus, RealtimeEvent } from "../types";

const activeStatuses: OrderStatus[] = ["NEW", "ACCEPTED", "PREPARING", "READY"];

export default function KitchenDashboard() {
  const [hotels, setHotels] = useState<Hotel[]>([]);
  const [selectedHotelId, setSelectedHotelId] = useState<number | null>(null);
  const [orders, setOrders] = useState<Order[]>([]);
  const [busyOrderId, setBusyOrderId] = useState<number | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchHotels()
      .then((items) => {
        setHotels(items);
        const hotelFromUrl = Number(new URLSearchParams(window.location.search).get("hotel_id"));
        const initialHotel = items.find((hotel) => hotel.id === hotelFromUrl) ?? items[0];
        setSelectedHotelId(initialHotel?.id ?? null);
      })
      .catch((err: Error) => setError(err.message));
  }, []);

  const loadOrders = useCallback(() => {
    if (!selectedHotelId) {
      return;
    }
    fetchOrders(selectedHotelId)
      .then((items) => setOrders(items.filter((order) => activeStatuses.includes(order.status))))
      .catch((err: Error) => setError(err.message));
  }, [selectedHotelId]);

  useEffect(() => {
    loadOrders();
  }, [loadOrders]);

  useEffect(() => {
    if (!selectedHotelId) {
      return;
    }

    const socket = new WebSocket(`${WS_URL}/ws/hotels/${selectedHotelId}/orders?token=${DASHBOARD_TOKEN}`);
    socket.onopen = () => setConnected(true);
    socket.onclose = () => setConnected(false);
    socket.onerror = () => setConnected(false);
    socket.onmessage = (event) => {
      const payload = JSON.parse(event.data) as RealtimeEvent;
      setOrders((current) => {
        const withoutCurrent = current.filter((order) => order.id !== payload.order.id);
        if (!activeStatuses.includes(payload.order.status)) {
          return withoutCurrent;
        }
        return [payload.order, ...withoutCurrent].sort(
          (left, right) => Date.parse(right.created_at) - Date.parse(left.created_at)
        );
      });
    };

    return () => socket.close();
  }, [selectedHotelId]);

  const selectedHotel = hotels.find((hotel) => hotel.id === selectedHotelId);

  const grouped = useMemo(
    () => ({
      NEW: orders.filter((order) => order.status === "NEW" || order.status === "ACCEPTED"),
      PREPARING: orders.filter((order) => order.status === "PREPARING"),
      READY: orders.filter((order) => order.status === "READY")
    }),
    [orders]
  );

  const handleStatusChange = async (orderId: number, status: OrderStatus) => {
    setBusyOrderId(orderId);
    setError(null);
    try {
      const updated = await updateOrderStatus(orderId, status);
      setOrders((current) => {
        const next = current.filter((order) => order.id !== updated.id);
        return [updated, ...next].filter((order) => activeStatuses.includes(order.status));
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to update order");
    } finally {
      setBusyOrderId(null);
    }
  };

  return (
    <main className="dashboard-shell">
      <header className="topbar">
        <div className="brand-block">
          <span className="eyebrow">Kitchen</span>
          <h1>{selectedHotel?.name ?? "Orders"}</h1>
        </div>
        <div className="topbar-actions">
          <label className="hotel-select">
            <span>Hotel</span>
            <select
              value={selectedHotelId ?? ""}
              onChange={(event) => setSelectedHotelId(Number(event.target.value))}
            >
              {hotels.map((hotel) => (
                <option key={hotel.id} value={hotel.id}>
                  {hotel.name}
                </option>
              ))}
            </select>
          </label>
          <button className="icon-button" onClick={loadOrders} title="Refresh">
            <RefreshCw size={18} />
          </button>
          <div className={`connection ${connected ? "connection--online" : "connection--offline"}`}>
            {connected ? <Wifi size={18} /> : <WifiOff size={18} />}
            <span>{connected ? "Live" : "Offline"}</span>
          </div>
        </div>
      </header>

      {error ? <div className="error-banner">{error}</div> : null}

      <section className="board">
        <OrderColumn
          title="NEW"
          count={grouped.NEW.length}
          orders={grouped.NEW}
          onStatusChange={handleStatusChange}
          busyOrderId={busyOrderId}
        />
        <OrderColumn
          title="PREPARING"
          count={grouped.PREPARING.length}
          orders={grouped.PREPARING}
          onStatusChange={handleStatusChange}
          busyOrderId={busyOrderId}
        />
        <OrderColumn
          title="READY"
          count={grouped.READY.length}
          orders={grouped.READY}
          onStatusChange={handleStatusChange}
          busyOrderId={busyOrderId}
        />
      </section>
    </main>
  );
}

