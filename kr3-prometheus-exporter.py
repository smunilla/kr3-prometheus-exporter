#!/usr/bin/env python3
""" A simple prometheus exporter for jenkins.

Scrapes jenkins on an interval and exposes metrics about builds.

It would be better for jenkins to offer a prometheus /metrics endpoint of its own.
"""

from datetime import datetime, timezone

import logging
import os
import time

import requests

from prometheus_client.core import (
    REGISTRY,
    CounterMetricFamily,
    GaugeMetricFamily,
    HistogramMetricFamily,
)
from prometheus_client import start_http_server

from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

retry_strategy = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
    method_whitelist=["HEAD", "GET", "OPTIONS"]
)
adapter = HTTPAdapter(max_retries=retry_strategy)
session = requests.Session()
session.mount("https://", adapter)
session.mount("http://", adapter)

START = None

DATAGREPPER_URL = "https://datagrepper.engineering.redhat.com"
TOPICS = ["VirtualTopic.external.github.continuous-prod.test-project"]

# In seconds
DURATION_BUCKETS = [
    10,
    30,
    60,  # 1 minute
    180,  # 3 minutes
    480,  # 8 minutes
    1200,  # 20 minutes
    3600,  # 1 hour
    7200,  # 2 hours
]

metrics = {}

def retrieve_recent_github_events(topic):
    params = dict(
        topic="/topic/{}".format(topic),
        delta="7200"
    )

    url = DATAGREPPER_URL + '/raw'
    response = session.get(url, params=params, timeout=30)
    response.raise_for_status()

    data = response.json()

    events = []

    for message in data.get("raw_messages"):
        events.append(message)

    return events


def get_event_fields(message):
    # TODO: some error checking on getting these so we don't just crash
    timestamp = message["headers"]["timestamp"]
    fullname = message["msg"]["repository"]["full_name"]
    commit_hash = message["msg"]["after"]
    correlation_id = message["headers"]["correlation-id"]

    return timestamp, fullname, commit_hash, correlation_id


def scrape():
    global START
    today = datetime.utcnow()
    START = datetime.combine(today, datetime.min.time())
    START = START.replace(tzinfo=timezone.utc)

    if START < startup:
        START = startup

    for topic in TOPICS:
        events = retrieve_recent_github_events(topic)

        for event in events:
            timestamp, fullname, commit_hash, correlation_id = get_event_fields(event)
            print("DEBUG: {} repo = {} commit hash = {}; correlation id = {}".format(timestamp, fullname, commit_hash, correlation_id))

        # TODO: Get all merge events in the tenant repo

        # TODO: For each correlation-id, calculate the time delta and add that to the metic

        # TODO: For each correlation-id that is more than 1 hour old, increment that 'failed to meet target' counter



class Expositor(object):
    """ Responsible for exposing metrics to prometheus """

    def collect(self):
        logging.info("Serving prometheus data")
        for key in sorted(metrics):
            yield metrics[key]


if __name__ == '__main__':
    now = datetime.utcnow()
    startup = now.replace(tzinfo=timezone.utc)

    logging.basicConfig(level=logging.DEBUG)
    for collector in list(REGISTRY._collector_to_names):
        REGISTRY.unregister(collector)
    REGISTRY.register(Expositor())

    # Popluate data before exposing over http
    scrape()
    start_http_server(8000)

    while True:
        time.sleep(int(os.environ.get('JENKINS_POLL_INTERVAL', '3')))
        scrape()
