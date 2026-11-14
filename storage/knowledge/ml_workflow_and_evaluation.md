# Machine learning workflow and evaluation

## Workflow
Define the problem, collect data, explore it, clean and preprocess, split into train and test sets, build features, train a model, evaluate on unseen data, improve, then package and document. Split before fitting any transformer to avoid data leakage: statistics such as vocabulary or scaling parameters must be learned from the training set only.

## Scikit-learn pattern
Estimators share a common interface: create the object, fit it on training data, predict on new data. Transformers add a transform step. A Pipeline chains preprocessing and a model so the same steps are applied consistently during training and prediction. Use a fixed random seed for reproducibility.

## Classification models
Logistic Regression models the probability of a class and is a strong baseline for text. Naive Bayes is fast for word counts. Decision trees and random forests handle non-linear relationships. Support vector machines work well on high-dimensional sparse data. Start simple and compare.

## Metrics
Accuracy is the share of correct predictions and can mislead on imbalanced data. Precision is how many predicted positives are correct; recall is how many real positives were found; F1 combines them. A confusion matrix shows the four outcomes (true/false positives/negatives). For regression use MAE, MSE/RMSE and R-squared. Overfitting means high training score but low test score; remedies are more data, simpler models, regularisation and cross-validation.
