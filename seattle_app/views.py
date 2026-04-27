import os
from django.conf import settings
from django.http import FileResponse, Http404
from django.shortcuts import render


def react_app(request, path=""):
    index_path = settings.BASE_DIR / "frontend" / "dist" / "index.html"
    return FileResponse(open(index_path, "rb"), content_type="text/html")


def smc_pdf(request):
    """Serve the local SMC PDF as a download. Linked from the /municode/
    index page only — explicit "(N MB)" affordance so users opt in to the
    long transfer. We tried wiring this into per-section page links and
    it was too slow without HTTP Range; here the wait is expected."""
    path = settings.SMC_PDF_PATH
    if not path or not path.exists():
        raise Http404("SMC PDF not configured or missing on disk.")
    response = FileResponse(open(path, "rb"), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{path.name}"'
    return response


def robots_txt(request):
    """Serve robots.txt file with crawling permissions based on environment."""
    return render(
        request,
        "robots.txt",
        {"ALLOW_CRAWL": os.getenv("ALLOW_CRAWL", "False").lower() == "true"},
        content_type="text/plain",
    )


def page_not_found(request, exception, template_name="404.html"):
    """Custom 404 error handler."""
    return render(request, template_name, status=404)


def server_error(request, template_name="500.html"):
    """Custom 500 error handler."""
    return render(request, template_name, status=500)
