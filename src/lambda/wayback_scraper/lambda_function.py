"""Lambda handler for the wayback_newegg Scrapy spider.

Runs the spider as a subprocess (same approach as tasks.py) to avoid
Twisted reactor restart issues in warm Lambda containers.

Event payload (all optional):
  {
    "products": [{"name": "...", "url": "...", "category": "..."}],
    "from_date": "20200101",
    "to_date": null,
    "max_snapshots": 50
  }
If "products" is omitted the spider falls back to its hardcoded PRODUCTS list.
"""

import boto3
import json
import os
import subprocess
import sys


SCRAPY_PROJECT_DIR = os.path.join(os.path.dirname(__file__), "wayback_newegg_scrapy")


def _database_url():
    db_url = os.environ.get("DATABASE_URL", "")
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    return db_url


def handler(event, context):
    event = event or {}
    products = event.get("products", [])
    env = {
        **os.environ,
        "DATABASE_URL": _database_url(),
        "PYTHONPATH": os.path.dirname(__file__),
    }

    if event.get("from_date"):
        env["WAYBACK_FROM_DATE"] = event["from_date"]
    if event.get("to_date"):
        env["WAYBACK_TO_DATE"] = event["to_date"]
    if event.get("max_snapshots") is not None:
        env["WAYBACK_MAX_SNAPSHOTS"] = str(event["max_snapshots"])

    targets = products if products else [{}]
    results = []

    for product in targets:
        cmd = [sys.executable, "-m", "scrapy", "crawl", "wayback_newegg"]
        if product.get("url"):
            cmd += ["-a", f"product_url={product['url']}"]
        if product.get("name"):
            cmd += ["-a", f"product_name={product['name']}"]
        if product.get("category"):
            cmd += ["-a", f"category={product['category']}"]

        try:
            result = subprocess.run(
                cmd,
                cwd=SCRAPY_PROJECT_DIR,
                env=env,
                timeout=int(os.environ.get("SCRAPY_TIMEOUT", "840")),
            )
            results.append({
                "product": product,
                "status": "success" if result.returncode == 0 else "failed",
                "returncode": result.returncode,
            })
        except subprocess.TimeoutExpired:
            results.append({"product": product, "status": "timeout"})
        except Exception as exc:
            results.append({"product": product, "status": "error", "message": str(exc)})

    value_analysis_fn = os.environ.get("VALUE_ANALYSIS_FUNCTION_NAME", "")
    if value_analysis_fn:
        lambda_client = boto3.client("lambda", region_name=os.environ.get("AWS_REGION", "us-west-1"))
        seen = set()
        for r in results:
            category = r.get("product", {}).get("category", "")
            if r.get("status") == "success" and category and category not in seen:
                seen.add(category)
                lambda_client.invoke(
                    FunctionName=value_analysis_fn,
                    InvocationType="Event",
                    Payload=json.dumps({"table": category}).encode(),
                )

    return {"results": results}
