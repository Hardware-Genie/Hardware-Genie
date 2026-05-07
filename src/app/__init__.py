import logging

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_login import current_user
from sqlalchemy import create_engine, inspect, text
import os


def _resolve_database_uri():
    db_uri = os.getenv('DATABASE_URL', 'sqlite:///parts.db').strip()
    if db_uri.startswith('postgres://'):
        db_uri = db_uri.replace('postgres://', 'postgresql://', 1)

    if db_uri.startswith('sqlite:///'):
        sqlite_path = db_uri[len('sqlite:///'):]
        if sqlite_path and sqlite_path != ':memory:' and not os.path.isabs(sqlite_path):
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            if sqlite_path in ('parts.db', './parts.db'):
                sqlite_path = os.path.join(project_root, 'instance', 'parts.db')
            else:
                sqlite_path = os.path.join(project_root, sqlite_path)
            normalized_sqlite_path = os.path.abspath(sqlite_path).replace('\\', '/')
            db_uri = f"sqlite:///{normalized_sqlite_path}"

    return db_uri


def _is_postgres_uri(db_uri):
    return db_uri.startswith('postgresql://') or db_uri.startswith('postgresql+')


def _table_has_rows(engine, table_name):
    with engine.connect() as conn:
        return conn.execute(text(f'SELECT 1 FROM "{table_name}" LIMIT 1')).first() is not None


def _copy_table_via_csv(sqlite_conn, pg_raw_conn, table_name, columns):
    """Stream rows from SQLite into Postgres using COPY for maximum throughput."""
    import csv
    import io

    cursor = sqlite_conn.execute(f'SELECT * FROM "{table_name}"')
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL)
    row_count = 0
    for row in cursor:
        writer.writerow(['' if v is None else v for v in row])
        row_count += 1

    if row_count == 0:
        return 0

    buf.seek(0)
    col_list = ', '.join(f'"{c}"' for c in columns)
    pg_cursor = pg_raw_conn.cursor()
    pg_cursor.copy_expert(
        f'COPY "{table_name}" ({col_list}) FROM STDIN WITH (FORMAT csv, NULL \'\')',
        buf,
    )
    pg_cursor.close()
    return row_count


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
        t for t in source_inspector.get_table_names()
        if not t.startswith('sqlite_')
    ]
    app.logger.info('SQLite seed source tables: %s', ', '.join(sorted(table_names)))

    # Use a raw psycopg2 connection for COPY support
    raw_conn = target_engine.raw_connection()
    sqlite_conn = source_engine.raw_connection()
    try:
        with target_engine.connect() as sa_conn:
            sa_conn.execute(text('''
                CREATE TABLE IF NOT EXISTS app_seed_status (
                    id INTEGER PRIMARY KEY,
                    seeded BOOLEAN NOT NULL DEFAULT FALSE,
                    seeded_at TIMESTAMP NULL
                )
            '''))
            already_seeded = sa_conn.execute(
                text('SELECT seeded FROM app_seed_status WHERE id = 1')
            ).scalar()
            sa_conn.commit()

        all_done = True
        for table_name in table_names:
            target_inspector = inspect(target_engine)  # refresh each iteration
            target_has_rows = (
                target_inspector.has_table(table_name)
                and _table_has_rows(target_engine, table_name)
            )
            if target_has_rows:
                app.logger.info('Table %s already has data, skipping.', table_name)
                continue

            all_done = False
            columns = [c['name'] for c in source_inspector.get_columns(table_name)]
            with target_engine.connect() as schema_conn:
                if not target_inspector.has_table(table_name):
                    # Build CREATE TABLE from SQLite schema
                    col_defs = []
                    for col in source_inspector.get_columns(table_name):
                        col_defs.append(f'"{col["name"]}" {str(col["type"])}')
                    schema_conn.execute(text(f'CREATE TABLE "{table_name}" ({", ".join(col_defs)})'))
                else:
                    # Add any missing columns
                    target_cols = {c['name'] for c in inspect(target_engine).get_columns(table_name)}
                    for col in source_inspector.get_columns(table_name):
                        if col['name'] not in target_cols:
                            schema_conn.execute(text(f'ALTER TABLE "{table_name}" ADD COLUMN "{col["name"]}" {str(col["type"])}'))
                schema_conn.commit()
            row_count = _copy_table_via_csv(sqlite_conn, raw_conn, table_name, columns)
            raw_conn.commit()
            app.logger.info('Seeded table %s with %s rows.', table_name, row_count)

            # Reset the PostgreSQL sequence so auto-increment starts after the seeded data
            with target_engine.connect() as seq_conn:
                seq_conn.execute(text(
                    f"SELECT setval(pg_get_serial_sequence('{table_name}', 'id'), "
                    f"COALESCE((SELECT MAX(id) FROM \"{table_name}\"), 0) + 1, false)"
                ))
                seq_conn.commit()

        if already_seeded and all_done:
            app.logger.info('All tables already seeded, skipping.')
            return

        with target_engine.connect() as sa_conn:
            sa_conn.execute(text('''
                INSERT INTO app_seed_status (id, seeded, seeded_at)
                VALUES (1, TRUE, NOW())
                ON CONFLICT (id)
                DO UPDATE SET seeded = EXCLUDED.seeded, seeded_at = EXCLUDED.seeded_at
            '''))
            sa_conn.commit()
        app.logger.info('Seeded PostgreSQL database from SQLite file %s.', sqlite_path)
    except Exception:
        raw_conn.rollback()
        raise
    finally:
        raw_conn.close()
        sqlite_conn.close()


app = Flask('Hardware Genie')
app.secret_key = os.getenv('SECRET_KEY', 'you will never know')
app.logger.setLevel(logging.INFO)
app.config['PASSWORD_RESET_DEBUG_FLOW'] = os.getenv('PASSWORD_RESET_DEBUG_FLOW', 'true').lower() in ('1', 'true', 'yes', 'on')

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


@app.context_processor
def inject_admin_flags():
    return {
        'is_admin_user': bool(getattr(current_user, 'is_authenticated', False) and getattr(current_user, 'is_admin', False)),
    }

from app.models import User

# user_loader callback
@login_manager.user_loader
def load_user(id):
    try: 
        return db.session.query(User).filter(User.id==id).one()
    except: 
        return None

from app import routes