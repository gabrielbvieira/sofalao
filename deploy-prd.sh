#!/usr/bin/env bash
set -e

kubectl delete configmap sofalao-app sofalao-templates sofalao-static --ignore-not-found

kubectl create configmap sofalao-app \
    --from-file=app.py \
    --from-file=drive_backup.py \
    --from-file=sync.py \
    --from-file=wsgi.py \
    --from-file=requirements.txt \
    --from-file=forwards.json

kubectl create configmap sofalao-templates \
    --from-file=templates/

kubectl create configmap sofalao-static \
    --from-file=static/

kubectl apply -f k8s/
kubectl rollout restart deployment sofalao-prd-deployment
kubectl rollout status deployment sofalao-prd-deployment
