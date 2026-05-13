from datetime import timedelta

from django.db.models import Count
from django.utils import timezone

from django_app.models import Order


def dashboard_summary() -> dict[str, int]:
    today_start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start = today_start + timedelta(days=1)
    today_orders = Order.objects.filter(created_at__gte=today_start, created_at__lt=tomorrow_start)

    counts = dict(today_orders.values("status").annotate(count=Count("id")).values_list("status", "count"))
    return {
        "orders_today_count": today_orders.count(),
        "pending_orders_count": counts.get("NEW", 0) + counts.get("ACCEPTED", 0) + counts.get("PREPARING", 0),
        "completed_orders_count": counts.get("READY", 0) + counts.get("COMPLETED", 0),
    }

