#!/usr/bin/env bash

# Run Celery as the DesignSafe Community Account
celery -A designsafe beat -l info --pidfile= --schedule=/tmp/celerybeat-schedule &
celery -A designsafe worker -l info --autoscale=15,5 -Q indexing,files -n designsafe_worker01 &
celery -A designsafe worker -l info --autoscale=10,3 -Q default,api -n designsafe_worker02