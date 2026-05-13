cd "C:\hotel order syaytem"
& "C:\hotel order syaytem\.venv\Scripts\Activate.ps1"

# Set environment variables for SQLite database
$env:DATABASE_URL="sqlite:///C:/hotel order syaytem/hotel_orders_dev.db"
$env:DJANGO_DEBUG="1"
$env:DJANGO_ALLOWED_HOSTS="localhost,127.0.0.1"

# Run Django development server
cd admin_panel
python manage.py runserver 0.0.0.0:8001
