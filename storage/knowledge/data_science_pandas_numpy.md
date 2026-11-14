# Data handling with Pandas and NumPy

## Pandas basics
A DataFrame is a table of rows and labelled columns; a Series is a single column. Typical first steps: load the file, look at the first rows, shape, column names, data types, count of missing values, duplicates, and the distribution of the target column. Selecting columns by label, filtering rows by condition, grouping and aggregating are the core operations. Methods usually return a new object instead of modifying in place.

## Cleaning data
Handle missing values (drop rows, fill with a statistic, or fill with a marker), remove duplicates, fix data types, standardise text, and check for outliers. Document each cleaning decision. Check class balance for classification problems because imbalance changes which metrics are meaningful.

## NumPy basics
NumPy provides n-dimensional arrays with fast vectorised operations. Think in terms of shape and axis. Broadcasting lets arrays of different shapes combine. Prefer vectorised operations over Python loops. Many shape errors can be diagnosed by printing the shape of each array.

## Visualisation
Matplotlib draws figures; Seaborn builds statistical charts on top. Use histograms for distributions, bar charts for counts, scatter plots for relationships, heatmaps for correlations and confusion matrices. Always label axes and add a title.
