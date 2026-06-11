import os

bind = "0.0.0.0:8040"
backlog = 2048

workers = 3
worker_class = "sync"
worker_connections = 100
timeout = 30
keepalive = 5

max_requests = 1000
max_requests_jitter = 100

preload_app = True

accesslog = "logs/gunicorn_access.log"
errorlog = "logs/gunicorn_error.log"
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'
capture_output = True

proc_name = "sofalao"

daemon = False
pidfile = "sofalao.pid"

graceful_timeout = 30

raw_env = [
    'FLASK_ENV=production',
    'PYTHONPATH=' + os.getcwd(),
    'PYTHONUNBUFFERED=1',
]
