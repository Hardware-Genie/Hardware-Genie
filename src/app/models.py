from datetime import date
from app import db
from flask_login import UserMixin, login_user, logout_user, login_required, current_user, login_manager

# EXAMPLE MODEL
# listing parts.
#class Part(db.Model):
#    "Class that defines parts"
#    __tablename__ = 'parts'
#    id = db.Column(db.Integer, primary_key=True ,autoincrement=True)
#    name = db.Column(db.String, nullable=False)
#   description = db.Column(db.String)
#    price = db.Column(db.Float, nullable=False)
#    available = db.Column(db.Boolean, default=True)
#    image_url = db.Column(db.String)
#
#    def __str__(self):
#        return f'<Part(id={self.id}, name={self.name}, price={self.price})>'

class User(db.Model, UserMixin):
    "Class that defines users"
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True ,autoincrement=True)
    username = db.Column(db.String, nullable=False, unique=True)
    email = db.Column(db.String, nullable=False, unique=True)
    password_hash = db.Column(db.String, nullable=False)

    def __str__(self):
        return f'<User(id={self.id}, username={self.username})>'