# Recommendation and prediction projects

## Recommendation systems
Content-based filtering recommends items similar to ones a user liked, using item features and similarity measures such as cosine similarity. Collaborative filtering uses patterns across many users: user-based, item-based or matrix factorisation. Cold start (new users or items) is the main weakness. Evaluate with precision@k, recall@k or RMSE for ratings, and hold out interactions for testing.

## Tabular prediction (students, diseases, prices)
Understand each feature and the target. Handle missing values and categorical features (one-hot or ordinal encoding). Scale numeric features for distance-based or linear models. Split data properly, compare a simple baseline with stronger models, and report metrics appropriate to the cost of mistakes - in medical problems missing a sick patient (low recall) is usually worse than a false alarm. Predictions from student projects are educational and must not replace professional judgement.

## Building a small interface
After the model works, save it and load it from a small application that accepts input, validates it, calls the model and shows the result. Keep model code and interface code in separate modules.
