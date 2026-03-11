## Background Crawling with Celery

The web scraper is now executed asynchronously by a Celery worker so the
Flask server does not block when you submit the form on `/scraper`.

### Setup

1. Install the new dependencies:

   ```sh
   pip install -r requirements.txt
   ```

2. **Run a Redis server** (default broker/backend). The Python `redis`
   package installed via `pip` is only the client library; you still need an
   actual Redis **server process** listening on `localhost:6379`.

   On Windows there are a few options:

   * Install Redis via WSL (e.g. `sudo apt install redis-server`) and start it
     with `redis-server` or `sudo service redis-server start`.
   * Run Redis in Docker:

     ```powershell
     docker run --rm -p 6379:6379 redis:8
     ```

     To verify it's running and responding:

     ```powershell
     # Find the container name (e.g. 'determined_sammet')
     docker ps

     # Ping Redis inside the container
     docker exec <container_name> redis-cli ping
     # Should reply: PONG
     ```

   * Use a cloud-hosted Redis service and point `CELERY_BROKER_URL`/`
     CELERY_RESULT_BACKEND` at it instead.

   If you see errors like:

   > ``consumer: Cannot connect to redis://localhost:6379/0: Error 10061``

   it means the worker tried to reach Redis but no server was listening. Make
   sure the server is running and accessible before starting the Celery
   worker.

   The URL can be changed via environment variables if you don't want to use
   localhost.

3. Start a worker. The worker process needs to be able to import the
   `app` package located under `src/`. Because we added code to
   `celery_app.py` that inserts the `src` directory on `sys.path`, you can
   simply run the worker from the project root without any extra setup. For
   example, in **PowerShell**:

   ```powershell
   # from repository root (the folder that contains `src` and `static`)
   celery -A app.tasks.celery worker --loglevel=info
   ```

   If you prefer to make the path explicit, set `PYTHONPATH` before invoking
   celery. In PowerShell the syntax is:

   ```powershell
   $env:PYTHONPATH = 'src'
   celery -A app.tasks.celery worker --pool=solo --loglevel=info
   ```

   > ⚠️ Do **not** `cd src` when starting the worker; doing so changes the
   > current working directory and makes relative file paths (e.g. the
   > `static/data` folder) resolve incorrectly. Running from the project root
   > keeps file paths consistent for both the web app and the worker.

   The import-path hack in `celery_app` provides an extra safety net, but the
   above commands are the recommended ways to launch the worker.

4. Launch the Flask server as usual (`flask run --debug`) and submit the
   scraper form; the job will run in the background.

You can monitor progress via the worker logs or inspect task results if you
need them.

