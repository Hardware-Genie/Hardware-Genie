
from logging import exception

from flask import Flask, render_template, jsonify, redirect, url_for, request
from sqlalchemy import inspect, text
from app import app
from app import db
import os
import pandas as pd
import json
import re
from urllib.parse import urlencode

from app.forms import LoginForm, SignupForm, WebsiteToScrape
from app.models import User
from app.wayback_newegg_scrapy.wayback_newegg_scrapy.spiders import wayback_newegg
from app.wayback_newegg_scrapy.wayback_newegg_scrapy.spiders.wayback_newegg import WaybackNeweggSpider
from app import tasks
import scrapy
import bcrypt
from flask_login import login_user, logout_user, login_required, current_user, login_manager
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


def _normalize_memory_label(value):
    if value is None:
        return None
    return re.sub(r'\s*,\s*', ',', str(value).strip())


CATEGORY_FILTER_PRIORITY = {
    'memory': ['modules', 'speed', 'cas_latency', 'first_word_latency', 'color'],
    'video_card': ['memory', 'core_clock', 'boost_clock', 'chipset', 'length', 'color'],
    'cpu': ['core_count', 'core_clock', 'boost_clock', 'tdp', 'graphics', 'smt', 'microarchitecture'],
    'motherboard': ['max_memory', 'memory_slots', 'socket', 'form_factor', 'color'],
    'internal_hard_drive': ['capacity', 'type', 'interface', 'form_factor', 'cache'],
}

FILTER_LABEL_OVERRIDES = {
    'core_count': 'Core Count',
    'core_clock': 'Core Clock',
    'boost_clock': 'Boost Clock',
    'max_memory': 'Max Memory',
    'memory_slots': 'Memory Slots',
    'first_word_latency': 'First Word Latency',
    'cas_latency': 'CAS Latency',
    'form_factor': 'Form Factor',
}

BUILD_TABLE_LABELS = {
    'cpu': 'CPU',
    'memory': 'Memory',
    'video_card': 'Video Card',
    'motherboard': 'Motherboard',
    'power_supply': 'Power Supply',
    'internal_hard_drive': 'Storage',
}


def _safe_parse_price(value):
    try:
        return float(str(value).replace('$', '').replace(',', '').strip())
    except (TypeError, ValueError):
        return None


def _build_category_items(table_name):
    inst = inspect(db.engine)
    columns = [c['name'] for c in inst.get_columns(table_name)]
    grouping_ignored_cols = ['price', 'snapshot_date', 'id', 'price_per_gb', 'price/gb', 'table_name', 'type_label', 'identity_params', 'value', 'deal_quality']
    group_cols = [c for c in columns if c.lower() not in grouping_ignored_cols]

    if not group_cols:
        return []

    group_by_cols = ", ".join(group_cols)
    sql = text(f"""
    SELECT *
    FROM (
        SELECT *, ROW_NUMBER() OVER (PARTITION BY {group_by_cols} ORDER BY snapshot_date DESC) as rn
        FROM {table_name}
    )
    WHERE rn = 1
    """)

    rows = db.session.execute(sql).mappings().all()
    items = []
    for row in rows:
        row_data = dict(row)
        name = row_data.get('name')
        if not name:
            continue

        price = _safe_parse_price(row_data.get('price'))
        items.append({
            'name': name,
            'price': price,
            'display_price': f"${price:,.2f}" if price is not None else 'N/A',
        })

    items.sort(key=lambda item: str(item.get('name', '')).lower())
    return items


def _get_build_catalog():
    catalog = {}
    for table_name, label in BUILD_TABLE_LABELS.items():
        catalog[table_name] = {
            'label': label,
            'items': _build_category_items(table_name),
        }
    return catalog



# #used to add the old data into a database
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

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    form = SignupForm()
    if form.validate_on_submit():
        if form.password.data == form.confirm_password.data:
            hashed = bcrypt.hashpw((form.password.data).encode('utf-8'), bcrypt.gensalt())
            newUser = User(email=form.email.data,username=form.username.data, password_hash=hashed)
            db.session.add(newUser)
            # don't commit if there is another user with the same id, or any other error that occurs with the commit
            try:
                db.session.commit()
                print("User created successfully")
            except:
                return render_template('signup.html',form=form, same_email=1)
            return redirect(url_for('index'))
        else:
            # if the passwords in the sinup dont match return to form with same data but give a message that says passwords dont match
            return render_template('signup.html', form=form, miss_match=1)
    return render_template('signup.html', form=form, same_email=0, miss_match=0, form_errors=form.errors)

@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        #Try to find user
        try:
            user = db.session.execute(db.select(User).filter(User.email==form.email.data)).scalar_one_or_none()
        except:
            # if the id doesnt exist give user message
            return render_template('login.html', wrong_email=1, form=form)
        #    
        #Authenticate user
        try:
            if bcrypt.checkpw((form.password.data).encode('utf-8'), user.password_hash):
                login_user(user)
                print("User logged in successfully")
                return redirect(url_for('index'))
            else:
                # if the password is wrong take to other page to say wrong password
                print("Wrong password")
                return render_template('login.html', wrong_pass=1, form=form)
        except Exception as e:
            print(f"Error during login: {e}")
            return render_template('login.html', wrong_email=1, form=form)
        print("Error during login")
    print(form.errors)
    return render_template('login.html', form=form, wrong_email=0, wrong_pass=0, form_errors=form.errors)


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

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


@app.route('/search')
def search():
    query = request.args.get('q', '')
    page = request.args.get('page', 1, type=int)
    sort_by = request.args.get('sort', 'alphabetical_asc')
    from_build = request.args.get('from_build', '0') == '1'
    min_price = request.args.get('min_price', type=float)
    max_price = request.args.get('max_price', type=float)
    min_value = request.args.get('min_value', type=float)
    max_value = request.args.get('max_value', type=float)
    per_page = 50
    active_filter_values = {
        key: [value for value in values if value]
        for key, values in request.args.lists()
        if key not in ['q', 'page', 'sort', 'min_price', 'max_price', 'min_value', 'max_value', 'from_build']
    }
    selected_category = active_filter_values.get('category', [None])[0] if 'category' in active_filter_values else None
    if selected_category:
        tables_to_search = [selected_category]
    else:
        tables_to_search = ['video_card', 'cpu', 'power_supply', 'motherboard', 'memory', 'internal_hard_drive']

    all_results = []
    filter_options = {}
    price_range = {'min': float('inf'), 'max': 0}
    value_range = {'min': float('inf'), 'max': 0}
    
    tables = ['video_card', 'cpu', 'power_supply', 'motherboard', 'memory', 'internal_hard_drive']
    grouping_ignored_cols = ['price', 'snapshot_date', 'id', 'price_per_gb', 'price/gb', 'table_name', 'type_label', 'identity_params', 'value', 'deal_quality']
    filter_ignored_cols = ['id', 'snapshot_date', 'table_name', 'type_label', 'identity_params', 'name', 'price', 'value']

    for table_name in tables_to_search:
        inst = inspect(db.engine)
        columns = [c['name'] for c in inst.get_columns(table_name)]
        
        where_parts = []
        params = {}

        if query:
            where_parts.append("name LIKE :q")
            params["q"] = f"%{query}%"

        # 2. Define identifying columns and grouping logic
        group_cols = [c for c in columns if c.lower() not in grouping_ignored_cols]
        
        # 3. Build the final SQL - use ROW_NUMBER window function for better performance
        where_clause = " AND ".join(where_parts) if where_parts else "1=1"
        group_by_cols = ", ".join(group_cols)
        
        # Use ROW_NUMBER to get the most recent row for each product
        sql = text(f"""
        SELECT *
        FROM (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY {group_by_cols} ORDER BY snapshot_date DESC) as rn
            FROM {table_name}
            WHERE {where_clause}
        )
        WHERE rn = 1
        """)
        
        # 4. Execute and Process
        results = db.session.execute(sql, params).mappings().all()
        for row in results:
            item = dict(row)
            item['table_name'] = table_name
            item['type_label'] = table_name.replace('_', ' ').title()
            item['identity_params'] = {k: v for k, v in item.items() if k in group_cols}
            spec_ignored_for_build = ['name', 'price', 'snapshot_date', 'table_name', 'type_label', 'identity_params', 'id', 'price_per_gb', 'price/gb', 'value', 'deal_quality', 'rn']
            spec_parts = []
            for key, value in item.items():
                if key.lower() in spec_ignored_for_build or value is None or value == '':
                    continue
                spec_parts.append(f"{key.replace('_', ' ').title()}: {value}")
            item['spec_summary'] = " | ".join(spec_parts)
            
            # Populate filter options from the unfiltered baseline set so choices remain visible.
            for key, val in item.items():
                if key not in filter_ignored_cols and val:
                    normalized_val = _normalize_memory_label(val)
                    if key not in filter_options:
                        filter_options[key] = set()
                    filter_options[key].add(normalized_val)

            # Apply selected checkbox filters after building options to avoid shrinking menus.
            item_matches_active_filters = True
            for key, val_list in active_filter_values.items():
                if key == 'category' or key not in columns or not val_list:
                    continue

                normalized_item_val = str(item.get(key, '')).replace(' ', '').lower()
                normalized_selected_vals = [str(v).replace(' ', '').lower() for v in val_list]
                if normalized_item_val not in normalized_selected_vals:
                    item_matches_active_filters = False
                    break

            if not item_matches_active_filters:
                continue

            all_results.append(item)

            # Track price range for currently matched results.
            try:
                price = float(str(item.get('price', 0)).replace('$', '').replace(',', ''))
                price_range['min'] = min(price_range['min'], price)
                price_range['max'] = max(price_range['max'], price)
            except:
                pass

            # Track value range for memory analysis controls.
            try:
                value = float(str(item.get('value', 0)).replace('$', '').replace(',', ''))
                value_range['min'] = min(value_range['min'], value)
                value_range['max'] = max(value_range['max'], value)
            except:
                pass

    # Apply numeric range filters after collecting latest rows per item
    if min_price is not None or max_price is not None or min_value is not None or max_value is not None:
        filtered_results = []
        for item in all_results:
            try:
                item_price = float(str(item.get('price', 0)).replace('$', '').replace(',', '') or 0)
            except:
                item_price = None

            try:
                item_value = float(str(item.get('value', 0)).replace('$', '').replace(',', '') or 0)
            except:
                item_value = None

            if min_price is not None and (item_price is None or item_price < min_price):
                continue
            if max_price is not None and (item_price is None or item_price > max_price):
                continue
            if min_value is not None and (item_value is None or item_value < min_value):
                continue
            if max_value is not None and (item_value is None or item_value > max_value):
                continue

            filtered_results.append(item)

        all_results = filtered_results

    # Categorize filters: numeric vs text
    numeric_filters = set()
    text_filters = {}
    for key, vals in filter_options.items():
        try:
            if all(str(v).replace('.', '').replace(',', '').replace('-', '').isdigit() for v in vals if v):
                numeric_filters.add(key)
        except:
            pass
        if key not in numeric_filters:
            text_filters[key] = sorted(list(vals))

    forced_filter_keys = set(CATEGORY_FILTER_PRIORITY.get(selected_category, []))
    sorted_filters = {
        k: sorted(list(v), key=lambda x: str(x).lower())
        for k, v in filter_options.items()
        if k not in numeric_filters or k in forced_filter_keys
    }

    # Prioritize requested category-specific filters at the top of the sidebar.
    if selected_category in CATEGORY_FILTER_PRIORITY:
        preferred_order = CATEGORY_FILTER_PRIORITY[selected_category]
        ordered_filters = {}

        for filter_key in preferred_order:
            if filter_key in sorted_filters:
                ordered_filters[filter_key] = sorted_filters[filter_key]

        for filter_key, values in sorted_filters.items():
            if filter_key not in ordered_filters:
                ordered_filters[filter_key] = values

        sorted_filters = ordered_filters

    filter_labels = {
        filter_key: FILTER_LABEL_OVERRIDES.get(filter_key, filter_key.replace('_', ' ').title())
        for filter_key in sorted_filters
    }
    
    # Apply sorting
    if sort_by in ['relevance', 'alphabetical_asc']:
        all_results.sort(key=lambda x: str(x.get('name', '')).lower())
    elif sort_by == 'alphabetical_desc':
        all_results.sort(key=lambda x: str(x.get('name', '')).lower(), reverse=True)
    elif sort_by == 'price_low':
        all_results.sort(key=lambda x: float(str(x.get('price', 0)).replace('$', '').replace(',', '') or 0))
    elif sort_by == 'price_high':
        all_results.sort(key=lambda x: float(str(x.get('price', 0)).replace('$', '').replace(',', '') or 0), reverse=True)
    elif sort_by == 'value_best':
        all_results.sort(key=lambda x: float(x.get('value', 0) or 0), reverse=True)
    elif sort_by == 'value_worst':
        all_results.sort(key=lambda x: float(x.get('value', 0) or 0))

    total_results = len(all_results)
    total_pages = max(1, (total_results + per_page - 1) // per_page)
    if page < 1:
        page = 1
    if page > total_pages:
        page = total_pages

    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated_results = all_results[start_idx:end_idx]
    start_item = start_idx + 1 if total_results > 0 else 0
    end_item = min(end_idx, total_results)

    flat_active_filters = {
        key: values[0] if len(values) == 1 else values
        for key, values in active_filter_values.items()
        if values
    }

    pagination_query_items = []
    if query:
        pagination_query_items.append(('q', query))
    if sort_by:
        pagination_query_items.append(('sort', sort_by))
    if from_build:
        pagination_query_items.append(('from_build', '1'))
    for key, values in active_filter_values.items():
        for value in values:
            pagination_query_items.append((key, value))
    if min_price is not None:
        pagination_query_items.append(('min_price', min_price))
    if max_price is not None:
        pagination_query_items.append(('max_price', max_price))
    if min_value is not None:
        pagination_query_items.append(('min_value', min_value))
    if max_value is not None:
        pagination_query_items.append(('max_value', max_value))
    pagination_query_string = urlencode(pagination_query_items, doseq=True)
    
    if price_range['min'] == float('inf'):
        price_range['min'] = 0
    if value_range['min'] == float('inf'):
        value_range['min'] = 0
    
    return render_template('products.html', 
                           results=paginated_results,
                           query=query, 
                           filter_options=sorted_filters, 
                           filter_labels=filter_labels,
                           active_filters=flat_active_filters,
                           all_active_filters=active_filter_values,
                           sort_by=sort_by,
                           selected_category=selected_category,
                           show_memory_analysis=selected_category == 'memory',
                           pagination_query_string=pagination_query_string,
                           page=page,
                           total_pages=total_pages,
                           total_results=total_results,
                           start_item=start_item,
                           end_item=end_item,
                           price_range=price_range,
                           value_range=value_range,
                           min_price=min_price,
                           max_price=max_price,
                           min_value=min_value,
                           max_value=max_value,
                           from_build=from_build)


@app.route('/products')
def products():
    return search()


@app.route('/build')
def build_page():
    build_categories = [
        {'key': key, 'label': label}
        for key, label in BUILD_TABLE_LABELS.items()
    ]
    return render_template('build.html', build_categories=build_categories)


@app.route('/history')
def item_history():
    table_type = request.args.get('table_type')

    ignored = ['table_type', 'price_per_gb', 'price/gb', 'microarchitecture', 'smt']
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

