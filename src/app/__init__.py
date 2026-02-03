from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask import Flask
import os

app = Flask('Hardware Genie')
# app.secret_key = os.environ['SECRET_KEY']
app.secret_key = 'you will never know'

app.jinja_env.add_extension('jinja2.ext.loopcontrols')

# db initialization
#from flask_sqlalchemy import SQLAlchemy
#app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///parts.db'
#db = SQLAlchemy(app)

# models initialization
#from app import models
#with app.app_context(): 
#    db.create_all()

from app import routes