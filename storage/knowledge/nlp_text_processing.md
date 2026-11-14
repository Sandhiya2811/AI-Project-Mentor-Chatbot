# Natural language processing

## Text preprocessing
Common steps: lower-casing, removing punctuation, URLs and numbers where they add noise, tokenisation (splitting into words), stop-word removal, stemming (chopping word endings) or lemmatisation (dictionary base form). Not every step helps every task - evaluate their effect. Keep the raw text so you can try other choices.

## Turning text into numbers
Bag of Words counts how often each word appears. TF-IDF weights a word by how frequent it is in a document and how rare it is across documents, which down-weights common words. N-grams capture short phrases. Word embeddings and transformer models capture meaning and context. Fit the vectoriser on training text only, then transform test text.

## Libraries
NLTK offers tokenisers, stop-word lists, stemmers and lemmatisers (some resources need a one-time download). spaCy provides fast pipelines with tokenisation, part-of-speech tags and named entities. Hugging Face Transformers provides pretrained transformer models.

## Text classification projects
Typical pipeline: load labelled text, explore label balance and text length, clean text, vectorise (TF-IDF), train a classifier, evaluate with precision/recall/F1 and a confusion matrix, inspect mistakes, and wrap the model in a small interface for prediction.
