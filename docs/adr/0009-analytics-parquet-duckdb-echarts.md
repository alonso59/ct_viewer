# ADR-0009 Analytics on Parquet + DuckDB; ECharts for charts
Status: Accepted · Date: 2026-09-23

**Context.** The dashboard needs fast aggregations over long feature tables (items × labels × features ≈ millions of rows) without a DB server (ADR-0002).

**Decision.** Radiomics outputs are Parquet. The backend queries them with in-process DuckDB plus NumPy/scikit-learn for PCA and z-scores (API-38). The frontend renders with Apache ECharts (canvas, large-data scatter).

**Consequences.** + Fast, serverless, and export-friendly (Parquet opens in pandas, polars and R). − Adds DuckDB + pyarrow to the image (~100 MB).

**Rejected.** Plotly (heavy bundle), Vega-Lite (weaker large scatter performance), client-side-only analytics (memory).
