import nltk
from nltk import pos_tag, word_tokenize
from nltk.corpus import sentiwordnet as swn
from nltk.corpus import wordnet as wn

_REQUIRED_NLTK_DATA = [
    ("corpora/sentiwordnet", "sentiwordnet"),
    ("corpora/wordnet", "wordnet"),
    ("corpora/omw-1.4", "omw-1.4"),
    ("taggers/averaged_perceptron_tagger_eng", "averaged_perceptron_tagger_eng"),
    ("tokenizers/punkt_tab", "punkt_tab"),
]


def _ensure_nltk_data():
    for path, package in _REQUIRED_NLTK_DATA:
        try:
            nltk.data.find(path)
        except LookupError:
            nltk.download(package, quiet=True)


_ensure_nltk_data()


def _wordnet_pos(penn_tag):
    if penn_tag.startswith("J"):
        return wn.ADJ
    if penn_tag.startswith("V"):
        return wn.VERB
    if penn_tag.startswith("N"):
        return wn.NOUN
    if penn_tag.startswith("R"):
        return wn.ADV
    return None


def sentiment_score(text):
    if not text:
        return 0.0

    tagged_tokens = pos_tag(word_tokenize(text))

    total = 0.0
    scored_count = 0

    for word, penn_tag in tagged_tokens:
        wn_pos = _wordnet_pos(penn_tag)
        if wn_pos is None:
            continue

        synsets = list(wn.synsets(word, pos=wn_pos))
        if not synsets:
            continue

        senti_synset = swn.senti_synset(synsets[0].name())
        total += senti_synset.pos_score() - senti_synset.neg_score()
        scored_count += 1

    if scored_count == 0:
        return 0.0

    return total / scored_count


def analyze_sentiment(text):
    score = sentiment_score(text)

    if score > 0.02:
        return "Positive"
    elif score < -0.02:
        return "Negative"
    else:
        return "Neutral"


def score_to_rating(score):
    rating = 3 + score * 4
    return round(min(5.0, max(1.0, rating)), 1)
