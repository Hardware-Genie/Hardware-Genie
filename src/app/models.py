from datetime import datetime
from app import db
from flask_login import UserMixin, login_user, logout_user, login_required, current_user, login_manager
from sqlalchemy.sql import expression

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
    is_admin = db.Column(db.Boolean, nullable=False, default=False, server_default=expression.false())

    def __str__(self):
        return f'<User(id={self.id}, username={self.username})>'


class SavedBuild(db.Model):
    "Class that defines saved user builds"
    __tablename__ = 'saved_builds'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    build_name = db.Column(db.String, nullable=False)
    build_data = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('saved_builds', cascade='all, delete-orphan', lazy=True))

    def __str__(self):
        return f'<SavedBuild(id={self.id}, user_id={self.user_id}, build_name={self.build_name})>'