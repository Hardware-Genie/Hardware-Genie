import subprocess
import os
import sys
import re
import json
import tempfile
import uuid
from urllib.parse import urlparse
from .celery_app import make_celery
from app import app

celery = make_celery(app)


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
    return _shorten_name_from_slug(slug)


def _shorten_name_from_slug(slug_text):
    if not slug_text:
        return None

    tokens = [t for t in re.split(r'\s+', str(slug_text).strip()) if t]
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


def _normalized_task_db_uri(project_root):
    configured = app.config.get('SQLALCHEMY_DATABASE_URI', '').strip()
    db_uri = configured or os.environ.get('DATABASE_URL', '').strip()

    if not db_uri:
        absolute_path = os.path.abspath(os.path.join(project_root, 'instance', 'parts.db')).replace('\\', '/')
        return f"sqlite:///{absolute_path}"

    if db_uri.startswith('postgres://'):
        db_uri = db_uri.replace('postgres://', 'postgresql://', 1)

    if db_uri.startswith('sqlite:///'):
        sqlite_path = db_uri[len('sqlite:///'):]
        if sqlite_path and sqlite_path != ':memory:' and not os.path.isabs(sqlite_path):
            if sqlite_path in ('parts.db', './parts.db'):
                sqlite_path = os.path.join(project_root, 'instance', 'parts.db')
            else:
                sqlite_path = os.path.join(project_root, sqlite_path)
            db_uri = f"sqlite:///{os.path.abspath(sqlite_path).replace('\\', '/')}"

    return db_uri


def _load_summary(summary_file):
    if not summary_file or not os.path.exists(summary_file):
        return {
            "canonical_name": None,
            "inserted": 0,
            "skipped_total": 0,
            "skipped_existing": 0,
            "skipped_invalid": 0,
            "processed_total": 0,
        }

    try:
        with open(summary_file, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        data = {}
    finally:
        try:
            os.remove(summary_file)
        except OSError:
            pass

    return {
        "canonical_name": data.get("canonical_name"),
        "inserted": int(data.get("inserted") or 0),
        "skipped_total": int(data.get("skipped_total") or 0),
        "skipped_existing": int(data.get("skipped_existing") or 0),
        "skipped_invalid": int(data.get("skipped_invalid") or 0),
        "processed_total": int(data.get("processed_total") or 0),
    }


@celery.task(bind=True)
def crawl_spider(self, product_url, category):
    """Celery task that runs the WaybackNeweggSpider via subprocess.

    This invokes the spider as a separate scrapy process, ensuring
    pipelines (CSV, SQLite) flush and close properly before returning.
    Calling ``crawl_spider.delay(url, category)`` does not block the web request.
    """
    # Get the scrapy project directory (where scrapy.cfg lives)
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    scrapy_project_dir = os.path.join(project_root, "src/app/wayback_newegg_scrapy")

    # Use the CURRENT Python interpreter (which is in the venv)
    python_exe = sys.executable

    # Run scrapy crawl command from the scrapy project directory
    cmd = [
        python_exe,
        "-m",
        "scrapy",
        "crawl",
        "wayback_newegg",
        "-a",
        f"product_url={product_url}",
        "-a",
        f"category={category}",
    ]

    try:
        db_uri = _normalized_task_db_uri(project_root)
        summary_file = os.path.join(tempfile.gettempdir(), f"scrape_summary_{uuid.uuid4().hex}.json")
        result = subprocess.run(
            cmd,
            cwd=scrapy_project_dir,
            timeout=3600,
            env={
                **os.environ,
                'PYTHONPATH': os.path.join(project_root, 'src'),
                'DATABASE_URL': db_uri,
                'SCRAPE_SUMMARY_FILE': summary_file,
            }
        )
        # this hangs on queues
        #result = subprocess.run(
        #    cmd,
        #    cwd=scrapy_project_dir,  # Run from scrapy project directory
        #    capture_output=True,
        #    text=True,
        #    timeout=3600,  # 1 hour timeout
        #    env={**os.environ, 'PYTHONPATH': os.path.join(project_root, 'src')},  # Set PYTHONPATH
        #)
        if result.returncode != 0:
            # Return both stdout and stderr for debugging
            stdout = getattr(result, 'stdout', '') or ''
            stderr = getattr(result, 'stderr', '') or ''
            output = f"{stdout}\n{stderr}".strip()
            return {
                "status": "failed",
                "message": f"Scrapy failed with code {result.returncode}",
                "details": output,
                "category": category,
                "product_url": product_url,
                "name": _slug_name_from_url(product_url),
                "summary": _load_summary(summary_file),
            }
        return {
            "status": "success",
            "message": f"Crawled {product_url}",
            "category": category,
            "product_url": product_url,
            "name": _slug_name_from_url(product_url),
            "summary": _load_summary(summary_file),
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "failed",
            "message": f"Crawl timeout for {product_url}",
            "category": category,
            "product_url": product_url,
            "name": _slug_name_from_url(product_url),
            "summary": {
                "canonical_name": None,
                "inserted": 0,
                "skipped_total": 0,
                "skipped_existing": 0,
                "skipped_invalid": 0,
                "processed_total": 0,
            },
        }
    except Exception as e:
        return {
            "status": "failed",
            "message": f"Crawl failed: {str(e)}",
            "category": category,
            "product_url": product_url,
            "name": _slug_name_from_url(product_url),
            "summary": {
                "canonical_name": None,
                "inserted": 0,
                "skipped_total": 0,
                "skipped_existing": 0,
                "skipped_invalid": 0,
                "processed_total": 0,
            },
        }


@celery.task(bind=True)
def crawl_tech_news(self, source=None, keywords=None, max_articles=None):
    """Celery task that runs the tech_news spider via subprocess."""
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    scrapy_project_dir = os.path.join(project_root, "src/app/wayback_newegg_scrapy")
    python_exe = sys.executable

    cmd = [
        python_exe,
        "-m",
        "scrapy",
        "crawl",
        "tech_news",
    ]

    if source:
        cmd.extend(["-a", f"source={source}"])
    if keywords:
        cmd.extend(["-a", f"keywords={keywords}"])
    if max_articles is not None:
        cmd.extend(["-a", f"max_articles={int(max_articles)}"])

    try:
        result = subprocess.run(
            cmd,
            cwd=scrapy_project_dir,
            timeout=3600,
            env={**os.environ, 'PYTHONPATH': os.path.join(project_root, 'src')}
        )
        if result.returncode != 0:
            output = result.stdout + "\n" + result.stderr
            return f"Tech news crawl failed with code {result.returncode}:\n{output}"
        return "Tech news crawl completed successfully."
    except subprocess.TimeoutExpired:
        return "Tech news crawl timed out."
    except Exception as e:
        return f"Tech news crawl failed: {str(e)}"