from flask import Flask


# Flask constructor takes the name of 
# current module (__name__) as argument.
app = Flask(__name__)

@app.route('/', methods=["GET","POST"])
def web_app():
    return 'Ram Prices are gonna go up. Or maybe down?'


# main driver function
if __name__ == '__main__':
    # run() method of Flask class runs the application 
    # on the local development server.
    app.run(debug=True)