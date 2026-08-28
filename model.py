from textblob import TextBlob

def analyze_sentiment(text):
    if not text:
        return "Neutral"

    analysis = TextBlob(text)
    polarity = analysis.sentiment.polarity

    if polarity > 0:
        return "Positive"
    elif polarity < 0:
        return "Negative"
    else:
        return "Neutral"