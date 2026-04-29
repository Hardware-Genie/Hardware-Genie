from transformers import pipeline

#currentl using distilroberta-finetuned-financial-news-model
classifier = pipeline("text-classification", model="mrm8488/distilroberta-finetuned-financial-news-sentiment-analysis")


def sentemantic_analysis(text):
    normalized_text = str(text or '').strip()
    if not normalized_text:
        return {
            'label': 'unsure',
            'score': 0.0,
        }

    result = classifier(normalized_text)[0]
    label = str(result.get('label', 'unsure')).strip().lower()
    score = float(result.get('score') or 0.0)

    if label not in {'positive', 'negative'}:
        label = 'unsure'

    return {
        'label': label,
        'score': score,
    }