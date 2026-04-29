# Hardware-Genie
Hardware Genie is a website that aims to provide up to date PC price information, make inferences about the future prices of components, and compare values of parts within a category. It gathers information via webscraping, and uses sentiment analysis to interpret headlines to predict whether the prices are expected to greatly change soon. We help estimate the value of a product by comparing certain specs of a component, like clock speed in RAM, and gives it a rating based on that. 

# Building and running the project
To build and run the project, you can use the following commands:
Requires Docker to be installed on your machine.
```powershell
# Build the project
docker build -t hardware-genie .
# Run the project
docker run -p 5000:5000 hardware-genie
```
This loads the project on localhost:5000, and you can access it through your web browser.

Scraper functionality needs a redis server and a celery worker to run. You can start these with the following commands:
```powershell
# Start redis server
docker run -p 6379:6379 redis
# Start celery worker
$env:PYTHONPATH = 'src'
celery -A app.tasks.celery worker --pool=solo --loglevel=info
```

# Model used for Sentiment analysis
https://huggingface.co/mrm8488/distilroberta-finetuned-financial-news-sentiment-analysis/discussions
