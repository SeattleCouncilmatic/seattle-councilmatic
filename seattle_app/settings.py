import os
import dj_database_url
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "your-secret-key-here")

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv("DEBUG", "False").lower() == "true"

ALLOWED_HOSTS = os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

# Required by Django 4+ for any state-changing POST behind an HTTPS
# reverse proxy (admin login, Wagtail CMS, the address-lookup form).
# Caddy terminates TLS and forwards to gunicorn over plain HTTP, so
# without this Django thinks the request is HTTP and rejects the
# CSRF token. Comma-separated list of full origins (scheme + host).
CSRF_TRUSTED_ORIGINS = [
    o for o in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",") if o
]
# Dev-mode auto-allow for the Vite dev server (:5173) and Django
# itself (:8000). When the browser hits `localhost:5173/admin/`, the
# `Origin` header is `http://localhost:5173`; Vite proxies the
# request to Django on :8000, which Django would otherwise reject
# as cross-origin. Production is unaffected — DEBUG=False there, so
# only the explicit env-var values count.
if DEBUG:
    CSRF_TRUSTED_ORIGINS.extend([
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ])

# Application definition
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.gis",
    "django.contrib.humanize",
    "django.contrib.postgres",
    "corsheaders",
    # Core apps
    "opencivicdata.core",
    "opencivicdata.legislative",
    "councilmatic_core",
    "seattle_app",
    "seattle",
    "reps",
    "digests",
    # CMS layer - Remove if CMS not required
    "councilmatic_cms",
    "wagtail.contrib.forms",
    "wagtail.contrib.redirects",
    "wagtail.contrib.typed_table_block",
    "wagtail.embeds",
    "wagtail.sites",
    "wagtail.users",
    "wagtail.snippets",
    "wagtail.documents",
    "wagtail.images",
    "wagtail.search",
    "wagtail.admin",
    "wagtail",
    "modelcluster",
    "taggit",
]

if DEBUG:
    INSTALLED_APPS.append("debug_toolbar")

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    # Cache middleware emits Cache-Control: max-age=600 on every cacheable
    # response. In dev (DEBUG=True) the cache backend is `dummy.DummyCache`
    # so server-side caching is a no-op, but the headers still tell the
    # browser to cache for 10 minutes — which makes admin-edit-then-
    # refresh workflows confusing (saves persist, API returns fresh data,
    # but the browser keeps showing the old response). Skip it entirely
    # in dev. Closes #159.
    *([] if DEBUG else ["django.middleware.cache.UpdateCacheMiddleware"]),
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    *([] if DEBUG else ["django.middleware.cache.FetchFromCacheMiddleware"]),
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

if DEBUG:
    MIDDLEWARE.append("debug_toolbar.middleware.DebugToolbarMiddleware")

ROOT_URLCONF = "seattle_app.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "seattle_app" / "templates"],
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

WSGI_APPLICATION = "seattle_app.wsgi.application"

# Database
DATABASES = {
    "default": dj_database_url.parse(
        os.getenv(
            "DATABASE_URL",
            "postgis://postgres:postgres@localhost:5432/seattle_councilmatic",
        ),
        conn_max_age=600,
        ssl_require=True if os.getenv("POSTGRES_REQUIRE_SSL") == "True" else False,
        engine="django.contrib.gis.db.backends.postgis",
    )
}

# Caching
cache_backend = "dummy.DummyCache" if DEBUG else "db.DatabaseCache"
CACHES = {
    "default": {
        "BACKEND": f"django.core.cache.backends.{cache_backend}",
        "LOCATION": "councilmatic_cache_table" if not DEBUG else "",
        "TIMEOUT": 60 * 10,  # 10 minutes
        "OPTIONS": {
            "MAX_ENTRIES": 1000,
        },
    }
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

# Internationalization
LANGUAGE_CODE = "en-us"
TIME_ZONE = "America/Los_Angeles"  # Update this for your city
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [
    BASE_DIR / "seattle_app" / "static",
    BASE_DIR / "frontend" / "dist",
]

# Media files
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# SMC source PDF — served at /smc.pdf as a download link on the
# /municode/ index page. Filename is dated; SMC_PDF_FILENAME env var
# overrides for deploys with a different snapshot.
SMC_PDF_PATH = BASE_DIR / "_data" / os.getenv(
    "SMC_PDF_FILENAME", "seattle_municipal_code_20260421.pdf"
)

# Default primary key field type
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Security settings
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True

# Debug toolbar settings
if DEBUG:
    INTERNAL_IPS = [
        "127.0.0.1",
        "localhost",
        "0.0.0.0",
    ]

WAGTAIL_SITE_NAME = "Seattle Councilmatic"
# Used by Wagtail for outbound notification email URLs. Without it,
# the admin's W003 system check fires every boot. Default points at
# the canonical prod hostname; override via env for staging deploys.
WAGTAILADMIN_BASE_URL = os.getenv(
    "WAGTAILADMIN_BASE_URL",
    "https://www.seattlecouncilmatic.org/cms/",
)

OCD_CITY_COUNCIL_NAME = os.getenv("OCD_CITY_COUNCIL_NAME", WAGTAIL_SITE_NAME)

# Claude / Anthropic API for plain-English summaries
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
# The defaults below are the CANONICAL per-pipeline model choices. The env
# overrides exist for deliberate per-environment pins only — never set a
# CLAUDE_*_MODEL env var that merely duplicates the default: stale pins
# silently detach an environment when the default moves (prod ran the
# legislation pipeline on a superseded Opus for weeks, and a leftover Haiku
# pin surfaced in the Sonnet 5 rollout audit — see WORK_LOG).
# All Sonnet pipelines moved 4.6 → Sonnet 5 on 2026-07-09. Sonnet 5 accepts
# the adaptive `thinking` param the batch commands send (the only gate is
# _supports_adaptive_thinking's haiku check in claude_service.py).
#
# Sonnet: balanced cost/quality for SMC-section summaries. Cached few-shot
# system prompt + Anthropic Batch API keep cost reasonable. The corpus
# backfill ran on Sonnet 4.6; Haiku 4.5 was tried and is too inconsistent
# for legal-summary work.
CLAUDE_CODE_SECTION_MODEL = os.getenv("CLAUDE_CODE_SECTION_MODEL", "claude-sonnet-5")
# Sonnet: balanced cost/quality for legislation summarization. The
# task is mostly reformatting the staff Summary and Fiscal Note into
# the structured JSON schema (output_config enforces format), so
# Sonnet is sufficient. Set CLAUDE_LEGISLATION_MODEL=claude-opus-4-8
# in the environment for higher-quality runs (~5x cost).
CLAUDE_LEGISLATION_MODEL = os.getenv("CLAUDE_LEGISLATION_MODEL", "claude-sonnet-5")
# Opus: gold-standard summaries of a curated section set; the outputs become
# few-shot examples for the bulk Sonnet run. Calibration only — not bulk.
CLAUDE_BOOTSTRAP_MODEL = os.getenv("CLAUDE_BOOTSTRAP_MODEL", "claude-opus-4-8")
# Sonnet: balanced cost/quality for interactive chat.
CLAUDE_CHAT_MODEL = os.getenv("CLAUDE_CHAT_MODEL", "claude-sonnet-5")
# Sonnet: short structured-JSON tagging task (1-3 enum tags per bill).
# Inputs are tiny (title + first 2k chars of bill text); cached system
# prompt makes per-bill cost cents. Haiku 4.5 likely sufficient too —
# revisit if Sonnet cost becomes meaningful at corpus scale.
CLAUDE_BILL_TAG_MODEL = os.getenv("CLAUDE_BILL_TAG_MODEL", "claude-sonnet-5")
# Sonnet: 2-3 paragraph rep summary card synthesizing tenure, committees,
# sponsorship portfolio, voting record, and bio prose. Per-rep input is
# ~2-4 KB; cached system prompt makes the 9-rep batch cost trivial.
CLAUDE_REP_SUMMARY_MODEL = os.getenv("CLAUDE_REP_SUMMARY_MODEL", "claude-sonnet-5")
# Sonnet: meeting overview + per-agenda-item summaries from the
# captioned transcript + roster + chapter list. Per-meeting input is
# ~30-100 KB (auto-captioned SRT text); two-tier structured output
# (overview + array of item summaries) in a single call so prompt
# caching applies once per meeting.
CLAUDE_EVENT_SUMMARY_MODEL = os.getenv("CLAUDE_EVENT_SUMMARY_MODEL", "claude-sonnet-5")
# Sonnet: 2-3 paragraph committee card — focus area + recent activity,
# synthesized from the committee's roster, recent meeting overviews, and the
# bills it has handled. Only 9 committees and re-summarized solely on change
# (content_hash), so cost is negligible.
CLAUDE_COMMITTEE_SUMMARY_MODEL = os.getenv("CLAUDE_COMMITTEE_SUMMARY_MODEL", "claude-sonnet-5")

# Outbound email (pipeline health alerts — #210; and any future notifications).
# Set the SMTP vars in the environment to enable real sending. Without
# EMAIL_HOST, Django's default backend would try localhost:25 and fail, so fall
# back to the console backend (logs the message) — alerts still surface in the
# cron log, just not as email, until SMTP is configured.
EMAIL_HOST = os.getenv("EMAIL_HOST", "")
if EMAIL_HOST:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
    EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
    EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
    EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "True").lower() == "true"
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = os.getenv(
    "DEFAULT_FROM_EMAIL", "Seattle Councilmatic <noreply@seattlecouncilmatic.org>"
)

# Pipeline health alerting (#210). `check_pipeline_health` runs on its own cron
# tick and emails when no successful full-cycle has finished within
# PIPELINE_HEARTBEAT_HOURS, with a digest of recent failures. Keep the window
# above the 6h cadence so one slow cycle doesn't false-alarm. Recipients:
# PIPELINE_ALERT_EMAILS (comma-separated); re-nags at most every
# PIPELINE_ALERT_RENOTIFY_HOURS while unhealthy, plus one note on recovery.
PIPELINE_HEARTBEAT_HOURS = int(os.getenv("PIPELINE_HEARTBEAT_HOURS", "8"))
PIPELINE_ALERT_RENOTIFY_HOURS = int(os.getenv("PIPELINE_ALERT_RENOTIFY_HOURS", "12"))
PIPELINE_ALERT_EMAILS = [
    e.strip() for e in os.getenv("PIPELINE_ALERT_EMAILS", "").split(",") if e.strip()
]

# Email digests (#231). Phase 1 ships subscription plumbing; digest
# composition/LLM/Postmark land in later phases.
#
# All outbound digest mail goes through the DigestEmailClient interface
# (digests/services/email_client.py). "smtp" reuses the EMAIL_* config
# above and is for TEST-TO-SELF ONLY — never real subscribers (no bounce
# handling, relay volume caps). "postmark" is the production transport,
# wired in Phase 4.
DIGEST_EMAIL_BACKEND = os.getenv("DIGEST_EMAIL_BACKEND", "smtp")
DIGEST_FROM_EMAIL = os.getenv("DIGEST_FROM_EMAIL", DEFAULT_FROM_EMAIL)
# Keys the stateless HMAC manage/unsubscribe tokens. Dedicated secret so it
# rotates independently of SECRET_KEY (rotation invalidates outstanding
# email links but not sessions); tokens.py falls back to SECRET_KEY when
# unset so dev works without it.
SUBSCRIBER_TOKEN_SECRET = os.getenv("SUBSCRIBER_TOKEN_SECRET", "")
# CAN-SPAM physical postal address, rendered in every digest footer
# (Phase 2 templates). Required before public launch.
DIGEST_POSTAL_ADDRESS = os.getenv("DIGEST_POSTAL_ADDRESS", "")

# Logging (#205). The project previously defined no LOGGING, so settings.LOGGING
# was Django's default {} — which is what made pupa's CLI KeyError (#216). A real
# config quiets chatty scrape/HTTP libraries and stamps the pipeline run_key onto
# logger output via the contextvars filter. The filter lives in a models-free
# module (seattle_app.logging_filters) because dictConfig runs before the app
# registry loads. Per-line timestamps on the flat cron log come from `ts`
# (moreutils) in scheduler-crontab, so the formatter omits asctime to avoid
# double-stamping.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "pipeline_run_key": {
            "()": "seattle_app.logging_filters.PipelineRunKeyFilter",
        },
        # Masks anything email-shaped in log output — subscriber emails
        # (#231) must never reach logs. Digest code paths log subscriber
        # ids; this filter is the backstop for third-party/library lines.
        "redact_emails": {
            "()": "seattle_app.logging_filters.EmailRedactionFilter",
        },
    },
    "formatters": {
        "tagged": {"format": "[%(run_key)s] %(levelname)s %(name)s: %(message)s"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "filters": ["pipeline_run_key", "redact_emails"],
            "formatter": "tagged",
        },
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        # Noisy scrape / HTTP libraries — keep them at WARNING.
        "scrapelib": {"level": "WARNING"},
        "urllib3": {"level": "WARNING"},
        "requests": {"level": "WARNING"},
        "boto": {"level": "WARNING"},
        "botocore": {"level": "WARNING"},
        "s3transfer": {"level": "WARNING"},
    },
}

# Content Security Policy settings
# In development, allow localhost resources
if DEBUG:
    CSP_DEFAULT_SRC = ("'self'", "localhost:3000", "localhost:8000")
    CSP_SCRIPT_SRC = ("'self'", "'unsafe-inline'", "'unsafe-eval'", "localhost:3000")
    CSP_STYLE_SRC = ("'self'", "'unsafe-inline'", "localhost:3000")
    CSP_IMG_SRC = ("'self'", "data:", "localhost:3000", "localhost:8000")
    CSP_FONT_SRC = ("'self'", "data:", "localhost:3000")
    CSP_CONNECT_SRC = ("'self'", "localhost:3000", "localhost:8000", "ws://localhost:3000")
else:
    # Production CSP. `img-src` allows seattle.gov because rep banner
    # photos (RepDetail) load from
    # `https://www.seattle.gov/images/Council/Members/CouncilmemberBanners/...`
    # — we hotlink rather than mirror so updates on seattle.gov flow
    # through automatically. data: stays for the inline SVG icons
    # bundled by lucide-react.
    CSP_DEFAULT_SRC = ("'self'",)
    CSP_SCRIPT_SRC = ("'self'",)
    CSP_STYLE_SRC = ("'self'",)
    CSP_IMG_SRC = ("'self'", "data:", "https://www.seattle.gov")
    CSP_FONT_SRC = ("'self'",)

# CORS settings for API
if DEBUG:
    # In development, allow React dev server
    CORS_ALLOWED_ORIGINS = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
else:
    # In production, the SPA is served same-origin by Django so CORS
    # isn't strictly needed. Empty list is valid; comma-split-and-
    # filter mirrors the CSRF_TRUSTED_ORIGINS pattern so a missing
    # env var doesn't leave a `[""]` that fails the corsheaders
    # system check.
    CORS_ALLOWED_ORIGINS = [
        o for o in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",") if o
    ]

CORS_ALLOW_CREDENTIALS = True
