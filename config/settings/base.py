"""Base Django settings shared by every environment.

Configuration is 12-factor: all environment-specific values are read from
environment variables (optionally via a local ``.env`` file) using
``django-environ``. Sensible development defaults are provided, but production
requires explicit secrets and a PostgreSQL ``DATABASE_URL``.
"""

from __future__ import annotations

from pathlib import Path

import environ

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# base.py -> settings/ -> config/ -> <project root>
BASE_DIR = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    DJANGO_ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    DJANGO_CSRF_TRUSTED_ORIGINS=(list, []),
    DJANGO_CORS_ALLOWED_ORIGINS=(list, []),
    DJANGO_LOG_LEVEL=(str, "INFO"),
    DJANGO_LOG_REDACT_HEADERS=(list, ["Authorization", "Cookie", "X-API-Key"]),
    DJANGO_LOG_FORMATTER=(str, "verbose"),
    DJANGO_DB_CONN_MAX_AGE=(int, 60),
    DJANGO_STATIC_ROOT=(str, str(BASE_DIR / "staticfiles")),
    DJANGO_MEDIA_ROOT=(str, str(BASE_DIR / "media")),
    CELERY_TASK_ALWAYS_EAGER=(bool, False),
    CELERY_TASK_TIME_LIMIT=(int, 300),
    CELERY_TASK_SOFT_TIME_LIMIT=(int, 240),
    CELERY_TASK_DEFAULT_RETRY_DELAY=(int, 10),
    CELERY_TASK_MAX_RETRIES=(int, 3),
    CELERY_TASK_ACKS_LATE=(bool, True),
    CELERY_TASK_REJECT_ON_WORKER_LOST=(bool, True),
    CELERY_TASK_PREFETCH_MULTIPLIER=(int, 1),
    CELERY_WORKER_CONCURRENCY=(int, 2),
    CELERY_RESULT_EXPIRES=(int, 86400),
    API_DOCS_ENABLED=(bool, True),
    MAX_UPLOAD_SIZE_BYTES=(int, 10 * 1024 * 1024),  # 10 MiB
    # --- MetaTrader 5 / market data (Phase 2) ---
    MT5_PATH=(str, ""),
    MT5_LOGIN=(int, 0),
    MT5_PASSWORD=(str, ""),
    MT5_SERVER=(str, ""),
    MT5_TIMEOUT_MS=(int, 60000),
    MT5_PORTABLE=(bool, False),
    MT5_MAX_RETRIES=(int, 3),
    MT5_RETRY_BACKOFF_SECONDS=(float, 2.0),
    MT5_RETRY_BACKOFF_MAX_SECONDS=(float, 30.0),
    MT5_FEED_DELAY_SECONDS=(int, 5),
    MT5_MAX_CANDLE_RANGE=(int, 5000),
    MT5_MAX_TICK_RANGE=(int, 10000),
    MT5_STALE_TICK_SECONDS=(int, 120),
    MT5_TICK_RETENTION_DAYS=(int, 7),
    MT5_WORKER_TOKEN=(str, ""),
    MT5_WORKER_POLL_INTERVAL_SECONDS=(int, 15),
    MT5_WORKER_HEARTBEAT_TTL_SECONDS=(int, 90),
    MT5_SYNC_SYMBOLS=(list, ["EURUSD"]),
    MT5_SYNC_TIMEFRAMES=(list, ["M1", "M5"]),
    MARKET_READ_THROTTLE=(str, "240/minute"),
    MARKET_INGEST_THROTTLE=(str, "1200/minute"),
    # --- Chart vision / vision LLM (Phase 3) ---
    VISION_LLM_PROVIDER=(str, "mock"),
    VISION_LLM_MODEL=(str, ""),
    VISION_LLM_API_KEY=(str, ""),
    VISION_LLM_BASE_URL=(str, ""),
    VISION_LLM_TIMEOUT_SECONDS=(int, 60),
    VISION_LLM_MAX_RETRIES=(int, 2),
    VISION_LLM_BACKOFF_SECONDS=(float, 1.5),
    VISION_LLM_MAX_TOKENS=(int, 2048),
    VISION_LLM_TEMPERATURE=(float, 0.0),
    VISION_MAX_UPLOAD_BYTES=(int, 8 * 1024 * 1024),
    VISION_MIN_WIDTH=(int, 200),
    VISION_MIN_HEIGHT=(int, 100),
    VISION_MAX_WIDTH=(int, 8000),
    VISION_MAX_HEIGHT=(int, 8000),
    VISION_MAX_PIXELS=(int, 40_000_000),
    VISION_PREPROCESS_MAX_DIMENSION=(int, 2000),
    VISION_SCREENSHOT_ROOT=(str, ""),
    VISION_SCREENSHOT_RETENTION_DAYS=(int, 30),
    VISION_ANALYSIS_MAX_ATTEMPTS=(int, 3),
    VISION_UPLOAD_THROTTLE=(str, "30/minute"),
    VISION_READ_THROTTLE=(str, "240/minute"),
    # --- Reasoning LLM (Phase 8) ---
    REASONING_LLM_PROVIDER=(str, "mock"),
    REASONING_LLM_MODEL=(str, ""),
    REASONING_LLM_API_KEY=(str, ""),
    REASONING_LLM_BASE_URL=(str, ""),
    REASONING_LLM_TIMEOUT_SECONDS=(int, 30),
    REASONING_LLM_MAX_RETRIES=(int, 2),
    REASONING_LLM_MAX_TOKENS=(int, 512),
    REASONING_LLM_TEMPERATURE=(float, 0.1),
    REASONING_FALLBACK_ON_FAILURE=(bool, True),
    ASSISTANT_UPLOAD_THROTTLE=(str, "30/minute"),
    ASSISTANT_READ_THROTTLE=(str, "240/minute"),
    JOURNAL_THROTTLE=(str, "60/min"),
    DASHBOARD_THROTTLE=(str, "120/min"),
    # --- Market synchronization (Phase 4) ---
    SYNC_MAX_CANDLES=(int, 200),
    SYNC_MIN_OVERLAP_CANDLES=(int, 3),
    SYNC_DIRECTION_MATCH_MIN=(float, 0.75),
    SYNC_DIRECTION_PARTIAL_MIN=(float, 0.5),
    SYNC_DOJI_BODY_RATIO_MAX=(float, 0.12),
    SYNC_BODY_BAND_SMALL_MAX=(float, 0.25),
    SYNC_BODY_BAND_MEDIUM_MAX=(float, 0.60),
    SYNC_WICK_BAND_SMALL_MAX=(float, 0.20),
    SYNC_WICK_BAND_MEDIUM_MAX=(float, 0.45),
    SYNC_BODY_RATIO_TOLERANCE=(float, 0.30),
    SYNC_WICK_RATIO_TOLERANCE=(float, 0.35),
    SYNC_SCREENSHOT_MAX_AGE_SECONDS=(int, 3600),
    SYNC_MT5_MAX_CANDLE_AGE_SECONDS=(int, 900),
    SYNC_TIMESTAMP_TOLERANCE_SECONDS=(int, 5),
    SYNC_MIN_STRUCTURE_OVERLAP=(int, 5),
    SYNC_STRUCTURE_AGREE_MIN=(float, 0.70),
    SYNC_SWING_LOOKBACK=(int, 2),
    SYNC_DEFAULT_TZ_OFFSET_MINUTES=(int, 0),
    SYNC_CONFIG_VERSION=(str, "1.0"),
    SYNC_VERIFY_THROTTLE=(str, "60/minute"),
    SYNC_READ_THROTTLE=(str, "240/minute"),
    # --- Price-action knowledge engine (Phase 5) ---
    PA_SWING_LOOKBACK=(int, 2),
    PA_MIN_SWINGS_FOR_TREND=(int, 2),
    PA_EQUAL_LEVEL_TOLERANCE=(float, 0.0005),
    PA_CONSOLIDATION_MAX_WIDTH=(float, 0.0025),
    PA_CONSOLIDATION_MIN_CANDLES=(int, 5),
    PA_ZONE_TOLERANCE=(float, 0.0015),
    PA_ZONE_MIN_TOUCHES=(int, 2),
    PA_REJECTION_WICK_MIN=(float, 0.5),
    PA_BREAKOUT_CLOSE_MARGIN=(float, 0.0005),
    PA_RETEST_WINDOW=(int, 5),
    PA_DOJI_BODY_RATIO_MAX=(float, 0.12),
    PA_SMALL_BODY_RATIO_MAX=(float, 0.30),
    PA_STRONG_BODY_RATIO_MIN=(float, 0.60),
    PA_STRONG_RANGE_MULTIPLE=(float, 1.2),
    PA_EXTENDED_RUN_LENGTH=(int, 3),
    PA_SEQUENCE_SIGNATURE_LENGTH=(int, 3),
    PA_SIMILAR_SEQUENCE_MIN_SAMPLES=(int, 3),
    PA_SIMILAR_SEQUENCE_MIN_SIMILARITY=(float, 1.0),
    PA_SWEEP_MIN_PENETRATION=(float, 0.0),
    PA_OPENING_GAP_MIN_SIZE=(float, 0.0),
    PA_HIGH_VOLUME_MULTIPLE=(float, 1.5),
    PA_LOW_VOLUME_MULTIPLE=(float, 0.6),
    PA_NARROW_RANGE_MULTIPLE=(float, 0.7),
    PA_WIDE_RANGE_MULTIPLE=(float, 1.3),
    PA_VOLUME_LOOKBACK=(int, 20),
    PA_HIGH_VOLATILITY_MULTIPLE=(float, 1.5),
    PA_LOW_VOLATILITY_MULTIPLE=(float, 0.6),
    PA_MAX_CANDLES=(int, 500),
    PA_MIN_CANDLES=(int, 3),
    PA_KNOWLEDGE_VERSION=(str, "1.0"),
)

_env_file = BASE_DIR / ".env"
if _env_file.exists():
    env.read_env(str(_env_file))

# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------
SECRET_KEY = env(
    "DJANGO_SECRET_KEY",
    default="django-insecure-development-only-key-change-me",
)
DEBUG = env("DJANGO_DEBUG")
ALLOWED_HOSTS = env("DJANGO_ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env("DJANGO_CSRF_TRUSTED_ORIGINS")

# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework.authtoken",
    "corsheaders",
    "drf_spectacular",
    "channels",
]

LOCAL_APPS = [
    "apps.core",
    "apps.accounts",
    "apps.dashboard",
    "apps.api",
    "apps.market_data",
    "apps.chart_vision",
    "apps.market_sync",
    "apps.price_action",
    "apps.strategy_knowledge",
    "apps.book_strategies",
    "apps.strategy_engine",
    "apps.research",
    "apps.ai_assistant",
    "apps.trading_journal",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.RequestIDMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.app_context",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
# Production requires a PostgreSQL DATABASE_URL, e.g.
#   postgres://user:pass@host:5432/nazbeen_academy
#
# An *empty* DATABASE_URL (the documented "leave unset for SQLite" pattern in
# .env) must behave like an unset variable: django-environ otherwise parses the
# empty string into an engine-less config and Django falls back to the dummy
# backend. Normalise empty -> SQLite default (production still enforces a real
# URL in prod.py).
_DEFAULT_DATABASE_URL = f"sqlite:///{BASE_DIR.as_posix()}/db.sqlite3"
DATABASE_URL = env("DATABASE_URL", default=_DEFAULT_DATABASE_URL) or _DEFAULT_DATABASE_URL
DATABASES = {
    "default": env.db_url_config(DATABASE_URL),
}
DATABASES["default"]["CONN_MAX_AGE"] = env("DJANGO_DB_CONN_MAX_AGE")
DATABASES["default"].setdefault("ATOMIC_REQUESTS", False)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "dashboard:index"
LOGOUT_REDIRECT_URL = "home"

# ---------------------------------------------------------------------------
# Internationalization
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static and media files
# ---------------------------------------------------------------------------
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = Path(env("DJANGO_STATIC_ROOT"))

MEDIA_URL = "media/"
MEDIA_ROOT = Path(env("DJANGO_MEDIA_ROOT"))

# Django 4.2+ storage configuration (STATICFILES_STORAGE was removed in 5.1).
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# ---------------------------------------------------------------------------
# Security-related defaults (tightened further in prod.py)
# ---------------------------------------------------------------------------
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False  # HTMX reads the CSRF token from the cookie.
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
DATA_UPLOAD_MAX_MEMORY_SIZE = env("MAX_UPLOAD_SIZE_BYTES")
FILE_UPLOAD_MAX_MEMORY_SIZE = env("MAX_UPLOAD_SIZE_BYTES")

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = env("DJANGO_CORS_ALLOWED_ORIGINS")
CORS_ALLOW_CREDENTIALS = True

# ---------------------------------------------------------------------------
# REST framework
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.TokenAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "apps.api.pagination.StandardResultsSetPagination",
    "PAGE_SIZE": 25,
    "DEFAULT_FILTER_BACKENDS": [
        "rest_framework.filters.OrderingFilter",
        "rest_framework.filters.SearchFilter",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
    "EXCEPTION_HANDLER": "apps.api.exceptions.api_exception_handler",
    "DEFAULT_THROTTLE_RATES": {
        "market_read": env("MARKET_READ_THROTTLE"),
        "market_ingest": env("MARKET_INGEST_THROTTLE"),
        "vision_upload": env("VISION_UPLOAD_THROTTLE"),
        "vision_read": env("VISION_READ_THROTTLE"),
        "sync_verify": env("SYNC_VERIFY_THROTTLE"),
        "sync_read": env("SYNC_READ_THROTTLE"),
        "assistant_upload": env("ASSISTANT_UPLOAD_THROTTLE"),
        "assistant_read": env("ASSISTANT_READ_THROTTLE"),
        "journal": env("JOURNAL_THROTTLE"),
        "dashboard": env("DASHBOARD_THROTTLE"),
    },
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Nazbeen Academy Binary Ai Asisstance API",
    "DESCRIPTION": (
        "Analysis and research API. This application never places trades. "
        "Probabilities are only reported by validated, calibrated models."
    ),
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
}

API_DOCS_ENABLED = env("API_DOCS_ENABLED")

# ---------------------------------------------------------------------------
# MetaTrader 5 / market data (Phase 2)
# ---------------------------------------------------------------------------
# Credentials are read from the environment only. A connection *profile* in the
# database stores non-secret identifiers (server, login, terminal path) and a
# ``credential_ref`` naming the secret; the password itself is never persisted.
MT5_TERMINAL_PATH = env("MT5_PATH")
MT5_LOGIN = env("MT5_LOGIN")
MT5_PASSWORD = env("MT5_PASSWORD")
MT5_SERVER = env("MT5_SERVER")
MT5_TIMEOUT_MS = env("MT5_TIMEOUT_MS")
MT5_PORTABLE = env("MT5_PORTABLE")
MT5_MAX_RETRIES = env("MT5_MAX_RETRIES")
MT5_RETRY_BACKOFF_SECONDS = env("MT5_RETRY_BACKOFF_SECONDS")
MT5_RETRY_BACKOFF_MAX_SECONDS = env("MT5_RETRY_BACKOFF_MAX_SECONDS")
MT5_FEED_DELAY_SECONDS = env("MT5_FEED_DELAY_SECONDS")
MT5_MAX_CANDLE_RANGE = env("MT5_MAX_CANDLE_RANGE")
MT5_MAX_TICK_RANGE = env("MT5_MAX_TICK_RANGE")
MT5_STALE_TICK_SECONDS = env("MT5_STALE_TICK_SECONDS")
MT5_TICK_RETENTION_DAYS = env("MT5_TICK_RETENTION_DAYS")

# Worker <-> server authentication. When unset, worker ingest endpoints are
# disabled (they return 403), which is the safe default.
MT5_WORKER_TOKEN = env("MT5_WORKER_TOKEN")
MT5_WORKER_POLL_INTERVAL_SECONDS = env("MT5_WORKER_POLL_INTERVAL_SECONDS")
MT5_WORKER_HEARTBEAT_TTL_SECONDS = env("MT5_WORKER_HEARTBEAT_TTL_SECONDS")

# Default instruments/timeframes collected by the worker.
MT5_CANDLE_SYNC_SYMBOLS = env("MT5_SYNC_SYMBOLS")
MT5_CANDLE_SYNC_TIMEFRAMES = env("MT5_SYNC_TIMEFRAMES")

# ---------------------------------------------------------------------------
# Chart vision / vision LLM (Phase 3)
# ---------------------------------------------------------------------------
# Provider credentials are read from the environment only and are never stored
# in the database or logged. ``VISION_LLM_PROVIDER`` selects the adapter:
#   * ``mock``   - deterministic development stub (no network, no credentials).
#   * ``openai`` - OpenAI-compatible ``/chat/completions`` vision endpoint.
#   * ``custom`` - generic OpenAI-compatible base URL (same protocol as openai).
# Provider errors never produce fabricated analysis results.
VISION_LLM_PROVIDER = env("VISION_LLM_PROVIDER")
VISION_LLM_MODEL = env("VISION_LLM_MODEL")
VISION_LLM_API_KEY = env("VISION_LLM_API_KEY")
VISION_LLM_BASE_URL = env("VISION_LLM_BASE_URL")
VISION_LLM_TIMEOUT_SECONDS = env("VISION_LLM_TIMEOUT_SECONDS")
VISION_LLM_MAX_RETRIES = env("VISION_LLM_MAX_RETRIES")
VISION_LLM_BACKOFF_SECONDS = env("VISION_LLM_BACKOFF_SECONDS")
VISION_LLM_MAX_TOKENS = env("VISION_LLM_MAX_TOKENS")
VISION_LLM_TEMPERATURE = env("VISION_LLM_TEMPERATURE")

# Reasoning LLM (Phase 8). The reasoning model explains results produced by the
# deterministic and statistical engines; it never overrides their decisions.
# Credentials are read from the environment only.
REASONING_LLM_PROVIDER = env("REASONING_LLM_PROVIDER")
REASONING_LLM_MODEL = env("REASONING_LLM_MODEL")
REASONING_LLM_API_KEY = env("REASONING_LLM_API_KEY")
REASONING_LLM_BASE_URL = env("REASONING_LLM_BASE_URL")
REASONING_LLM_TIMEOUT_SECONDS = env("REASONING_LLM_TIMEOUT_SECONDS")
REASONING_LLM_MAX_RETRIES = env("REASONING_LLM_MAX_RETRIES")
REASONING_LLM_MAX_TOKENS = env("REASONING_LLM_MAX_TOKENS")
REASONING_LLM_TEMPERATURE = env("REASONING_LLM_TEMPERATURE")
REASONING_FALLBACK_ON_FAILURE = env("REASONING_FALLBACK_ON_FAILURE")

# Upload/decoding bounds (defence against decompression bombs and oversized
# payloads). ``VISION_MAX_PIXELS`` maps to Pillow's decompression-bomb guard.
VISION_MAX_UPLOAD_BYTES = env("VISION_MAX_UPLOAD_BYTES")
VISION_MIN_WIDTH = env("VISION_MIN_WIDTH")
VISION_MIN_HEIGHT = env("VISION_MIN_HEIGHT")
VISION_MAX_WIDTH = env("VISION_MAX_WIDTH")
VISION_MAX_HEIGHT = env("VISION_MAX_HEIGHT")
VISION_MAX_PIXELS = env("VISION_MAX_PIXELS")
VISION_PREPROCESS_MAX_DIMENSION = env("VISION_PREPROCESS_MAX_DIMENSION")

# Screenshots are stored **privately** (outside MEDIA_URL) and served only
# through an authenticated, ownership-checked API view. Retention controls how
# long originals are kept before a purge task may delete them.
VISION_SCREENSHOT_ROOT = Path(
    env("VISION_SCREENSHOT_ROOT") or (BASE_DIR / "private_media" / "screenshots")
)
VISION_SCREENSHOT_RETENTION_DAYS = env("VISION_SCREENSHOT_RETENTION_DAYS")
VISION_ANALYSIS_MAX_ATTEMPTS = env("VISION_ANALYSIS_MAX_ATTEMPTS")

# ---------------------------------------------------------------------------
# Market synchronization (Phase 4)
# ---------------------------------------------------------------------------
# Comparison thresholds and freshness policies. These are pragmatic defaults for
# a qualitative/relative comparison, configurable per deployment. They are NOT
# scientifically validated market parameters. See
# ``apps.market_sync.services.config.SyncConfig`` for the full list.
SYNC_MAX_CANDLES = env("SYNC_MAX_CANDLES")
SYNC_MIN_OVERLAP_CANDLES = env("SYNC_MIN_OVERLAP_CANDLES")
SYNC_DIRECTION_MATCH_MIN = env("SYNC_DIRECTION_MATCH_MIN")
SYNC_DIRECTION_PARTIAL_MIN = env("SYNC_DIRECTION_PARTIAL_MIN")
SYNC_DOJI_BODY_RATIO_MAX = env("SYNC_DOJI_BODY_RATIO_MAX")
SYNC_BODY_BAND_SMALL_MAX = env("SYNC_BODY_BAND_SMALL_MAX")
SYNC_BODY_BAND_MEDIUM_MAX = env("SYNC_BODY_BAND_MEDIUM_MAX")
SYNC_WICK_BAND_SMALL_MAX = env("SYNC_WICK_BAND_SMALL_MAX")
SYNC_WICK_BAND_MEDIUM_MAX = env("SYNC_WICK_BAND_MEDIUM_MAX")
SYNC_BODY_RATIO_TOLERANCE = env("SYNC_BODY_RATIO_TOLERANCE")
SYNC_WICK_RATIO_TOLERANCE = env("SYNC_WICK_RATIO_TOLERANCE")
SYNC_SCREENSHOT_MAX_AGE_SECONDS = env("SYNC_SCREENSHOT_MAX_AGE_SECONDS")
SYNC_MT5_MAX_CANDLE_AGE_SECONDS = env("SYNC_MT5_MAX_CANDLE_AGE_SECONDS")
SYNC_TIMESTAMP_TOLERANCE_SECONDS = env("SYNC_TIMESTAMP_TOLERANCE_SECONDS")
SYNC_MIN_STRUCTURE_OVERLAP = env("SYNC_MIN_STRUCTURE_OVERLAP")
SYNC_STRUCTURE_AGREE_MIN = env("SYNC_STRUCTURE_AGREE_MIN")
SYNC_SWING_LOOKBACK = env("SYNC_SWING_LOOKBACK")
SYNC_DEFAULT_TZ_OFFSET_MINUTES = env("SYNC_DEFAULT_TZ_OFFSET_MINUTES")
SYNC_CONFIG_VERSION = env("SYNC_CONFIG_VERSION")

# ---------------------------------------------------------------------------
# Price-action knowledge engine (Phase 5)
# ---------------------------------------------------------------------------
# Detection thresholds for the deterministic price-action engine. These are
# pragmatic defaults; they are NOT validated market parameters and carry no
# predictive claim. See ``apps.price_action.services.config.PriceActionConfig``.
PA_SWING_LOOKBACK = env("PA_SWING_LOOKBACK")
PA_MIN_SWINGS_FOR_TREND = env("PA_MIN_SWINGS_FOR_TREND")
PA_EQUAL_LEVEL_TOLERANCE = env("PA_EQUAL_LEVEL_TOLERANCE")
PA_CONSOLIDATION_MAX_WIDTH = env("PA_CONSOLIDATION_MAX_WIDTH")
PA_CONSOLIDATION_MIN_CANDLES = env("PA_CONSOLIDATION_MIN_CANDLES")
PA_ZONE_TOLERANCE = env("PA_ZONE_TOLERANCE")
PA_ZONE_MIN_TOUCHES = env("PA_ZONE_MIN_TOUCHES")
PA_REJECTION_WICK_MIN = env("PA_REJECTION_WICK_MIN")
PA_BREAKOUT_CLOSE_MARGIN = env("PA_BREAKOUT_CLOSE_MARGIN")
PA_RETEST_WINDOW = env("PA_RETEST_WINDOW")
PA_DOJI_BODY_RATIO_MAX = env("PA_DOJI_BODY_RATIO_MAX")
PA_SMALL_BODY_RATIO_MAX = env("PA_SMALL_BODY_RATIO_MAX")
PA_STRONG_BODY_RATIO_MIN = env("PA_STRONG_BODY_RATIO_MIN")
PA_STRONG_RANGE_MULTIPLE = env("PA_STRONG_RANGE_MULTIPLE")
PA_EXTENDED_RUN_LENGTH = env("PA_EXTENDED_RUN_LENGTH")
PA_SEQUENCE_SIGNATURE_LENGTH = env("PA_SEQUENCE_SIGNATURE_LENGTH")
PA_SIMILAR_SEQUENCE_MIN_SAMPLES = env("PA_SIMILAR_SEQUENCE_MIN_SAMPLES")
PA_SIMILAR_SEQUENCE_MIN_SIMILARITY = env("PA_SIMILAR_SEQUENCE_MIN_SIMILARITY")
PA_SWEEP_MIN_PENETRATION = env("PA_SWEEP_MIN_PENETRATION")
PA_OPENING_GAP_MIN_SIZE = env("PA_OPENING_GAP_MIN_SIZE")
PA_HIGH_VOLUME_MULTIPLE = env("PA_HIGH_VOLUME_MULTIPLE")
PA_LOW_VOLUME_MULTIPLE = env("PA_LOW_VOLUME_MULTIPLE")
PA_NARROW_RANGE_MULTIPLE = env("PA_NARROW_RANGE_MULTIPLE")
PA_WIDE_RANGE_MULTIPLE = env("PA_WIDE_RANGE_MULTIPLE")
PA_VOLUME_LOOKBACK = env("PA_VOLUME_LOOKBACK")
PA_HIGH_VOLATILITY_MULTIPLE = env("PA_HIGH_VOLATILITY_MULTIPLE")
PA_LOW_VOLATILITY_MULTIPLE = env("PA_LOW_VOLATILITY_MULTIPLE")
PA_MAX_CANDLES = env("PA_MAX_CANDLES")
PA_MIN_CANDLES = env("PA_MIN_CANDLES")
PA_KNOWLEDGE_VERSION = env("PA_KNOWLEDGE_VERSION")

# ---------------------------------------------------------------------------
# Celery
# ---------------------------------------------------------------------------
REDIS_URL = env("REDIS_URL", default="")

if REDIS_URL:
    CELERY_BROKER_URL = REDIS_URL
    CELERY_RESULT_BACKEND = REDIS_URL
else:  # pragma: no cover - development fallback
    CELERY_BROKER_URL = "memory://"
    CELERY_RESULT_BACKEND = "cache+memory://"

CELERY_TASK_ALWAYS_EAGER = env("CELERY_TASK_ALWAYS_EAGER")
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TASK_TIME_LIMIT = env("CELERY_TASK_TIME_LIMIT")
CELERY_TASK_SOFT_TIME_LIMIT = env("CELERY_TASK_SOFT_TIME_LIMIT")
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TIMEZONE = TIME_ZONE

# --- Reliability (Phase 10, Step 6) --------------------------------------
# Retry transient failures (e.g. a short DB outage) with a bounded budget
# instead of silently dropping the job.
CELERY_TASK_DEFAULT_RETRY_DELAY = env("CELERY_TASK_DEFAULT_RETRY_DELAY")
CELERY_TASK_MAX_RETRIES = env("CELERY_TASK_MAX_RETRIES")
# Redeliver work if a worker dies mid-task. Tasks are idempotent (keyed by
# primary key and guarded by status transitions), so re-running is safe.
CELERY_TASK_ACKS_LATE = env("CELERY_TASK_ACKS_LATE")
CELERY_TASK_REJECT_ON_WORKER_LOST = env("CELERY_TASK_REJECT_ON_WORKER_LOST")
# Bound per-worker memory when long screenshot/backtest jobs are queued.
CELERY_TASK_PREFETCH_MULTIPLIER = env("CELERY_TASK_PREFETCH_MULTIPLIER")
CELERY_WORKER_CONCURRENCY = env("CELERY_WORKER_CONCURRENCY")
# Keep Redis from growing without bound; results are rebuildable from the DB.
CELERY_RESULT_EXPIRES = env("CELERY_RESULT_EXPIRES")
# A task that exceeds its time limit is failed, not retried indefinitely.
CELERY_TASK_ANNOTATIONS = {
    "*": {"max_retries": env("CELERY_TASK_MAX_RETRIES")},
}

# Queue isolation: a burst of screenshot analysis must not starve market-data
# ingestion, and a long backtest must not block either. Unmatched task names
# fall through to the default queue (market-data tasks are the highest volume
# and latency sensitive, so they get an explicit queue of their own).
CELERY_TASK_ROUTES = {
    "chart_vision.*": {"queue": "vision"},
    "research.*": {"queue": "backtest"},
    "market_data.*": {"queue": "market"},
    "market_sync.*": {"queue": "market"},
    "ai_assistant.*": {"queue": "assistant"},
}

# --- Periodic maintenance (Phase 10) --------------------------------------
# Without a beat schedule the retention purges were defined but never
# invoked, so screenshots and ticks would accumulate forever. A dedicated
# `beat` service runs these; they are idempotent (delete-what-is-expired), so
# an overlapping or redelivered schedule is harmless.
CELERY_BEAT_SCHEDULE = {
    "market-data.purge-ticks-daily": {
        "task": "market_data.purge_ticks",
        "schedule": 60 * 60 * 24,  # 24h
        "options": {"queue": "market"},
    },
    "chart-vision.purge-screenshots-daily": {
        "task": "chart_vision.purge_screenshots",
        "schedule": 60 * 60 * 24,  # 24h
        "options": {"queue": "vision"},
    },
    "core.health-probe-minutely": {
        "task": "core.health_probe",
        "schedule": 60,  # 1min
        "options": {"queue": "market"},
    },
}

# ---------------------------------------------------------------------------
# Channels
# ---------------------------------------------------------------------------
if REDIS_URL:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {"hosts": [REDIS_URL]},
        }
    }
else:  # pragma: no cover - development fallback
    CHANNEL_LAYERS = {
        "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"},
    }

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
        }
    }
else:  # pragma: no cover - development fallback
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "nazbeen-academy",
        }
    }

# ---------------------------------------------------------------------------
# Logging (structured, request-correlated)
# ---------------------------------------------------------------------------
#: Header names whose values are masked from every log record (see
#: ``apps.core.logging.RedactHeadersFilter``). Comma-separated in ``.env``.
DJANGO_LOG_REDACT_HEADERS = env("DJANGO_LOG_REDACT_HEADERS")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "request_id": {"()": "apps.core.logging.RequestIDFilter"},
        "redact": {
            "()": "apps.core.logging.RedactHeadersFilter",
            "headers": DJANGO_LOG_REDACT_HEADERS,
        },
    },
    "formatters": {
        "verbose": {
            "()": "apps.core.logging.ConsoleFormatter",
        },
        "json": {
            "()": "apps.core.logging.JsonFormatter",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "filters": ["request_id", "redact"],
            "formatter": env("DJANGO_LOG_FORMATTER"),
        },
    },
    "root": {
        "handlers": ["console"],
        "level": env("DJANGO_LOG_LEVEL"),
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": env("DJANGO_LOG_LEVEL"),
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "apps": {
            "handlers": ["console"],
            "level": env("DJANGO_LOG_LEVEL"),
            "propagate": False,
        },
    },
}
