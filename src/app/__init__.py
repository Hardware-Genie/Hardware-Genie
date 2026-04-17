import logging

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from sqlalchemy import create_engine, inspect, text
import os
import pandas as pd


def _resolve_database_uri():
    db_uri = os.getenv('DATABASE_URL', 'sqlite:///parts.db').strip()
    if db_uri.startswith('postgres://'):
        db_uri = db_uri.replace('postgres://', 'postgresql://', 1)
    return db_uri


def _is_postgres_uri(db_uri):
    return db_uri.startswith('postgresql://') or db_uri.startswith('postgresql+')


def _target_has_any_data(target_engine, ignored_tables=None):
    ignored_tables = ignored_tables or set()
    target_inspector = inspect(target_engine)
    table_names = target_inspector.get_table_names()

    if not table_names:
        return False

    with target_engine.connect() as conn:
        for table_name in table_names:
            if table_name in ignored_tables:
                continue
            row = conn.execute(text(f'SELECT 1 FROM "{table_name}" LIMIT 1')).first()
            if row is not None:
                return True
    return False


def _target_has_seed_tables_and_data(target_engine, source_table_names):
    target_inspector = inspect(target_engine)
    target_table_names = set(target_inspector.get_table_names())

    for table_name in source_table_names:
        if table_name not in target_table_names:
            return False

    with target_engine.connect() as conn:
        for table_name in source_table_names:
            row = conn.execute(text(f'SELECT 1 FROM "{table_name}" LIMIT 1')).first()
            if row is None:
                return False

    return True


def _table_has_rows(conn, table_name):
    row = conn.execute(text(f'SELECT 1 FROM "{table_name}" LIMIT 1')).first()
    return row is not None


def _seed_postgres_from_sqlite_if_needed(db_uri):
    should_seed = os.getenv('SEED_SQLITE_TO_RDS', 'true').lower() in ('1', 'true', 'yes', 'on')
    if not should_seed or not _is_postgres_uri(db_uri):
        return

    project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    default_sqlite_path = os.path.join(project_root, 'instance', 'parts.db')
    sqlite_path = os.getenv('SQLITE_SEED_PATH', default_sqlite_path)

    if not os.path.exists(sqlite_path):
        app.logger.warning('SQLite seed file not found at %s. Skipping RDS seed.', sqlite_path)
        return

    target_engine = create_engine(db_uri)

    source_engine = create_engine(f'sqlite:///{sqlite_path}')
    source_inspector = inspect(source_engine)
    table_names = [
        table_name for table_name in source_inspector.get_table_names()
        if not table_name.startswith('sqlite_')
    ]

    expected_core_tables = {
        'cpu',
        'memory',
        'video_card',
        'motherboard',
        'power_supply',
        'internal_hard_drive',
        'users',
        'saved_builds',
    }

    missing_source_tables = sorted(list(expected_core_tables - set(table_names)))
    if missing_source_tables:
        app.logger.warning(
            'SQLite seed source is missing expected tables: %s',
            ', '.join(missing_source_tables)
        )

    app.logger.info('SQLite seed source tables: %s', ', '.join(sorted(table_names)))

    conn = target_engine.connect()
    try:
        conn.execute(text('''
            CREATE TABLE IF NOT EXISTS app_seed_status (
                id INTEGER PRIMARY KEY,
                seeded BOOLEAN NOT NULL DEFAULT FALSE,
                seeded_at TIMESTAMP NULL
            )
        '''))

        already_seeded = conn.execute(
            text('SELECT seeded FROM app_seed_status WHERE id = 1')
        ).scalar()
        if already_seeded and _target_has_seed_tables_and_data(target_engine, table_names):
            app.logger.info('Seed status already marked complete and source tables exist. Skipping SQLite seed migration.')
            conn.commit()
            return

        if _target_has_seed_tables_and_data(target_engine, table_names):
            conn.execute(text('''
                INSERT INTO app_seed_status (id, seeded, seeded_at)
                VALUES (1, TRUE, NOW())
                ON CONFLICT (id)
                DO UPDATE SET seeded = EXCLUDED.seeded, seeded_at = EXCLUDED.seeded_at
            '''))
            app.logger.info('Target database already contains seeded source tables. Marked seed status as complete.')
            conn.commit()
            return

        target_inspector = inspect(target_engine)
        for table_name in table_names:
            df = pd.read_sql_query(f'SELECT * FROM "{table_name}"', source_engine)
            source_row_count = len(df.index)
            target_has_table = target_inspector.has_table(table_name)
            target_has_rows = target_has_table and _table_has_rows(conn, table_name)

            if source_row_count == 0:
                if not target_has_table:
                    df.to_sql(table_name, target_engine, if_exists='append', index=False)
                    app.logger.info('Created empty target table %s from SQLite schema.', table_name)
                else:
                    app.logger.info('Source table %s is empty; leaving existing target data unchanged.', table_name)
                continue

            if target_has_table and not target_has_rows:
                app.logger.info('Backfilling empty target table %s from SQLite.', table_name)
            elif target_has_table:
                conn.execute(text(f'TRUNCATE TABLE "{table_name}" RESTART IDENTITY CASCADE'))

            df.to_sql(table_name, target_engine, if_exists='append', index=False, method='multi', chunksize=1000)
            app.logger.info('Seeded table %s with %s rows.', table_name, source_row_count)

        conn.execute(text('''
            INSERT INTO app_seed_status (id, seeded, seeded_at)
            VALUES (1, TRUE, NOW())
            ON CONFLICT (id)
            DO UPDATE SET seeded = EXCLUDED.seeded, seeded_at = EXCLUDED.seeded_at
        '''))
        app.logger.info('Seeded PostgreSQL database from SQLite file %s.', sqlite_path)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


app = Flask('Hardware Genie')
app.secret_key = os.getenv('SECRET_KEY', 'you will never know')
app.logger.setLevel(logging.INFO)

app.jinja_env.add_extension('jinja2.ext.loopcontrols')

# db initialization
app.config['SQLALCHEMY_DATABASE_URI'] = _resolve_database_uri()
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# models initialization
from app import models
with app.app_context():
    db.create_all()
    _seed_postgres_from_sqlite_if_needed(app.config['SQLALCHEMY_DATABASE_URI'])

# login manager
login_manager = LoginManager()
login_manager.init_app(app)

from app.models import User

# user_loader callback
@login_manager.user_loader
def load_user(id):
    try: 
        return db.session.query(User).filter(User.id==id).one()
    except: 
        return None

from app import routes