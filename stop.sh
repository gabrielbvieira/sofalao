#!/bin/bash

echo "Parando Sofalao..."

pkill -TERM -f "gunicorn.*sofalao" 2>/dev/null || true

sleep 3

sudo fuser -k 8040/tcp 2>/dev/null || true
pkill -KILL -f "gunicorn.*sofalao" 2>/dev/null || true

echo "Sofalao parado"
