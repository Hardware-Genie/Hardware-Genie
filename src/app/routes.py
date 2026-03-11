
from flask import Flask, render_template, jsonify, redirect, url_for, request
from app import app
import pandas as pd
import json

from app.forms import WebsiteToScrape
from app.wayback_newegg_scrapy.wayback_newegg_scrapy.spiders import wayback_newegg
from app.wayback_newegg_scrapy.wayback_newegg_scrapy.spiders.wayback_newegg import WaybackNeweggSpider
from app import tasks
import scrapy
from scrapy.crawler import CrawlerProcess

from app.forms import WebsiteToScrape
from app.wayback_newegg_scrapy.wayback_newegg_scrapy.spiders import wayback_newegg
from app.wayback_newegg_scrapy.wayback_newegg_scrapy.spiders.wayback_newegg import WaybackNeweggSpider
from app import tasks
import scrapy
from scrapy.crawler import CrawlerProcess

class csv_name_reader:
    def __init__(self, labels, price, date):
        self.labels = labels
        self.price = price
        self.date = date

    def from_csv(self, file_name, sort, ascending):
        csv_path = f'static/data/{file_name}.csv'
        df = pd.read_csv(csv_path)
        df = df.dropna(subset=['price'])
        df = df.sort_values(by=sort, ascending=ascending)
        self.labels = df['product_name'].tolist()
        self.price = df['price'].tolist()
        self.date = df['snapshot_date'].tolist()
        print(df['price'].median())

    def to_dict(self):
        return {
            'labels': self.labels,
            'price': self.price,
            'date': self.date,
        }


class csv_data_reader:
    def __init__(self, labels, price):
        self.labels = labels
        self.price = price

    def from_csv(self, file_name, sort, ascending):
        csv_path = f'static/data/{file_name}.csv'
        df = pd.read_csv(csv_path)
        df = df.dropna(subset=['price'])
        df = df.sort_values(by=sort, ascending=ascending)
        self.labels = df['name'].tolist()
        self.price = df['price'].tolist()
        print(df['price'].median())

    def to_dict(self):
        return {
            'labels': self.labels,
            'price': self.price,
        }

cpu_csv_reader = csv_data_reader([], [])
cpu_csv_reader.from_csv('July 23 2025/cpu', 'price', True)

memory_csv_reader = csv_data_reader([], [])
memory_csv_reader.from_csv('July 23 2025/memory', 'price', True)

gpu_csv_reader = csv_data_reader([], [])
gpu_csv_reader.from_csv('July 23 2025/video-card', 'price', True)

gpu_csv_reader_sort = csv_data_reader([], [])
gpu_csv_reader_sort.from_csv('July 23 2025/video-card', 'price', False)

storage_csv_reader = csv_data_reader([], [])
storage_csv_reader.from_csv('July 23 2025/internal-hard-drive', 'price', True)

mb_csv_reader = csv_data_reader([], [])
mb_csv_reader.from_csv('July 23 2025/motherboard', 'price', True)

psu_csv_reader = csv_data_reader([], [])
psu_csv_reader.from_csv('July 23 2025/power-supply', 'price', True)

@app.route('/')
@app.route('/index')
@app.route('/index.html')
def index():
    """Render the main index page."""
    return render_template('index.html')

@app.route('/scraper', methods=['GET', 'POST'])
def scraper():
    form = WebsiteToScrape()
    if form.validate_on_submit():
        # Process the form data
        name = form.name.data
        url = form.url.data

        # enqueue a Celery job rather than running inline
        
        task = tasks.crawl_spider.delay(name, url)
        # the request returns immediately; the worker will pick up the crawl

        print(f"Name: {name}, URL: {url}")
        return redirect(url_for('scraper_status', task_id=task.id))
    return render_template('scraper.html', form=form)

@app.route('/scraper/status/<task_id>')
def scraper_status(task_id):
    from celery.result import AsyncResult
    from app.tasks import celery
    result = AsyncResult(task_id, app=celery)
    return render_template('scraper_status.html', task_id=task_id, state=result.state, result=result.result, info=result.info)

@app.route('/memory', methods=['GET', 'POST'])
def memory_page():
    dict=memory_csv_reader.to_dict()
    labels = dict['labels']
    price = dict['price']
    return render_template('memory_page.html', labels=labels, price=price)

@app.route('/memorygraphs', methods=['GET', 'POST'])
def memory_graphs():
    dict=memory_csv_reader.to_dict()
    labels = dict['labels']
    price = dict['price']
    return render_template('memory_graphs.html', labels=labels, price=price)

@app.route('/gpu', methods=['GET', 'POST'])
def gpu_page():
    dict=gpu_csv_reader_sort.to_dict()
    labels = dict['labels']
    price = dict['price']
    return render_template('gpu_page.html', labels=labels, price=price)

@app.route('/gpugraphs', methods=['GET', 'POST'])
def gpu_graphs():
    dict=gpu_csv_reader.to_dict()
    labels = dict['labels']
    price = dict['price']
    return render_template('gpu_graphs.html', labels=labels, price=price)

@app.route('/cpu', methods=['GET', 'POST'])
def cpu_page():
    dict=cpu_csv_reader.to_dict()
    labels = dict['labels']
    price = dict['price']
    return render_template('cpu_page.html', labels=labels, price=price)

@app.route('/cpugraphs', methods=['GET', 'POST'])
def cpu_graphs():
    """Render the CPU page."""
    return render_template('cpu_graphs.html')

@app.route('/storage', methods=['GET', 'POST'])
def storage_page():
    dict=storage_csv_reader.to_dict()
    labels = dict['labels']
    price = dict['price']
    return render_template('storage_page.html', labels=labels, price=price)

@app.route('/storagegraphs', methods=['GET', 'POST'])
def storage_graphs():
    """Render the Storage page."""
    return render_template('storage_graphs.html')

@app.route('/motherboard', methods=['GET', 'POST'])
def motherboard_page():
    dict=mb_csv_reader.to_dict()
    labels = dict['labels']
    price = dict['price']
    return render_template('motherboard_page.html', labels=labels, price=price)

@app.route('/motherboardgraphs', methods=['GET', 'POST'])
def motherboard_graphs():
    """Render the motherboard page."""
    return render_template('motherboard_graphs.html')

@app.route('/powersupply', methods=['GET', 'POST'])
def powersupply_page():
    dict=psu_csv_reader.to_dict()
    labels = dict['labels']
    price = dict['price']
    return render_template('powersupply_page.html', labels=labels, price=price)

@app.route('/powersupplygraphs', methods=['GET', 'POST'])
def powersupply_graphs():
    """Render the power supply page."""
    return render_template('powersupply_graphs.html')

