# Clustering Notes

The backend uses online semantic clustering:

- Compute embedding for each accepted insight.
- Compare against existing cluster centroids with cosine similarity.
- If similarity is above threshold, assign to nearest cluster and update centroid with EMA.
- Otherwise create a new cluster.

Thresholds and EMA alpha are configured by environment variables.
