FROM public.ecr.aws/lambda/python:3.12

RUN microdnf install -y zip && microdnf clean all

WORKDIR /build/wayback_scraper
RUN mkdir -p /artifacts
RUN mkdir -p wayback_newegg_scrapy/wayback_newegg_scrapy

COPY src/lambda/wayback_scraper/requirements.txt /tmp/requirements.txt
RUN python -m pip install --upgrade pip && pip install -r /tmp/requirements.txt -t .

COPY src/lambda/wayback_scraper/lambda_function.py ./
COPY src/app/wayback_newegg_scrapy/scrapy.cfg ./wayback_newegg_scrapy/scrapy.cfg
COPY src/app/wayback_newegg_scrapy/setup_scheduler.py ./wayback_newegg_scrapy/setup_scheduler.py
COPY src/app/wayback_newegg_scrapy/wayback_newegg_scrapy ./wayback_newegg_scrapy/wayback_newegg_scrapy

RUN zip -r9 /artifacts/wayback_scraper.zip .