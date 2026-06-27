from pathlib import Path

import environ
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(DEBUG=(bool, False))
environ.Env.read_env(BASE_DIR / ".env")

# Дефолтный ключ годится ТОЛЬКО для локальной разработки. В проде (DEBUG=False)
# он запрещён — см. проверку ниже.
INSECURE_SECRET_KEY = "dev-insecure-key-change-me"
SECRET_KEY = env("SECRET_KEY", default=INSECURE_SECRET_KEY)
# По умолчанию False: безопаснее «упасть» на локальной забывчивости, чем
# случайно раскрыть трейсбэки и окружение в проде.
DEBUG = env("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

if not DEBUG and SECRET_KEY == INSECURE_SECRET_KEY:
    raise ImproperlyConfigured(
        "В продакшене (DEBUG=False) необходимо задать собственный SECRET_KEY "
        "через переменную окружения."
    )

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "django_q",
    "accounts",
    "documents",
    "search",
    "ingestion",
    "assistant",
    "practice",
    "bookmarks",
    "history",
    "notes",
    "glossary",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "history.middleware.RecordViewMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

if env("DATABASE_URL", default=""):
    DATABASES = {"default": env.db("DATABASE_URL")}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]

LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "Europe/Moscow"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Forward-compat для Django 6.0: модельные URLField по умолчанию будут
# подставлять схему 'https' вместо 'http'. Включаем новое поведение заранее,
# чтобы убрать RemovedInDjango60Warning (наши source_url — внешние https-ссылки).
FORMS_URLFIELD_ASSUME_HTTPS = True

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "document_list"
LOGOUT_REDIRECT_URL = "login"

# --- Приём данных по расписанию (План 3c) ---------------------------------
# Cron-выражение ежедневного обхода целей авто-приёма. По умолчанию 03:00.
SWEEP_CRON = env("SWEEP_CRON", default="0 3 * * *")
# Cron-выражение ежедневного обхода портала опубликования (обнаружение актов).
DISCOVERY_CRON = env("DISCOVERY_CRON", default="0 4 * * *")

# --- AI-ассистент (RAG) ---------------------------------------------------
# Ключ Claude API. Пусто (по умолчанию) → ассистент работает в режиме
# «только извлечение» (показывает релевантные статьи, без синтеза ответа).
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY", default="")

# django-q2: брокер задач прямо в Postgres (без Redis).
Q_CLUSTER = {
    "name": "lawiot",
    "orm": "default",  # использовать БД Django как брокер
    "workers": 2,
    "timeout": 300,  # сек на задачу; должен быть < retry
    "retry": 660,  # сек до повторной выдачи «зависшей» задачи
    "max_attempts": 1,  # обход идемпотентен — не копим повторы при сбое
    "catch_up": False,  # не «отыгрывать» пропущенные прогоны после простоя
    "label": "Django Q",
}

# --- Безопасность транспорта и cookie -------------------------------------
# В проде включаем HTTPS-only поведение. Локально (DEBUG=True) оставляем
# выключенным, иначе по http нельзя залогиниться (secure-cookie не отправится).
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31_536_000  # 1 год
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    # Доверяем заголовку прокси о схеме (за nginx/traefik) — иначе бесконечный
    # редирект. Включать, только если прокси действительно ставит этот заголовок.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
else:
    SECURE_SSL_REDIRECT = False
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False
    SECURE_HSTS_SECONDS = 0
    SECURE_HSTS_INCLUDE_SUBDOMAINS = False
    SECURE_HSTS_PRELOAD = False

# --- Логирование ----------------------------------------------------------
# Пишем в stdout (12-factor): сбор/ротацию делает рантайм (Docker/systemd),
# а не приложение. Наши подсистемы (ingestion/assistant/search) намеренно
# «деградируют, а не падают» — без логов проглоченные ошибки невидимы.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{asctime} {levelname} {name}: {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {"handlers": ["console"], "level": "INFO" if DEBUG else "WARNING"},
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "ingestion": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "assistant": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "search": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
