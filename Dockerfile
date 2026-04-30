FROM python:3.12 AS app
LABEL maintainer "DataMade <info@datamade.us>"

RUN apt-get update && \
	apt-get install -y --no-install-recommends --purge postgresql-client gdal-bin cron && \
	apt-get autoclean && \
	rm -rf /var/lib/apt/lists/* && \
	rm -rf /tmp/*

RUN mkdir /app
WORKDIR /app

COPY ./requirements.txt /app/requirements.txt
RUN pip install -r requirements.txt

COPY . /app
ENV DJANGO_SECRET_KEY 'foobar'
RUN python manage.py collectstatic --no-input

# Set up cron
COPY scheduler-crontab /etc/cron.d/scheduler-crontab
RUN chmod 0644 /etc/cron.d/scheduler-crontab && \
    crontab /etc/cron.d/scheduler-crontab && \
    mkdir -p /var/log/cron && \
    touch /var/log/cron/sync.log

ENTRYPOINT ["/app/docker-entrypoint.sh"]
