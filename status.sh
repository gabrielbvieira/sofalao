#!/bin/bash

echo "Sofalao - Status"
echo "================"

if pgrep -f "gunicorn.*sofalao" > /dev/null; then
    echo "Status: RODANDO"

    echo "PIDs:"
    pgrep -f "gunicorn.*sofalao" | while read pid; do
        echo "   - $pid"
    done

    echo "Uso de recursos:"
    ps -o pid,ppid,pcpu,pmem,etime,cmd -p $(pgrep -f "gunicorn.*sofalao" | tr '\n' ',' | sed 's/,$//')

    echo "Teste de conectividade:"
    if curl -s -f http://localhost:8040/healthz > /dev/null; then
        echo "   Servidor respondendo na porta 8040"
    else
        echo "   Servidor nao esta respondendo"
    fi

else
    echo "Status: PARADO"
fi

if [ -f "logs/gunicorn_error.log" ]; then
    echo ""
    echo "Ultimas 5 linhas do log de erro:"
    tail -5 logs/gunicorn_error.log
fi
