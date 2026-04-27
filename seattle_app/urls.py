from django.conf import settings
from django.contrib import admin
from django.urls import path, include
from django.conf.urls.static import static

from wagtail.admin import urls as wagtailadmin_urls
from wagtail.documents import urls as wagtaildocs_urls

from . import views
from . import api_views

urlpatterns = [
    path("robots.txt", views.robots_txt, name="robots_txt"),
    path("admin/", admin.site.urls),
    path("api/reps/", include("reps.urls")),
    path("api/legislation/recent/", api_views.recent_legislation, name="api_legislation_recent"),
    path("api/legislation/", api_views.legislation_index, name="api_legislation_index"),
    path("api/legislation/<slug:slug>/", api_views.legislation_detail, name="api_legislation_detail"),
    path("api/events/upcoming/", api_views.upcoming_events, name="api_events_upcoming"),
    path("api/events/", api_views.events_index, name="api_events_index"),
    path("api/events/<slug:slug>/", api_views.event_detail, name="api_event_detail"),
    # Wagtail admin + documents only — wagtail's "" catch-all is intentionally not included
    # so the React SPA can own all non-API, non-admin routes.
    path("cms/", include(wagtailadmin_urls)),
    path("documents/", include(wagtaildocs_urls)),
    # React SPA catch-all (must be last). Matches "" and any unmatched path.
    path("", views.react_app, name="react_index"),
    path("<path:path>", views.react_app, name="react_catchall"),
]

# Error handlers
handler404 = "seattle_app.views.page_not_found"
handler500 = "seattle_app.views.server_error"

# Debug toolbar and static files for development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

    if "debug_toolbar" in settings.INSTALLED_APPS:
        import debug_toolbar

        urlpatterns = [
            path("__debug__/", include(debug_toolbar.urls)),
        ] + urlpatterns
