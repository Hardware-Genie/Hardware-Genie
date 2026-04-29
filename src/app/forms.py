from flask_wtf import FlaskForm
from wtforms import *
from wtforms.validators import DataRequired, InputRequired, Email, Optional, EqualTo, Length


class WebsiteToScrape(FlaskForm):
    name = StringField('Name', validators=[DataRequired()])
    url = StringField('URL', validators=[DataRequired()])
    submit = SubmitField('Submit')


class PartScraperForm(FlaskForm):
    category = SelectField(
        'Category',
        validators=[DataRequired()],
        choices=[
            ('video-card', 'Video Card'),
            ('cpu', 'CPU'),
            ('memory', 'Memory'),
            ('motherboard', 'Motherboard'),
            ('power-supply', 'Power Supply'),
            ('internal-hard-drive', 'Internal Hard Drive'),
        ],
    )
    url = StringField('Product URL', validators=[DataRequired()])
    submit = SubmitField('Run Part Scraper')


class ArticleScraperForm(FlaskForm):
    heading = StringField('Article Heading', validators=[DataRequired()])
    category = SelectField(
        'Category',
        validators=[DataRequired()],
        choices=[
            ('cpu', 'CPU'),
            ('memory', 'Memory'),
            ('video-card', 'Video Card'),
            ('motherboard', 'Motherboard'),
            ('power-supply', 'Power Supply'),
            ('internal-hard-drive', 'Internal Hard Drive'),
        ],
    )
    submit = SubmitField('Analyze Heading')


class ValueAnalysisForm(FlaskForm):
    category = SelectField(
        'Category',
        validators=[DataRequired()],
        choices=[
            ('cpu', 'CPU'),
            ('memory', 'Memory (RAM)'),
            ('motherboard', 'Motherboard'),
            ('power_supply', 'Power Supply'),
            ('video_card', 'Video Card'),
        ],
    )
    submit = SubmitField('Run Value Analysis')

class SignupForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired()])
    submit = SubmitField('Sign Up')

class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Log In')


class ResetPasswordForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    new_password = PasswordField('New Password', validators=[DataRequired(), Length(min=8, max=128)])
    confirm_new_password = PasswordField('Confirm New Password', validators=[DataRequired(), EqualTo('new_password', message='Passwords must match.')])
    submit = SubmitField('Reset Password')


class ProfileForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(max=150)])
    email = StringField('Email', validators=[DataRequired(), Email(), Length(max=255)])
    new_password = PasswordField('New Password', validators=[Optional(), Length(min=8, max=128)])
    confirm_new_password = PasswordField('Confirm New Password', validators=[EqualTo('new_password', message='Passwords must match.')])
    submit = SubmitField('Save Changes')