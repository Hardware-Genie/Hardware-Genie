import os
import sys

# make sure the top‑level `src` directory (the parent of this file) is on
# sys.path so that `import app` works regardless of the current working
#directory. celery often executes from the project root, which doesn't
# include `src` by default.
base = os.path.dirname(os.path.dirname(__file__))  # .../src/app -> .../src
if base not in sys.path:
    sys.path.insert(0, base)

from celery import Celery
import os


def make_celery(app=None):
    """Create and configure a Celery instance.

    The broker URL and backend can be configured via environment variables
    (e.g. CELERY_BROKER_URL, CELERY_RESULT_BACKEND). By default we use
    Redis on localhost so you'll need a running Redis server for development.
    """
    app = app or None
    celery = Celery(
        app.import_name if app else __name__,
        broker=os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0'),
        backend=os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0'),
    )

    # Optionally load configuration from flask app config
    if app is not None:
        celery.conf.update(app.config)

    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            # ensure tasks run within Flask application context
            if app is not None:
                with app.app_context():
                    return self.run(*args, **kwargs)
            else:
                return self.run(*args, **kwargs)

    celery.Task = ContextTask
    return celery
