"""URL lists for the digests app.

Mounted at two prefixes in seattle_app/urls.py: ``api_urlpatterns`` under
``/api/digests/`` (JSON, consumed by the React SPA) and ``page_urlpatterns``
under ``/digests/`` (server-rendered token entry points from email links).
The SPA-owned routes ``/digests/subscribe`` and ``/digests/preferences``
are deliberately NOT here — they fall through to the React catch-all.
"""
from django.urls import path

from . import views

app_name = "digests"

api_urlpatterns = [
    path("subscribe", views.subscribe, name="subscribe"),
    path("preferences", views.preferences_api, name="preferences"),
    path("options", views.options, name="options"),
]

page_urlpatterns = [
    path("confirm", views.confirm, name="confirm"),
    path("manage", views.manage, name="manage"),
    path("unsubscribe", views.unsubscribe, name="unsubscribe"),
]
