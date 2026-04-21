import subprocess
import os
import sys
from .celery_app import make_celery
from app import app

celery = make_celery(app)


@celery.task(bind=True)
def crawl_spider(self, product_name, product_url):
    """Celery task that runs the WaybackNeweggSpider via subprocess.

    This invokes the spider as a separate scrapy process, ensuring
    pipelines (CSV, SQLite) flush and close properly before returning.
    Calling ``crawl_spider.delay(name, url)`` does not block the web request.
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
        f"product_name={product_name}",
        "-a",
        f"product_url={product_url}",
    ]

    try:
        result = subprocess.run(
            cmd,
            cwd=scrapy_project_dir,
            timeout=3600,
            env={**os.environ, 'PYTHONPATH': os.path.join(project_root, 'src')}
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
            output = result.stdout + "\n" + result.stderr
            return f"Scrapy failed with code {result.returncode}:\n{output}"
        return f"crawled {product_name}. Output:\n{result.stdout}"
    except subprocess.TimeoutExpired:
        return f"Crawl timeout for {product_name}"
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