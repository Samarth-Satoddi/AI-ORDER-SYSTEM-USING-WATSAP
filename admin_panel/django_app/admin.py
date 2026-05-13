import requests
from django.conf import settings
from django.contrib import admin, messages
from django.contrib.admin import AdminSite

from django_app.models import Customer, Hotel, MenuItem, Order, OrderItem, UserSession
from django_app.views import dashboard_summary


class FoodOrderingAdminSite(AdminSite):
    site_header = "Hotel Food Ordering Admin"
    site_title = "Hotel Orders"
    index_title = "Operations Summary"
    index_template = "admin/dashboard_index.html"

    def each_context(self, request):
        context = super().each_context(request)
        context.update(dashboard_summary())
        return context


admin_site = FoodOrderingAdminSite(name="hotel_ordering_admin")


@admin.register(Hotel, site=admin_site)
class HotelAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "telegram_label", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name", "slug", "telegram_label")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(MenuItem, site=admin_site)
class MenuItemAdmin(admin.ModelAdmin):
    list_display = ("name", "hotel", "price", "is_available", "updated_at")
    list_filter = ("hotel", "is_available")
    search_fields = ("name", "description", "hotel__name")
    autocomplete_fields = ("hotel",)


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    can_delete = False
    readonly_fields = ("menu_item", "item_name_snapshot", "quantity", "unit_price", "line_total")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Order, site=admin_site)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "customer_name", "items_summary", "pickup_time", "status", "hotel", "created_at")
    list_filter = ("hotel", "status", "created_at")
    search_fields = ("=id", "customer__username", "customer__first_name", "items__item_name_snapshot")
    date_hierarchy = "created_at"
    readonly_fields = ("status", "total_amount", "source", "created_at", "updated_at")
    autocomplete_fields = ("hotel", "customer")
    inlines = (OrderItemInline,)
    actions = ("accept_orders", "mark_preparing", "mark_ready")

    @admin.display(description="Customer Name")
    def customer_name(self, obj: Order) -> str:
        return obj.customer.display_name

    @admin.display(description="Items")
    def items_summary(self, obj: Order) -> str:
        return ", ".join(str(item) for item in obj.items.all())

    @admin.action(description="Accept order")
    def accept_orders(self, request, queryset):
        self._send_status_action(request, queryset, "ACCEPTED")

    @admin.action(description="Mark as Preparing")
    def mark_preparing(self, request, queryset):
        self._send_status_action(request, queryset, "PREPARING")

    @admin.action(description="Mark as Ready")
    def mark_ready(self, request, queryset):
        self._send_status_action(request, queryset, "READY")

    def _send_status_action(self, request, queryset, status_value: str) -> None:
        successes = 0
        failures = []
        base_url = settings.FASTAPI_INTERNAL_URL.rstrip("/")
        headers = {"X-API-Key": settings.BACKEND_API_KEY}

        for order in queryset:
            try:
                response = requests.patch(
                    f"{base_url}/api/orders/{order.id}/status",
                    json={"status": status_value},
                    headers=headers,
                    timeout=8,
                )
                response.raise_for_status()
                successes += 1
            except requests.RequestException as exc:
                failures.append(f"#{order.id}: {exc}")

        if successes:
            self.message_user(request, f"{successes} order(s) moved to {status_value}.", messages.SUCCESS)
        if failures:
            self.message_user(request, "Failed to update " + "; ".join(failures), messages.ERROR)


@admin.register(Customer, site=admin_site)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("display_name", "telegram_user_id", "telegram_chat_id", "username", "created_at")
    search_fields = ("first_name", "last_name", "username", "=telegram_user_id")
    readonly_fields = (
        "telegram_user_id",
        "telegram_chat_id",
        "first_name",
        "last_name",
        "username",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(UserSession, site=admin_site)
class UserSessionAdmin(admin.ModelAdmin):
    list_display = ("telegram_user_id", "hotel", "state", "updated_at")
    list_filter = ("state", "hotel")
    readonly_fields = ("telegram_user_id", "hotel", "state", "context", "created_at", "updated_at")

    def has_add_permission(self, request):
        return False
