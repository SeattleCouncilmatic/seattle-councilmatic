from django.conf import settings
from django.contrib import admin
from django.urls import path, include
from django.conf.urls.static import static

from wagtail.admin import urls as wagtailadmin_urls
from wagtail import urls as wagtail_urls
from wagtail.documents import urls as wagtaildocs_urls

from . import views
from . import api_views

urlpatterns = [
    path("", views.IndexView.as_view(), name="index"),
    path("robots.txt", views.robots_txt, name="robots_txt"),
    path("admin/", admin.site.urls),
    path("api/reps/", include("reps.urls")),
    path("api/legislation/recent/", api_views.recent_legislation, name="api_legislation_recent"),
    path("api/legislation/<slug:slug>/", api_views.legislation_detail, name="api_legislation_detail"),
    path("api/meetings/upcoming/", api_views.upcoming_meetings, name="api_meetings_upcoming"),
    path("api/meetings/<slug:slug>/", api_views.meeting_detail, name="api_meeting_detail"),
    path("", include("councilmatic_search.urls")),
    path("", include("councilmatic_cms.urls")),
    # Catch-all: serve the React SPA for any remaining frontend routes
    path("<path:path>", views.IndexView.as_view(), name="react_catchall"),
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
