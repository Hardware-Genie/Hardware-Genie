import nltk

from transformers import pipeline
from nltk.tokenize import sent_tokenize

#currentl using distilroberta-finetuned-financial-news-model
classifier = pipeline("text-classification", model="mrm8488/distilroberta-finetuned-financial-news-sentiment-analysis")

def sentemantic_analysis(text):
    pos = 0
    neg = 0
    
    #Tokenizes the article by blank line. Currently expects just headlines, though full articles have been tested.
    article_paragraph = sent_tokenize(text) 
    results = classifier(article_paragraph)
    
    for article_paragraph, result in zip(article_paragraph, results):
        print(f"Text: {article_paragraph}")
        print(f"Label: {result['label']}, Score: {result['score']:.4f}\n")

        #Keeps track of number of positive or negative sentences to determine overall sentiment
        if result["label"] == "positive" and result["score"] > .7:
            pos =+ 1
        elif result["label"] == "negative" and result["score"] > .7:
            neg =+ 1
                
    if pos > neg:
        return "positive"
    elif neg > pos:
        return "negative"
    else:
        return "unsure"