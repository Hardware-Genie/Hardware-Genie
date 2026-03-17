# Use a pipeline as a high-level helper
from transformers import pipeline
from nltk.tokenize import sent_tokenize

classifier = pipeline("text-classification", model="mrm8488/distilroberta-finetuned-financial-news-sentiment-analysis")

#Perform sentiment analysis on sample texts
with open("test_article") as file:
    article = file.read()

article_sentence = sent_tokenize(article)


results = classifier(article_sentence)

for article_sentence, result in zip(article_sentence, results):
    print(f"Text: {article_sentence}")
    print(f"Label: {result['label']}, Score: {result['score']:.4f}\n")