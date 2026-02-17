
from flask import Flask, render_template, jsonify, redirect, url_for, request
from app import app
import pandas as pd
import json

class csv_data_reader:
    def __init__(self, labels, price):
        self.labels = labels
        self.price = price

    def from_csv(self, file_name):
        csv_path = f'static/data/{file_name}.csv'
        df = pd.read_csv(csv_path)
        df = df.dropna(subset=['price'])
        self.labels = df['name'].tolist()
        self.price = df['price'].tolist()

    def to_dict(self):
        return {
            'labels': self.labels,
            'price': self.price
        }

memory_csv_reader = csv_data_reader([], [])
memory_csv_reader.from_csv('memory')


@app.route('/')
@app.route('/index')
@app.route('/index.html')
def index():
    """Render the main index page."""
    return render_template('index.html')

@app.route('/memory', methods=['GET', 'POST'])
def memory_page():
    dict=memory_csv_reader.to_dict()
    labels = dict['labels']
    price = dict['price']
    return render_template('memory_page.html', labels=labels, price=price)

@app.route('/memorygraphs', methods=['GET', 'POST'])
def memory_graphs():
    dict=memory_csv_reader.to_dict()
    labels = dict['labels']
    price = dict['price']
    return render_template('memory_graphs.html', labels=labels, price=price)

@app.route('/gpugraphs', methods=['GET', 'POST'])
def gpu_graphs():
    """Render the GPU page."""
    return render_template('gpu_graphs.html')

@app.route('/cpugraphs', methods=['GET', 'POST'])
def cpu_graphs():
    """Render the CPU page."""
    return render_template('cpu_graphs.html')

@app.route('/storagegraphs', methods=['GET', 'POST'])
def storage_graphs():
    """Render the Storage page."""
    return render_template('storage_graphs.html')

@app.route('/motherboardgraphs', methods=['GET', 'POST'])
def motherboard_graphs():
    """Render the motherboard page."""
    return render_template('motherboard_graphs.html')

@app.route('/powersupplygraphs', methods=['GET', 'POST'])
def powersupply_graphs():
    """Render the power supply page."""
    return render_template('powersupply_graphs.html')

