from django.contrib import admin
from django.urls import path

from dashboard import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", views.dashboard, name="dashboard"),
    path("api/events", views.events_api, name="events_api"),
    path("api/state", views.state_api, name="state_api"),
    path("api/ack", views.ack_api, name="ack_api"),
]
