import subprocess
import os
import sys
from .celery_app import make_celery
from app import app

celery = make_celery(app)


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
        "wayback_newegg_functional",
        "-a",
        f"product_url={product_url}",
        "-a",
        f"category={category}",
    ]

    try:
        result = subprocess.run(
            cmd,
            cwd=scrapy_project_dir,
            capture_output=True,
            text=True,
            timeout=3600,
            env={**os.environ, 'PYTHONPATH': os.path.join(project_root, 'src')}
        )
        if result.returncode != 0:
            # Return both stdout and stderr for debugging
            output = (result.stdout or "") + "\n" + (result.stderr or "")
            return f"Scrapy failed with code {result.returncode}:\n{output}"
        return f"crawled {product_url}. Output:\n{result.stdout or ''}"
    except subprocess.TimeoutExpired:
        return f"Crawl timeout for {product_url}"
    except Exception as e:
        return f"Crawl failed: {str(e)}"


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
            capture_output=True,
            text=True,
            timeout=3600,
            env={**os.environ, 'PYTHONPATH': os.path.join(project_root, 'src')}
        )
        if result.returncode != 0:
            output = (result.stdout or "") + "\n" + (result.stderr or "")
            return f"Tech news crawl failed with code {result.returncode}:\n{output}"
        return "Tech news crawl completed successfully."
    except subprocess.TimeoutExpired:
        return "Tech news crawl timed out."
    except Exception as e:
        return f"Tech news crawl failed: {str(e)}"