#!/bin/bash
set -e

LOCKFILE="/tmp/sofalao.lock"

exec 200>"$LOCKFILE"
flock -n 200 || { echo "Ja existe uma instancia rodando"; exit 1; }

[ -d "venv" ] && source venv/bin/activate

mkdir -p logs

pkill -f "gunicorn.*sofalao" 2>/dev/null || true
sleep 2

nohup gunicorn -c gunicorn.conf.py wsgi:application > logs/gunicorn.log 2>&1 &

echo "Sofalao iniciado (Gunicorn, porta 8040)"
echo "Logs: logs/gunicorn.log"
