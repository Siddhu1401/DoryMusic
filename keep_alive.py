from flask import Flask
from threading import Thread

# Initialize a Flask web server
app = Flask('')

@app.route('/')
def home():
    """This is the home page of the web server."""
    return "I'm alive!"

def run():
    """Runs the Flask server."""
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    """
    Creates and starts a new thread to run the web server,
    allowing the bot to run concurrently.
    """
    t = Thread(target=run)
    t.start()
