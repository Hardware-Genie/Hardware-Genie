
from logging import exception
from bisect import bisect_right

from flask import Flask, render_template, jsonify, redirect, url_for, request
from sqlalchemy import inspect, text
from app import app
from app import db
import os
import pandas as pd
import json
import re
from urllib.parse import urlencode, urlparse

from app.forms import LoginForm, SignupForm, ProfileForm, ResetPasswordForm, PartScraperForm, ArticleScraperForm
from app.models import User, SavedBuild
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
# class csv_data_reader:
#     def __init__(self, labels, price):
#         self.labels = labels
#         self.price = price

#     def from_csv(self, file_name, sort, ascending):
#         csv_path = f'static/data/{file_name}.csv'
#         df = pd.read_csv(csv_path)
#         df = df.dropna(subset=['price'])
#         df = df.sort_values(by=sort, ascending=ascending)
#         self.labels = df['name'].tolist()
#         self.price = df['price'].tolist()
#         # print(df['price'].median())

#     def to_dict(self):
#         return {
#             'labels': self.labels,
#             'price': self.price,
#         }

# cpu_csv_reader = csv_data_reader([], [])
# cpu_csv_reader.from_csv('July 23 2025/cpu', 'price', True)

# memory_csv_reader = csv_data_reader([], [])
# memory_csv_reader.from_csv('July 23 2025/memory', 'price', True)

# gpu_csv_reader = csv_data_reader([], [])
# gpu_csv_reader.from_csv('July 23 2025/video-card', 'price', True)

# gpu_csv_reader_sort = csv_data_reader([], [])
# gpu_csv_reader_sort.from_csv('July 23 2025/video-card', 'price', False)

# storage_csv_reader = csv_data_reader([], [])
# storage_csv_reader.from_csv('July 23 2025/internal-hard-drive', 'price', True)

# mb_csv_reader = csv_data_reader([], [])
# mb_csv_reader.from_csv('July 23 2025/motherboard', 'price', True)

# psu_csv_reader = csv_data_reader([], [])
# psu_csv_reader.from_csv('July 23 2025/power-supply', 'price', True)
# end of the old data reader

# This is for the new data from our scraper
class scraper_csv_reader:
    def __init__(self, name, price, date):
        self.name = name
        self.price = price
        self.date = date

    def from_csv(self, file_name, sort_by, ascending_bool):
        csv_path = f'static/data/newegg_price_history_files/{file_name}.csv'
        try:
            df = pd.read_csv(csv_path)
        except (FileNotFoundError, pd.errors.EmptyDataError, pd.errors.ParserError):
            self.name = []
            self.price = []
            self.date = []
            return

        name_column = 'product_name' if 'product_name' in df.columns else 'name' if 'name' in df.columns else None
        if name_column is None:
            self.name = []
            self.price = []
            self.date = []
            return

        df = df.dropna(subset=['price'])
        df = df[df[name_column].fillna('').astype(str).str.strip() != '']

        if sort_by not in df.columns:
            sort_by = name_column

        df = df.sort_values(by=sort_by, ascending=ascending_bool)
        self.name = df[name_column].fillna('').tolist()
        self.price = df['price'].tolist()
        self.date = df['snapshot_date'].tolist() if 'snapshot_date' in df.columns else []

    def to_dict(self):
        return {
            'name': self.name,
            'price': self.price,
            'date': self.date,
        }

    #dont touch these unless you know what you're doing
new_cpu_csv_reader = scraper_csv_reader([], [], [])
new_cpu_csv_reader.from_csv('cpu', 'name', True)

new_memory_csv_reader = scraper_csv_reader([], [], [])
new_memory_csv_reader.from_csv('memory', 'name', True)

new_gpu_csv_reader = scraper_csv_reader([], [], [])
new_gpu_csv_reader.from_csv('video-card', 'name', True)

new_storage_csv_reader = scraper_csv_reader([], [], [])
new_storage_csv_reader.from_csv('internal-hard-drive', 'name', True)

new_motherboard_csv_reader = scraper_csv_reader([], [], [])
new_motherboard_csv_reader.from_csv('motherboard', 'name', True)

new_psu_csv_reader = scraper_csv_reader([], [], [])
new_psu_csv_reader.from_csv('power-supply', 'name', True)


def _normalize_memory_label(value):
    if value is None:
        return None
    return re.sub(r'\s*,\s*', ',', str(value).strip())


def _parse_memory_modules(value):
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    match = re.search(r'(\d+(?:\.\d+)?)\s*[,xX]\s*(\d+(?:\.\d+)?)\s*(TB|GB)?', text)
    if not match:
        numbers = re.findall(r'\d+(?:\.\d+)?', text)
        if len(numbers) < 2:
            return None
        match = (numbers[0], numbers[1], re.search(r'(TB|GB)', text, re.I).group(1) if re.search(r'(TB|GB)', text, re.I) else 'GB')
        count_text, size_text, unit_text = match
    else:
        count_text, size_text, unit_text = match.group(1), match.group(2), match.group(3) or 'GB'

    try:
        module_count = float(count_text)
        module_size = float(size_text)
    except (TypeError, ValueError):
        return None

    unit = str(unit_text or 'GB').upper()
    if unit == 'TB':
        module_size *= 1024

    return {
        'count': module_count,
        'size': module_size,
    }


def _parse_memory_speed(value):
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    numbers = re.findall(r'\d+(?:\.\d+)?', text)
    if len(numbers) < 2:
        return None

    try:
        ddr_type = float(numbers[0])
        mhz = float(numbers[1])
    except (TypeError, ValueError):
        return None

    return {
        'ddr_type': ddr_type,
        'mhz': mhz,
    }


def _parse_memory_latency(value):
    if value is None:
        return None

    text = str(value).strip().replace(',', '')
    if not text:
        return None

    try:
        return float(text)
    except (TypeError, ValueError):
        numbers = re.findall(r'\d+(?:\.\d+)?', text)
        if not numbers:
            return None

        try:
            return float(numbers[0])
        except (TypeError, ValueError):
            return None


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

TREND_CATEGORY_LABELS = {
    'cpu': 'CPUs',
    'memory': 'Memory',
    'video_card': 'Video Cards',
    'motherboard': 'Motherboards',
    'power_supply': 'Power Supplies',
    'internal_hard_drive': 'Hard Drives',
}

HISTORY_SIGNATURE_COLUMNS = {
    'cpu': ['core_count', 'core_clock', 'boost_clock', 'tdp', 'graphics', 'smt'],
    'memory': ['modules', 'speed', 'cas_latency', 'color'],
    'video_card': ['chipset', 'memory', 'core_clock', 'boost_clock', 'length'],
    'motherboard': ['socket', 'form_factor', 'max_memory', 'memory_slots'],
    'power_supply': ['type', 'efficiency', 'wattage', 'modular'],
    'internal_hard_drive': ['capacity', 'type', 'interface', 'form_factor', 'cache'],
}

GROUPING_IGNORED_COLUMNS = ['price', 'snapshot_date', 'id', 'price_per_gb', 'price/gb', 'table_name', 'type_label', 'identity_params', 'value', 'deal_quality']


def _fetch_latest_row_for_part(table_type, part_name):
    if not table_type or not part_name:
        return None
    if table_type not in BUILD_TABLE_LABELS:
        return None
    if not _table_exists(table_type):
        return None

    sql = text(f"SELECT * FROM {table_type} WHERE name = :name ORDER BY snapshot_date DESC LIMIT 1")
    row = db.session.execute(sql, {'name': part_name}).mappings().first()
    return dict(row) if row else None


def _is_admin_user():
    if not getattr(current_user, 'is_authenticated', False):
        return False

    return bool(getattr(current_user, 'is_admin', False))


def _safe_parse_price(value):
    try:
        return float(str(value).replace('$', '').replace(',', '').strip())
    except (TypeError, ValueError):
        return None


def _slug_name_from_url(product_url):
    parsed = urlparse(product_url or '')
    path_parts = [p for p in parsed.path.split('/') if p]
    if 'p' in path_parts:
        p_index = path_parts.index('p')
        if p_index > 0:
            slug = path_parts[p_index - 1]
        elif len(path_parts) >= 2:
            slug = path_parts[-2]
        else:
            slug = path_parts[-1] if path_parts else ''
    elif len(path_parts) >= 2:
        slug = path_parts[-2]
    elif path_parts:
        slug = path_parts[-1]
    else:
        return None

    slug = re.sub(r'-p$', '', slug, flags=re.IGNORECASE)
    slug = re.sub(r'[-_]+', ' ', slug).strip()

    tokens = [t for t in re.split(r'\s+', slug) if t]
    if not tokens:
        return None

    stop_exact = {
        'desktop', 'laptop', 'notebook', 'memory', 'ram', 'black', 'white',
        'silver', 'red', 'blue', 'gray', 'grey', 'gold', 'kit', 'module', 'gaming'
    }

    shortened = []
    for token in tokens:
        lower = token.lower()
        if re.match(r'^ddr\d+$', lower):
            break
        if re.match(r'^cl\d+$', lower):
            break
        if lower in {'cas', 'latency'}:
            break
        if lower in stop_exact and len(shortened) >= 3:
            break
        shortened.append(token)

    if not shortened:
        shortened = tokens[:7]

    return ' '.join(shortened).title()


def _table_exists(table_name):
    return inspect(db.engine).has_table(table_name)


def _percentile_rank(sorted_values, value):
    if value is None or not sorted_values:
        return None

    total_values = len(sorted_values)
    if total_values == 1:
        return 100.0

    rank_index = bisect_right(sorted_values, value) - 1
    rank_index = max(0, min(rank_index, total_values - 1))
    return (rank_index / (total_values - 1)) * 100.0


def _category_group_columns(table_name):
    inst = inspect(db.engine)
    columns = [c['name'] for c in inst.get_columns(table_name)]
    ignored = {column.lower() for column in GROUPING_IGNORED_COLUMNS}
    return [column for column in columns if column.lower() not in ignored]


def _sorted_value_baseline_for_table(table_name, group_cols):
    if not table_name or not group_cols:
        return []

    group_by_cols = ", ".join(group_cols)
    baseline_sql = text(f"""
    SELECT value
    FROM (
        SELECT value,
               ROW_NUMBER() OVER (PARTITION BY {group_by_cols} ORDER BY snapshot_date DESC) as rn
        FROM {table_name}
    )
    WHERE rn = 1
    """)

    baseline_rows = db.session.execute(baseline_sql).mappings().all()
    baseline_values = []
    for baseline_row in baseline_rows:
        baseline_value = _safe_parse_price(baseline_row.get('value'))
        if baseline_value is not None:
            baseline_values.append(baseline_value)

    return sorted(baseline_values)


def _build_category_items(table_name):
    if not _table_exists(table_name):
        return []

    group_cols = _category_group_columns(table_name)

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


def _build_trend_series(table_name):
    if not _table_exists(table_name):
        return {
            'labels': [],
            'prices': [],
            'min_prices': [],
            'max_prices': [],
            'sample_counts': [],
        }

    sql = text(f"""
    SELECT snapshot_date,
           AVG(CAST(REPLACE(REPLACE(CAST(price AS TEXT), '$', ''), ',', '') AS REAL)) AS avg_price,
        MIN(CAST(REPLACE(REPLACE(CAST(price AS TEXT), '$', ''), ',', '') AS REAL)) AS min_price,
        MAX(CAST(REPLACE(REPLACE(CAST(price AS TEXT), '$', ''), ',', '') AS REAL)) AS max_price,
           COUNT(*) AS sample_count
    FROM {table_name}
    WHERE price IS NOT NULL
      AND TRIM(CAST(price AS TEXT)) != ''
    GROUP BY snapshot_date
    ORDER BY snapshot_date ASC
    """)

    rows = db.session.execute(sql).mappings().all()
    labels = []
    prices = []
    min_prices = []
    max_prices = []
    sample_counts = []

    for row in rows:
        snapshot_date = row.get('snapshot_date')
        avg_price = _safe_parse_price(row.get('avg_price'))
        min_price = _safe_parse_price(row.get('min_price'))
        max_price = _safe_parse_price(row.get('max_price'))
        if snapshot_date is None or avg_price is None:
            continue

        if min_price is None:
            min_price = avg_price
        if max_price is None:
            max_price = avg_price

        labels.append(str(snapshot_date))
        prices.append(round(avg_price, 2))
        min_prices.append(round(min_price, 2))
        max_prices.append(round(max_price, 2))
        sample_counts.append(int(row.get('sample_count') or 0))

    return {
        'labels': labels,
        'prices': prices,
        'min_prices': min_prices,
        'max_prices': max_prices,
        'sample_counts': sample_counts,
    }



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
        email = (form.email.data or '').strip().lower()
        password = form.password.data or ''
        if len(password) < 8 or len(password) > 128:
            form.password.errors.append('Password must be between 8 and 128 characters.')
            return render_template('signup.html', form=form, same_email=0, miss_match=0, form_errors=form.errors)

        if password == form.confirm_password.data:
            hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
            newUser = User(email=email,username=form.username.data, password_hash=hashed)
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
        email = (form.email.data or '').strip().lower()
        #Try to find user
        try:
            user = db.session.execute(db.select(User).filter(User.email==email)).scalar_one_or_none()
        except:
            # if the id doesnt exist give user message
            return render_template(
                'login.html',
                wrong_email=1,
                form=form,
                password_reset_debug_flow=app.config.get('PASSWORD_RESET_DEBUG_FLOW', False),
            )
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
                return render_template(
                    'login.html',
                    wrong_pass=1,
                    form=form,
                    password_reset_debug_flow=app.config.get('PASSWORD_RESET_DEBUG_FLOW', False),
                )
        except Exception as e:
            print(f"Error during login: {e}")
            return render_template(
                'login.html',
                wrong_email=1,
                form=form,
                password_reset_debug_flow=app.config.get('PASSWORD_RESET_DEBUG_FLOW', False),
            )
        print("Error during login")
    print(form.errors)
    return render_template(
        'login.html',
        form=form,
        wrong_email=0,
        wrong_pass=0,
        form_errors=form.errors,
        password_reset_debug_flow=app.config.get('PASSWORD_RESET_DEBUG_FLOW', False),
    )


@app.route('/password-reset-preview')
def password_reset_preview():
    if not app.config.get('PASSWORD_RESET_DEBUG_FLOW', False):
        return redirect(url_for('reset_password'))

    return render_template(
        'password_reset_preview.html',
        redirect_url=url_for('reset_password'),
        preview_image=url_for('static', filename='images/angai313-spongebob-sad.gif'),
    )


@app.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    form = ResetPasswordForm()
    password_reset = False

    if form.validate_on_submit():
        email = (form.email.data or '').strip().lower()
        new_password = form.new_password.data or ''

        user = db.session.execute(db.select(User).filter(User.email == email)).scalar_one_or_none()
        if user is None:
            form.email.errors.append('Email not found. Please try again.')
        elif new_password != (form.confirm_new_password.data or ''):
            form.confirm_new_password.errors.append('Passwords must match.')
        else:
            user.password_hash = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt())
            db.session.commit()
            password_reset = True
            form.email.data = ''
            form.new_password.data = ''
            form.confirm_new_password.data = ''

    return render_template(
        'reset_password.html',
        form=form,
        password_reset=password_reset,
        form_errors=form.errors,
        password_reset_debug_flow=app.config.get('PASSWORD_RESET_DEBUG_FLOW', False),
    )


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))


@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    form = ProfileForm()
    profile_updated = request.args.get('updated', '0') == '1'
    duplicate_username = False
    duplicate_email = False

    if form.validate_on_submit():
        username = (form.username.data or '').strip()
        email = (form.email.data or '').strip().lower()

        if not username:
            form.username.errors.append('Username is required.')
        if not email:
            form.email.errors.append('Email is required.')

        if username and username != current_user.username:
            existing_username = db.session.execute(
                db.select(User).filter(User.username == username, User.id != current_user.id)
            ).scalar_one_or_none()
            duplicate_username = existing_username is not None

        if email and email != current_user.email:
            existing_email = db.session.execute(
                db.select(User).filter(User.email == email, User.id != current_user.id)
            ).scalar_one_or_none()
            duplicate_email = existing_email is not None

        if duplicate_username:
            form.username.errors.append('Username already exists. Please choose another one.')
        if duplicate_email:
            form.email.errors.append('Email already exists. Please choose another one.')

        if not form.errors:
            current_user.username = username
            current_user.email = email

            new_password = form.new_password.data or ''
            if new_password.strip():
                current_user.password_hash = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt())

            db.session.commit()
            return redirect(url_for('profile', updated=1))

    elif request.method == 'GET':
        form.username.data = current_user.username
        form.email.data = current_user.email

    saved_builds = (
        SavedBuild.query
        .filter_by(user_id=current_user.id)
        .order_by(SavedBuild.updated_at.desc(), SavedBuild.id.desc())
        .all()
    )

    return render_template(
        'profile.html',
        form=form,
        profile_updated=profile_updated,
        duplicate_username=duplicate_username,
        duplicate_email=duplicate_email,
        saved_builds=saved_builds,
    )

@app.route('/scraper')
@login_required
def scraper_redirect():
    if not _is_admin_user():
        return redirect(url_for('index'))

    return redirect(url_for('scrapers'))


@app.route('/scrapers')
@login_required
def scrapers():
    if not _is_admin_user():
        return redirect(url_for('index'))

    return render_template('scrapers.html')


@app.route('/scrapers/parts', methods=['GET', 'POST'])
@login_required
def scraper_parts():
    if not _is_admin_user():
        return redirect(url_for('index'))

    form = PartScraperForm()
    if form.validate_on_submit():
        category = form.category.data
        url = form.url.data
        task = tasks.crawl_spider.delay(url, category)
        return redirect(url_for('scraper_status', task_id=task.id, scraper='parts', scraped_category=category, scraped_url=url))
    return render_template('scraper_parts.html', form=form)


@app.route('/scrapers/articles', methods=['GET', 'POST'])
@login_required
def scraper_articles():
    if not _is_admin_user():
        return redirect(url_for('index'))

    form = ArticleScraperForm()
    if form.validate_on_submit():
        source = (form.source.data or '').strip() or None
        keywords = (form.keywords.data or '').strip() or None
        max_articles = form.max_articles.data
        task = tasks.crawl_tech_news.delay(source=source, keywords=keywords, max_articles=max_articles)
        return redirect(url_for('scraper_status', task_id=task.id, scraper='articles'))
    return render_template('scraper_articles.html', form=form)

@app.route('/scraper/status/<task_id>')
@login_required
def scraper_status(task_id):
    if not _is_admin_user():
        return redirect(url_for('index'))

    from celery.result import AsyncResult
    from app.tasks import celery
    result = AsyncResult(task_id, app=celery)
    scraper_type = request.args.get('scraper', 'parts')
    scraped_category = request.args.get('scraped_category')
    scraped_url = request.args.get('scraped_url')
    part_history_url = None

    task_payload = result.result if isinstance(result.result, dict) else {}
    scrape_summary = task_payload.get('summary') if isinstance(task_payload.get('summary'), dict) else None
    if not scraped_category:
        scraped_category = task_payload.get('category')
    if not scraped_url:
        scraped_url = task_payload.get('product_url')

    if scraper_type == 'parts' and scraped_category and scraped_url:
        table_type = scraped_category.replace('-', '_')
        part_name = (
            (scrape_summary or {}).get('canonical_name')
            or task_payload.get('name')
            or _slug_name_from_url(scraped_url)
        )
        if part_name:
            history_params = {'table_type': table_type, 'name': part_name}
            latest_row = _fetch_latest_row_for_part(table_type, part_name)
            for column in HISTORY_SIGNATURE_COLUMNS.get(table_type, []):
                value = latest_row.get(column) if latest_row else None
                if value in (None, ''):
                    continue
                history_params[column] = value

            part_history_url = url_for('item_history', **history_params)

    if scraper_type == 'articles':
        back_url = url_for('scraper_articles')
        back_label = 'Back to Article Scraper'
    else:
        back_url = url_for('scraper_parts')
        back_label = 'Back to Part Scraper'

    return render_template(
        'scraper_status.html',
        task_id=task_id,
        state=result.state,
        result=result.result,
        info=result.info,
        back_url=back_url,
        back_label=back_label,
        part_history_url=part_history_url,
        scrape_summary=scrape_summary,
    )


@app.route('/search')
def search():
    query = request.args.get('q', '')
    page = request.args.get('page', 1, type=int)
    requested_sort = request.args.get('sort')
    sort_by = requested_sort if requested_sort else None
    from_build = request.args.get('from_build', '0') == '1'
    min_price = request.args.get('min_price', type=float)
    max_price = request.args.get('max_price', type=float)
    min_value = request.args.get('min_value', type=float)
    max_value = request.args.get('max_value', type=float)
    min_modules_count = request.args.get('min_modules_count', type=float)
    max_modules_count = request.args.get('max_modules_count', type=float)
    min_modules_size = request.args.get('min_modules_size', type=float)
    max_modules_size = request.args.get('max_modules_size', type=float)
    min_speed_ddr_type = request.args.get('min_speed_ddr_type', type=float)
    max_speed_ddr_type = request.args.get('max_speed_ddr_type', type=float)
    min_speed_mhz = request.args.get('min_speed_mhz', type=float)
    max_speed_mhz = request.args.get('max_speed_mhz', type=float)
    min_cas_latency = request.args.get('min_cas_latency', type=float)
    max_cas_latency = request.args.get('max_cas_latency', type=float)
    min_first_word_latency = request.args.get('min_first_word_latency', type=float)
    max_first_word_latency = request.args.get('max_first_word_latency', type=float)
    per_page = 50
    active_filter_values = {
        key: [value for value in values if value]
        for key, values in request.args.lists()
        if key not in ['q', 'page', 'sort', 'min_price', 'max_price', 'min_value', 'max_value', 'min_modules_count', 'max_modules_count', 'min_modules_size', 'max_modules_size', 'min_speed_ddr_type', 'max_speed_ddr_type', 'min_speed_mhz', 'max_speed_mhz', 'min_cas_latency', 'max_cas_latency', 'min_first_word_latency', 'max_first_word_latency', 'from_build']
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
    module_count_range = {'min': float('inf'), 'max': 0}
    module_size_range = {'min': float('inf'), 'max': 0}
    speed_ddr_type_range = {'min': float('inf'), 'max': 0}
    speed_mhz_range = {'min': float('inf'), 'max': 0}
    cas_latency_range = {'min': float('inf'), 'max': 0}
    first_word_latency_range = {'min': float('inf'), 'max': 0}
    value_samples_by_table = {}
    
    tables = ['video_card', 'cpu', 'power_supply', 'motherboard', 'memory', 'internal_hard_drive']
    filter_ignored_cols = ['id', 'snapshot_date', 'table_name', 'type_label', 'identity_params', 'name', 'price', 'value', 'snapshot_count', 'modules', 'speed', 'cas_latency', 'first_word_latency']

    for table_name in tables_to_search:
        if not _table_exists(table_name):
            continue

        inst = inspect(db.engine)
        columns = [c['name'] for c in inst.get_columns(table_name)]
        
        where_parts = []
        params = {}

        if query:
            where_parts.append("name LIKE :q")
            params["q"] = f"%{query}%"

        # 2. Define identifying columns and grouping logic
        group_cols = _category_group_columns(table_name)
        
        # 3. Build the final SQL - use ROW_NUMBER window function for better performance
        where_clause = " AND ".join(where_parts) if where_parts else "1=1"
        group_by_cols = ", ".join(group_cols)
        
        # Use ROW_NUMBER to get the most recent row for each product
        sql = text(f"""
        SELECT *
        FROM (
            SELECT *,
                   ROW_NUMBER() OVER (PARTITION BY {group_by_cols} ORDER BY snapshot_date DESC) as rn,
                   COUNT(*) OVER (PARTITION BY {group_by_cols}) as snapshot_count
            FROM {table_name}
            WHERE {where_clause}
        )
        WHERE rn = 1
        """)

        # Build the category-wide value baseline from all latest rows,
        # independent of search text and active filters.
        baseline_values = _sorted_value_baseline_for_table(table_name, group_cols)
        if baseline_values:
            value_samples_by_table[table_name] = baseline_values
        
        # 4. Execute and Process
        results = db.session.execute(sql, params).mappings().all()
        for row in results:
            item = dict(row)
            item['table_name'] = table_name
            item['type_label'] = table_name.replace('_', ' ').title()
            item['identity_params'] = {k: v for k, v in item.items() if k in group_cols}
            item['snapshot_count'] = int(item.get('snapshot_count') or 0)
            spec_ignored_for_build = ['name', 'price', 'snapshot_date', 'table_name', 'type_label', 'identity_params', 'id', 'price_per_gb', 'price/gb', 'value', 'deal_quality', 'rn', 'snapshot_count']
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

            modules_dimensions = _parse_memory_modules(item.get('modules'))
            if modules_dimensions:
                module_count_range['min'] = min(module_count_range['min'], modules_dimensions['count'])
                module_count_range['max'] = max(module_count_range['max'], modules_dimensions['count'])
                module_size_range['min'] = min(module_size_range['min'], modules_dimensions['size'])
                module_size_range['max'] = max(module_size_range['max'], modules_dimensions['size'])

            speed_dimensions = _parse_memory_speed(item.get('speed'))
            if speed_dimensions:
                speed_ddr_type_range['min'] = min(speed_ddr_type_range['min'], speed_dimensions['ddr_type'])
                speed_ddr_type_range['max'] = max(speed_ddr_type_range['max'], speed_dimensions['ddr_type'])
                speed_mhz_range['min'] = min(speed_mhz_range['min'], speed_dimensions['mhz'])
                speed_mhz_range['max'] = max(speed_mhz_range['max'], speed_dimensions['mhz'])

            cas_latency_value = _parse_memory_latency(item.get('cas_latency'))
            if cas_latency_value is not None:
                cas_latency_range['min'] = min(cas_latency_range['min'], cas_latency_value)
                cas_latency_range['max'] = max(cas_latency_range['max'], cas_latency_value)

            first_word_latency_value = _parse_memory_latency(item.get('first_word_latency'))
            if first_word_latency_value is not None:
                first_word_latency_range['min'] = min(first_word_latency_range['min'], first_word_latency_value)
                first_word_latency_range['max'] = max(first_word_latency_range['max'], first_word_latency_value)

            # Keep raw DB value for scoring against the category-wide baseline.
            item_value_raw = _safe_parse_price(item.get('value'))
            item['value_raw'] = item_value_raw
            item['value_normalized'] = None

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

            if item_matches_active_filters and table_name == 'memory' and any(value is not None for value in [min_modules_count, max_modules_count, min_modules_size, max_modules_size, min_speed_ddr_type, max_speed_ddr_type, min_speed_mhz, max_speed_mhz, min_cas_latency, max_cas_latency, min_first_word_latency, max_first_word_latency]):
                if min_modules_count is not None or max_modules_count is not None or min_modules_size is not None or max_modules_size is not None:
                    if not modules_dimensions:
                        item_matches_active_filters = False
                    else:
                        module_count = modules_dimensions['count']
                        module_size = modules_dimensions['size']
                        if min_modules_count is not None and module_count < min_modules_count:
                            item_matches_active_filters = False
                        if max_modules_count is not None and module_count > max_modules_count:
                            item_matches_active_filters = False
                        if min_modules_size is not None and module_size < min_modules_size:
                            item_matches_active_filters = False
                        if max_modules_size is not None and module_size > max_modules_size:
                            item_matches_active_filters = False

                if item_matches_active_filters and (min_speed_ddr_type is not None or max_speed_ddr_type is not None or min_speed_mhz is not None or max_speed_mhz is not None):
                    if not speed_dimensions:
                        item_matches_active_filters = False
                    else:
                        speed_ddr_type = speed_dimensions['ddr_type']
                        speed_mhz = speed_dimensions['mhz']
                        if min_speed_ddr_type is not None and speed_ddr_type < min_speed_ddr_type:
                            item_matches_active_filters = False
                        if max_speed_ddr_type is not None and speed_ddr_type > max_speed_ddr_type:
                            item_matches_active_filters = False
                        if min_speed_mhz is not None and speed_mhz < min_speed_mhz:
                            item_matches_active_filters = False
                        if max_speed_mhz is not None and speed_mhz > max_speed_mhz:
                            item_matches_active_filters = False

                if item_matches_active_filters and (min_cas_latency is not None or max_cas_latency is not None):
                    if cas_latency_value is None:
                        item_matches_active_filters = False
                    else:
                        if min_cas_latency is not None and cas_latency_value < min_cas_latency:
                            item_matches_active_filters = False
                        if max_cas_latency is not None and cas_latency_value > max_cas_latency:
                            item_matches_active_filters = False

                if item_matches_active_filters and (min_first_word_latency is not None or max_first_word_latency is not None):
                    if first_word_latency_value is None:
                        item_matches_active_filters = False
                    else:
                        if min_first_word_latency is not None and first_word_latency_value < min_first_word_latency:
                            item_matches_active_filters = False
                        if max_first_word_latency is not None and first_word_latency_value > max_first_word_latency:
                            item_matches_active_filters = False

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

    # Compute percentile per category and map percentile (0-100) to value score (0-5).
    sorted_value_samples_by_table = {
        table_name: values
        for table_name, values in value_samples_by_table.items()
        if values
    }

    has_value_for_selected_category = bool(selected_category and sorted_value_samples_by_table.get(selected_category))
    if not sort_by:
        sort_by = 'value_best' if has_value_for_selected_category else 'alphabetical_asc'

    for item in all_results:
        table_name = item.get('table_name')
        table_values = sorted_value_samples_by_table.get(table_name)
        item_percentile = _percentile_rank(table_values, item.get('value_raw'))
        if item_percentile is None:
            continue

        normalized_value = (item_percentile / 100.0) * 5.0
        if normalized_value is None:
            continue

        item['value_percentile'] = round(item_percentile, 3)
        normalized_value = round(normalized_value, 3)
        item['value_normalized'] = normalized_value
        value_range['min'] = min(value_range['min'], normalized_value)
        value_range['max'] = max(value_range['max'], normalized_value)

    if value_range['min'] != float('inf'):
        value_range['min'] = 0.0
        value_range['max'] = 5.0

    if module_count_range['min'] != float('inf'):
        module_count_range['min'] = int(module_count_range['min'])
        module_count_range['max'] = int(module_count_range['max'])
    else:
        module_count_range = {'min': 1, 'max': 8}

    if module_size_range['min'] == float('inf'):
        module_size_range = {'min': 4, 'max': 64}

    if speed_ddr_type_range['min'] != float('inf'):
        speed_ddr_type_range['min'] = int(speed_ddr_type_range['min'])
        speed_ddr_type_range['max'] = int(speed_ddr_type_range['max'])
    else:
        speed_ddr_type_range = {'min': 0, 'max': 0}

    if speed_mhz_range['min'] != float('inf'):
        speed_mhz_range['min'] = int(speed_mhz_range['min'])
        speed_mhz_range['max'] = int(speed_mhz_range['max'])
    else:
        speed_mhz_range = {'min': 0, 'max': 0}

    if cas_latency_range['min'] != float('inf'):
        cas_latency_range['min'] = round(cas_latency_range['min'], 3)
        cas_latency_range['max'] = round(cas_latency_range['max'], 3)
    else:
        cas_latency_range = {'min': 0, 'max': 0}

    if first_word_latency_range['min'] != float('inf'):
        first_word_latency_range['min'] = round(first_word_latency_range['min'], 3)
        first_word_latency_range['max'] = round(first_word_latency_range['max'], 3)
    else:
        first_word_latency_range = {'min': 0, 'max': 0}

    # Apply numeric range filters after collecting latest rows per item
    if min_price is not None or max_price is not None or min_value is not None or max_value is not None:
        filtered_results = []
        for item in all_results:
            try:
                item_price = float(str(item.get('price', 0)).replace('$', '').replace(',', '') or 0)
            except:
                item_price = None

            try:
                item_value = item.get('value_normalized')
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
        all_results.sort(key=lambda x: float(x.get('value_normalized') or 0), reverse=True)
    elif sort_by == 'value_worst':
        all_results.sort(key=lambda x: float(x.get('value_normalized') or 0))

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
    if min_modules_count is not None:
        pagination_query_items.append(('min_modules_count', min_modules_count))
    if max_modules_count is not None:
        pagination_query_items.append(('max_modules_count', max_modules_count))
    if min_modules_size is not None:
        pagination_query_items.append(('min_modules_size', min_modules_size))
    if max_modules_size is not None:
        pagination_query_items.append(('max_modules_size', max_modules_size))
    if min_speed_ddr_type is not None:
        pagination_query_items.append(('min_speed_ddr_type', min_speed_ddr_type))
    if max_speed_ddr_type is not None:
        pagination_query_items.append(('max_speed_ddr_type', max_speed_ddr_type))
    if min_speed_mhz is not None:
        pagination_query_items.append(('min_speed_mhz', min_speed_mhz))
    if max_speed_mhz is not None:
        pagination_query_items.append(('max_speed_mhz', max_speed_mhz))
    if min_cas_latency is not None:
        pagination_query_items.append(('min_cas_latency', min_cas_latency))
    if max_cas_latency is not None:
        pagination_query_items.append(('max_cas_latency', max_cas_latency))
    if min_first_word_latency is not None:
        pagination_query_items.append(('min_first_word_latency', min_first_word_latency))
    if max_first_word_latency is not None:
        pagination_query_items.append(('max_first_word_latency', max_first_word_latency))
    pagination_query_string = urlencode(pagination_query_items, doseq=True)
    
    if price_range['min'] == float('inf'):
        price_range['min'] = 0
    if value_range['min'] == float('inf'):
        value_range['min'] = 0

    show_value_analysis = has_value_for_selected_category
    
    return render_template('products.html', 
                           results=paginated_results,
                           query=query, 
                           filter_options=sorted_filters, 
                           filter_labels=filter_labels,
                           active_filters=flat_active_filters,
                           all_active_filters=active_filter_values,
                           sort_by=sort_by,
                           selected_category=selected_category,
                           show_memory_analysis=show_value_analysis,
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
                           min_modules_count=min_modules_count,
                           max_modules_count=max_modules_count,
                           min_modules_size=min_modules_size,
                           max_modules_size=max_modules_size,
                           module_count_range=module_count_range,
                           module_size_range=module_size_range,
                           min_speed_ddr_type=min_speed_ddr_type,
                           max_speed_ddr_type=max_speed_ddr_type,
                           min_speed_mhz=min_speed_mhz,
                           max_speed_mhz=max_speed_mhz,
                           min_cas_latency=min_cas_latency,
                           max_cas_latency=max_cas_latency,
                           min_first_word_latency=min_first_word_latency,
                           max_first_word_latency=max_first_word_latency,
                           speed_ddr_type_range=speed_ddr_type_range,
                           speed_mhz_range=speed_mhz_range,
                           cas_latency_range=cas_latency_range,
                           first_word_latency_range=first_word_latency_range,
                           from_build=from_build)


@app.route('/products')
def products():
    return search()


@app.route('/trends')
def trends():
    trend_data = []
    for table_name, label in TREND_CATEGORY_LABELS.items():
        trend_series = _build_trend_series(table_name)
        trend_data.append({
            'key': table_name,
            'label': label,
            'labels': trend_series['labels'],
            'prices': trend_series['prices'],
            'min_prices': trend_series['min_prices'],
            'max_prices': trend_series['max_prices'],
            'sample_counts': trend_series['sample_counts'],
        })

    return render_template('trends.html', trend_data=trend_data)


@app.route('/build')
def build_page():
    build_categories = [
        {'key': key, 'label': label}
        for key, label in BUILD_TABLE_LABELS.items()
    ]
    return render_template('build.html', build_categories=build_categories)


@app.route('/api/builds', methods=['GET', 'POST'])
@login_required
def saved_builds_api():
    if request.method == 'GET':
        builds = (
            SavedBuild.query
            .filter_by(user_id=current_user.id)
            .order_by(SavedBuild.updated_at.desc(), SavedBuild.id.desc())
            .all()
        )
        return jsonify([
            {
                'id': build.id,
                'build_name': build.build_name,
                'build_data': build.build_data or [],
                'item_count': len(build.build_data or []),
                'created_at': build.created_at.isoformat() if build.created_at else None,
                'updated_at': build.updated_at.isoformat() if build.updated_at else None,
            }
            for build in builds
        ])

    payload = request.get_json(silent=True) or {}
    build_name = str(payload.get('build_name', '')).strip()
    build_data = payload.get('build_data', [])

    if not build_name:
        return jsonify({'error': 'Build name is required.'}), 400
    if not isinstance(build_data, list):
        return jsonify({'error': 'Build data must be a list.'}), 400

    saved_build = SavedBuild(
        user_id=current_user.id,
        build_name=build_name,
        build_data=build_data,
    )
    db.session.add(saved_build)
    db.session.commit()

    return jsonify({
        'id': saved_build.id,
        'build_name': saved_build.build_name,
        'build_data': saved_build.build_data or [],
        'created_at': saved_build.created_at.isoformat() if saved_build.created_at else None,
    }), 201


@app.route('/api/builds/<int:build_id>', methods=['GET', 'PUT', 'DELETE'])
@login_required
def saved_build_detail(build_id):
    saved_build = SavedBuild.query.filter_by(id=build_id, user_id=current_user.id).first_or_404()

    if request.method == 'PUT':
        payload = request.get_json(silent=True) or {}
        build_name = str(payload.get('build_name', '')).strip()

        if not build_name:
            return jsonify({'error': 'Build name is required.'}), 400

        saved_build.build_name = build_name
        db.session.commit()
        return jsonify({
            'id': saved_build.id,
            'build_name': saved_build.build_name,
            'build_data': saved_build.build_data or [],
            'updated_at': saved_build.updated_at.isoformat() if saved_build.updated_at else None,
        })

    if request.method == 'DELETE':
        db.session.delete(saved_build)
        db.session.commit()
        return jsonify({'status': 'deleted', 'id': build_id})

    return jsonify({
        'id': saved_build.id,
        'build_name': saved_build.build_name,
        'build_data': saved_build.build_data or [],
        'created_at': saved_build.created_at.isoformat() if saved_build.created_at else None,
        'updated_at': saved_build.updated_at.isoformat() if saved_build.updated_at else None,
    })


@app.route('/history')
def item_history():
    table_type = request.args.get('table_type')
    category = (table_type or '').strip().lower().replace('-', '_')
    passed_value_normalized = request.args.get('value_normalized')

    ignored = ['table_type', 'price_per_gb', 'price/gb', 'microarchitecture', 'smt', 'value_normalized']
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

    product_name = filters.get('name')
    if not product_name and rows:
        product_name = rows[0].get('name')
    
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

    latest_value_normalized = None
    if category and _table_exists(category):
        group_cols = _category_group_columns(category)
        baseline_values = _sorted_value_baseline_for_table(category, group_cols)
        latest_row = rows[-1] if rows else None
        latest_value_raw = _safe_parse_price(latest_row.get('value')) if latest_row else None
        latest_percentile = _percentile_rank(baseline_values, latest_value_raw)
        if latest_percentile is not None:
            latest_value_normalized = round((latest_percentile / 100.0) * 5.0, 3)

    if latest_value_normalized is None and passed_value_normalized not in (None, '', 'None'):
        try:
            latest_value_normalized = float(passed_value_normalized)
        except (TypeError, ValueError):
            latest_value_normalized = None

    return render_template('item_history.html', 
                           history=rows, 
                           specs=filters,
                           name=product_name,
                           category=category,
                           latest_price=prices[-1] if prices else None,
                           value_normalized=latest_value_normalized,
                           dates=labels,
                           prices=prices)

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
    data = new_motherboard_csv_reader.to_dict()
    labels = data['name']
    price = data['price']
    return render_template('motherboard_page.html', labels=labels, price=price)

@app.route('/motherboardgraphs', methods=['GET', 'POST'])
def motherboard_graphs():
    """Render the motherboard page."""
    return render_template('motherboard_graphs.html')

@app.route('/powersupply', methods=['GET', 'POST'])
def powersupply_page():
    data = new_psu_csv_reader.to_dict()
    labels = data['name']
    price = data['price']
    return render_template('powersupply_page.html', labels=labels, price=price)

@app.route('/powersupplygraphs', methods=['GET', 'POST'])
def powersupply_graphs():
    """Render the power supply page."""
    return render_template('powersupply_graphs.html')

