from django.db import models


class Hotel(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=160)
    slug = models.CharField(max_length=180, unique=True)
    telegram_label = models.CharField(max_length=180, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = "hotels"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Customer(models.Model):
    id = models.AutoField(primary_key=True)
    telegram_user_id = models.BigIntegerField(unique=True)
    telegram_chat_id = models.BigIntegerField()
    first_name = models.CharField(max_length=120, blank=True, null=True)
    last_name = models.CharField(max_length=120, blank=True, null=True)
    username = models.CharField(max_length=120, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = "customers"
        ordering = ["-created_at"]

    @property
    def display_name(self) -> str:
        name = " ".join(part for part in [self.first_name, self.last_name] if part)
        return name or self.username or str(self.telegram_user_id)

    def __str__(self) -> str:
        return self.display_name


class MenuItem(models.Model):
    id = models.AutoField(primary_key=True)
    hotel = models.ForeignKey(Hotel, on_delete=models.DO_NOTHING, related_name="menu_items")
    name = models.CharField(max_length=180)
    description = models.TextField(blank=True, null=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    is_available = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = "menu_items"
        ordering = ["hotel__name", "name"]

    def __str__(self) -> str:
        return f"{self.hotel.name} - {self.name}"


class Order(models.Model):
    STATUS_CHOICES = [
        ("NEW", "New"),
        ("ACCEPTED", "Accepted"),
        ("PREPARING", "Preparing"),
        ("READY", "Ready"),
        ("COMPLETED", "Completed"),
        ("CANCELLED", "Cancelled"),
    ]

    id = models.AutoField(primary_key=True)
    hotel = models.ForeignKey(Hotel, on_delete=models.DO_NOTHING, related_name="orders")
    customer = models.ForeignKey(Customer, on_delete=models.DO_NOTHING, related_name="orders")
    status = models.CharField(max_length=32, choices=STATUS_CHOICES)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    pickup_time = models.DateTimeField(blank=True, null=True)
    customer_note = models.TextField(blank=True, null=True)
    source = models.CharField(max_length=32)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = "orders"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Order #{self.id}"


class OrderItem(models.Model):
    id = models.AutoField(primary_key=True)
    order = models.ForeignKey(Order, on_delete=models.DO_NOTHING, related_name="items")
    menu_item = models.ForeignKey(MenuItem, on_delete=models.DO_NOTHING)
    item_name_snapshot = models.CharField(max_length=180)
    quantity = models.IntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    line_total = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        managed = False
        db_table = "order_items"

    def __str__(self) -> str:
        return f"{self.item_name_snapshot} x {self.quantity}"


class UserSession(models.Model):
    id = models.AutoField(primary_key=True)
    telegram_user_id = models.BigIntegerField(unique=True)
    hotel = models.ForeignKey(Hotel, on_delete=models.DO_NOTHING, blank=True, null=True)
    state = models.CharField(max_length=64)
    context = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = "user_sessions"

    def __str__(self) -> str:
        return f"{self.telegram_user_id} - {self.state}"
