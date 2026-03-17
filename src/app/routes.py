
from flask import Flask, render_template, jsonify, redirect, url_for, request
from sqlalchemy import inspect, text
from app import app
from app import db
import os
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


# py partpicker, an api for getting data from pc partpicker, trying this out 
#Blocked by pcpp, likely due to Cloudflare.
#import pypartpicker
#import asyncio
#from pypartpicker import AsyncClient

#
#
# This is for the old data from the github instead of our scraper
#
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
        # print(df['price'].median())

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
# end of the old data reader

# This is for the new data from our scraper
class scraper_csv_reader:
    def __init__(self, name, price, date):
        self.name = name
        self.price = price
        self.date = date

    def from_csv(self, file_name, sort_by, ascending_bool):
        csv_path = f'static/data/newegg_price_history_files/{file_name}.csv'
        df = pd.read_csv(csv_path)
        df = df.dropna(subset=['price'])
        df = df.sort_values(by=sort_by, ascending=ascending_bool)
        self.name = df['product_name'].tolist()
        self.price = df['price'].tolist()
        self.date = df['snapshot_date'].tolist()

    def to_dict(self):
        return {
            'name': self.name,
            'price': self.price,
            'date': self.date,
        }

    #dont touch these unless you know what you're doing
new_cpu_csv_reader = scraper_csv_reader([], [], [])
new_cpu_csv_reader.from_csv('cpu', 'product_name', True)

new_memory_csv_reader = scraper_csv_reader([], [], [])
new_memory_csv_reader.from_csv('memory', 'product_name', True)

new_gpu_csv_reader = scraper_csv_reader([], [], [])
new_gpu_csv_reader.from_csv('video-card', 'product_name', True)

new_storage_csv_reader = scraper_csv_reader([], [], [])
new_storage_csv_reader.from_csv('internal-hard-drive', 'product_name', True)

#used to add the old data into a database
# csv_files = [
#     r"static\data\old PCpartpicker data\combined_video-card.csv",
#     r"static\data\old PCpartpicker data\combined_cpu.csv",
#     r"static\data\old PCpartpicker data\combined_power-supply.csv",
#     r"static\data\old PCpartpicker data\combined_motherboard.csv",
#     r"static\data\old PCpartpicker data\combined_memory.csv",
#     r"static\data\old PCpartpicker data\combined_internal-hard-drive.csv"
# ]

# def import_all_parts():
#     with app.app_context():
#         for path in csv_files:
#             # 1. Generate a clean table name (e.g., 'video_card')
#             filename = os.path.basename(path)
#             table_name = filename.replace('combined_', '').replace('.csv', '').replace('-', '_')
            
#             print(f"Importing {path} into table '{table_name}'...")
            
#             # 2. Read CSV into Pandas DataFrame
#             # Tip: Use 'encoding' if you encounter special character errors
#             df = pd.read_csv(path)
            
#             # 3. Write to SQLite
#             # if_exists='replace' creates the table from scratch based on CSV headers
#             # if_exists='append' adds data if you've already defined SQLAlchemy models
#             df.to_sql(table_name, con=db.engine, if_exists='replace', index=False)

# import_all_parts()

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

# The following code is for testing the pypartpicker library and checking if we're being blocked by Cloudflare. It should be run separately from the Flask app, as it uses asyncio and is not designed to be part of a web request handler.
# pcpp = AsyncClient()
# @app.route('/search', methods=['GET', 'POST'])
# async def search_results():
#     query = request.args.get('q')
#     if not query:
#         return redirect(url_for('index'))

#     try:
#         # Use a context manager to handle session setup/teardown
#         async with AsyncClient() as pcpp:
#             search_result = await pcpp.get_part_search(query, region="us")
#             # Safety check: if the library returned None instead of a result object
#             if search_result is None:
#                 return render_template('search_results.html', parts=[], query=query)
            
#             parts = search_result.parts
#     except AttributeError as e:
#         print(f"Scraping Error (Likely Cloudflare block): {e}")
#         parts = []
#     except Exception as e:
#         print(f"General Error: {e}")
#         parts = []
        
#     return render_template('search_results.html', parts=parts, query=query)

# @app.route('/search')
# def search():
#     query = request.args.get('q', '')
#     all_results = []
#     tables = ['video_card', 'cpu', 'power_supply', 'motherboard', 'memory', 'internal_hard_drive']
    
#     # Define columns you want to ignore across ALL tables
#     ignored_cols = ['price', 'snapshot_date', 'id', 'price_per_gb', 'price/gb']

#     if query:
#         for table_name in tables:
            # inst = inspect(db.engine)
            # columns = [c['name'] for c in inst.get_columns(table_name)]
            
            # # Filter out the ignored columns
            # group_cols = [c for c in columns if c.lower() not in ignored_cols]
            # norm_cols = [f"REPLACE(LOWER(CAST({c} AS TEXT)), ' ', '')" for c in group_cols]
            # group_by_str = ", ".join(norm_cols)
            
            # # Select the 'raw' values but group by normalized versions
#             sql = text(f"SELECT * FROM {table_name} WHERE name LIKE :q GROUP BY {group_by_str}")
#             results = db.session.execute(sql, {"q": f"%{query}%"}).mappings().all()
            
#             for row in results:
#                 item = dict(row)
#                 item['table_name'] = table_name
#                 item['type_label'] = table_name.replace('_', ' ').title()
#                 # Identity params should NOT include price_per_gb
#                 item['identity_params'] = {k: v for k, v in item.items() if k in group_cols}
#                 all_results.append(item)

#     return render_template('search_results.html', results=all_results, query=query)

@app.route('/search')
def search():
    query = request.args.get('q', '')
    active_filters = {k: v for k, v in request.args.items() if k not in ['q', 'page'] and v}
    selected_category = active_filters.get('category')
    if selected_category:
        tables_to_search = [selected_category]
    else:
        tables_to_search = ['video_card', 'cpu', 'power_supply', 'motherboard', 'memory', 'internal_hard_drive']


    all_results = []
    filter_options = {}
    
    tables = ['video_card', 'cpu', 'power_supply', 'motherboard', 'memory', 'internal_hard_drive']
    ignored_cols = ['price', 'snapshot_date', 'id', 'price_per_gb', 'price/gb', 'table_name', 'type_label', 'identity_params']

    if query:
        for table_name in tables_to_search:
            inst = inspect(db.engine)
            columns = [c['name'] for c in inst.get_columns(table_name)]
            
            # --- FIX: Define these ONCE per table loop ---
            where_parts = ["name LIKE :q"]
            params = {"q": f"%{query}%"}

            for key, val in active_filters.items():
                if key in columns:
                    # If the column exists, apply the filter
                    where_parts.append(f"REPLACE(LOWER(CAST({key} AS TEXT)), ' ', '') = :{key}_val")
                    params[f"{key}_val"] = val.replace(" ", "").lower()
                else:
                    # If the column doesn't exist in THIS table (e.g., 'speed' in 'video_card'),
                    # we skip it so the table still shows its basic search results.
                    pass 
            
            # 2. Define identifying columns and grouping logic
            group_cols = [c for c in columns if c.lower() not in ignored_cols]
            norm_group_by = ", ".join([f"REPLACE(LOWER(CAST({c} AS TEXT)), ' ', '')" for c in group_cols])
            
            sql_filters = {k: v for k, v in active_filters.items() if k != 'category'}
            
            # 3. Build the final SQL (No more resetting here!)
            where_clause = " AND ".join(where_parts)
            sql = text(f"SELECT * FROM {table_name} WHERE {where_clause} GROUP BY {norm_group_by}")
            
            # 4. Execute and Process
            results = db.session.execute(sql, params).mappings().all()
            for row in results:
                item = dict(row)
                item['table_name'] = table_name
                item['type_label'] = table_name.replace('_', ' ').title()
                item['identity_params'] = {k: v for k, v in item.items() if k in group_cols}
                all_results.append(item)
                
                # 5. Populate dropdowns ONLY from the filtered results
                for key, val in item.items():
                    if key not in ignored_cols and key != 'name' and val:
                        if key not in filter_options:
                            filter_options[key] = set()
                        filter_options[key].add(str(val))

    sorted_filters = {k: sorted(list(v)) for k, v in filter_options.items()}
    
    return render_template('search_results.html', 
                           results=all_results, 
                           query=query, 
                           filter_options=sorted_filters, 
                           active_filters=active_filters)


@app.route('/history')
def item_history():
    table_type = request.args.get('table_type')

    ignored = ['table_type', 'price_per_gb', 'price/gb']
    filters = {k: v for k, v in request.args.items() if k not in ignored and v != 'None'}
    
    # Build a normalized WHERE clause
    # This compares: REPLACE('5, 4800', ' ', '') = REPLACE('5,4800', ' ', '')
    where_parts = []
    clean_params = {}
    
    for k, v in filters.items():
        # Strip spaces from the search value coming from the URL
        clean_val = str(v).replace(" ", "").lower()
        where_parts.append(f"REPLACE(LOWER(CAST({k} AS TEXT)), ' ', '') = :{k}_clean")
        clean_params[f"{k}_clean"] = clean_val

    where_clause = " AND ".join(where_parts)
    sql = text(f"SELECT * FROM {table_type} WHERE {where_clause} ORDER BY snapshot_date ASC")
    
    rows = db.session.execute(sql, clean_params).mappings().all()
    
    # Process dates and prices for the chart
    labels = [row['snapshot_date'] for row in rows]
    prices = []
    for row in rows:
        try:
            # Strip currency symbols and commas
            clean_price = str(row['price']).replace('$', '').replace(',', '')
            prices.append(float(clean_price))
        except (ValueError, TypeError):
            prices.append(None)

    return render_template('item_history.html', 
                           history=rows, 
                           specs=filters,
                           dates=json.dumps(labels), 
                           prices=json.dumps(prices))

@app.route('/memory', methods=['GET', 'POST'])
def memory_page():
    dict=new_memory_csv_reader.to_dict()
    names = dict['name']
    price = dict['price']
    date = dict['date']
    return render_template('memory_page.html', names=names, price=price, date=date)

@app.route('/memorygraphs', methods=['GET', 'POST'])
def memory_graphs():
    dict=new_memory_csv_reader.to_dict()
    names = dict['name']
    price = dict['price']
    date = dict['date']
    return render_template('memory_graphs.html', names=names, price=price, date=date)

@app.route('/gpu', methods=['GET', 'POST'])
def gpu_page():
    dict=new_gpu_csv_reader.to_dict()
    names = dict['name']
    price = dict['price']
    date = dict['date']
    return render_template('gpu_page.html', names=names, price=price, date=date)

@app.route('/gpugraphs', methods=['GET', 'POST'])
def gpu_graphs():
    dict=new_gpu_csv_reader.to_dict()
    names = dict['name']
    price = dict['price']
    date = dict['date']
    return render_template('gpu_graphs.html', names=names, price=price, date=date)

@app.route('/cpu', methods=['GET', 'POST'])
def cpu_page():
    dict=new_cpu_csv_reader.to_dict()
    names = dict['name']
    price = dict['price']
    date = dict['date']
    return render_template('cpu_page.html', names=names, price=price, date=date)

@app.route('/cpugraphs', methods=['GET', 'POST'])
def cpu_graphs():
    """Render the CPU graphs."""
    return render_template('cpu_graphs.html')

@app.route('/storage', methods=['GET', 'POST'])
def storage_page():
    dict=new_storage_csv_reader.to_dict()
    names = dict['name']
    price = dict['price']
    date = dict['date']
    return render_template('storage_page.html', names=names, price=price, date=date)

@app.route('/storagegraphs', methods=['GET', 'POST'])
def storage_graphs():
    """Render the Storage graphs."""
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

