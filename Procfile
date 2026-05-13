web: playwright install-deps chromium && playwright install chromium && gunicorn server:app --bind 0.0.0.0:${PORT:-8000} --workers 2 --timeout 600 --worker-class gevent
