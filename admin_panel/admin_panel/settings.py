import os
from pathlib import Path
from urllib.parse import unquote, urlparse

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BASE_DIR.parent
load_dotenv(ROOT_DIR / ".env")


def _postgres_database_config(url: str) -> dict[str, object]:
    parsed = urlparse(url.replace("postgresql+psycopg://", "postgresql://"))
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": unquote(parsed.path.lstrip("/")),
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname or "localhost",
        "PORT": str(parsed.port or 5432),
        "CONN_MAX_AGE": 600,
    }


def _sqlite_database_config(url: str) -> dict[str, object]:
    parsed = urlparse(url)
    name = unquote(parsed.path)
    if os.name == "nt" and len(name) >= 3 and name[0] == "/" and name[2] == ":":
        name = name[1:]
    if not name or name == "/":
        name = str(BASE_DIR / "db.sqlite3")
    return {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": name,
    }


SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "change-me-django-secret")
DEBUG = os.getenv("DJANGO_DEBUG", "0") == "1"
ALLOWED_HOSTS = [host.strip() for host in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_app.apps.DjangoAppConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "admin_panel.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "admin_panel.wsgi.application"
ASGI_APPLICATION = "admin_panel.asgi.application"

database_url = os.getenv("DJANGO_DATABASE_URL") or os.getenv(
    "DATABASE_URL",
    "postgresql://hotel:hotel@localhost:5432/hotel_orders",
)
if database_url.startswith("sqlite"):
    DATABASES = {"default": _sqlite_database_config(database_url)}
else:
    DATABASES = {"default": _postgres_database_config(database_url)}

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.getenv("TIME_ZONE", "Asia/Kolkata")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"

FASTAPI_INTERNAL_URL = os.getenv("FASTAPI_INTERNAL_URL", "http://localhost:8000")
BACKEND_API_KEY = os.getenv("BACKEND_API_KEY", "")
