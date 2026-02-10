from flask import render_template, redirect, url_for, request
from app import app

@app.route('/')
@app.route('/index')
@app.route('/index.html')
def index():
    """Render the main index page."""
    return render_template('index.html')

@app.route('/memorygraphs', methods=['GET', 'POST'])
def memory_graphs():
    """Render the memory page."""
    return render_template('memory_graphs.html')

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

