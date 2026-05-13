from django.urls import path

from django_app.admin import admin_site

urlpatterns = [
    path("admin/", admin_site.urls),
]

