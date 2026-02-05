from datetime import date
from app import db



# listing parts.
class Part(db.Model):
    "Class that defines parts"
    __tablename__ = 'parts'
    id = db.Column(db.Integer, primary_key=True ,autoincrement=True)
    name = db.Column(db.String, nullable=False)
    description = db.Column(db.String)
    price = db.Column(db.Float, nullable=False)
    available = db.Column(db.Boolean, default=True)
    image_url = db.Column(db.String)

    def __str__(self):
        return f'<Part(id={self.id}, name={self.name}, price={self.price})>'
