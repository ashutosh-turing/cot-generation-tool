#!/bin/bash
echo "Restarting Gunicorn V2 server..."

pkill -f "gunicorn.*v2" || true
sleep 2

cd /home/cot/v2/eval
gunicorn coreproject.wsgi:application \
    --workers 3 \
    --bind unix:/run/gunicorn_v2.sock \
    --timeout 300 \
    --daemon \
    --pid /run/gunicorn_v2.pid \
    --access-logfile /var/log/gunicorn/v2_access.log \
    --error-logfile /var/log/gunicorn/v2_error.log

echo "Gunicorn V2 server restarted."
