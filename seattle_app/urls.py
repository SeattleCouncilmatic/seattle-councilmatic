from django.conf import settings
from django.contrib import admin
from django.urls import path, include
from django.conf.urls.static import static
from django.views.generic import RedirectView

from wagtail.admin import urls as wagtailadmin_urls
from wagtail.documents import urls as wagtaildocs_urls

from . import views
from . import api_views

urlpatterns = [
    path("robots.txt", views.robots_txt, name="robots_txt"),
    # Browsers auto-request /favicon.ico (and sometimes /favicon.png) at
    # the root regardless of the <link rel="icon"> in the SPA shell.
    # Without these explicit routes the requests hit the SPA catch-all
    # and return index.html, which Chrome can cache as "no valid icon"
    # and then ignore the <link> tag on subsequent loads. We redirect
    # to /static/favicon.svg (Landmark glyph on navy, matches the
    # header brand mark); .png stays as a fallback for older browsers
    # that don't support SVG favicons. 302 (temporary) so a future
    # icon swap doesn't get stuck in browser caches the way a 301
    # would.
    path("favicon.ico", RedirectView.as_view(url="/static/favicon.svg", permanent=False)),
    path("favicon.png", RedirectView.as_view(url="/static/favicon.png", permanent=False)),
    path("admin/", admin.site.urls),
    path("api/reps/", include("reps.urls")),
    path("api/legislation/recent/", api_views.recent_legislation, name="api_legislation_recent"),
    path("api/legislation/", api_views.legislation_index, name="api_legislation_index"),
    path("api/legislation/<slug:slug>/", api_views.legislation_detail, name="api_legislation_detail"),
    path("api/events/upcoming/", api_views.upcoming_events, name="api_events_upcoming"),
    path("api/events/", api_views.events_index, name="api_events_index"),
    path("api/events/<slug:slug>/", api_views.event_detail, name="api_event_detail"),
    path("api/smc/", api_views.smc_search, name="api_smc_search"),
    path("api/smc/tree/", api_views.smc_tree, name="api_smc_tree"),
    path("api/smc/titles/<str:title_number>/", api_views.smc_title_detail, name="api_smc_title_detail"),
    path("api/smc/chapters/<str:chapter_number>/", api_views.smc_chapter_detail, name="api_smc_chapter_detail"),
    path("api/smc/sections/<str:section_number>/", api_views.smc_section_detail, name="api_smc_section_detail"),
    path("api/smc/appendices/<str:title_number>/<slug:label_slug>/", api_views.smc_appendix_detail, name="api_smc_appendix_detail"),
    path("smc.pdf", views.smc_pdf, name="smc_pdf"),
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
