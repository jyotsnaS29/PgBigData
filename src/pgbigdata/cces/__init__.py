"""CCES (Cooperative Election Study) survey ingestion from Harvard Dataverse.

Unlike ACS/PUMS (a REST API), CCES is distributed as bulk tabular files — this
exercises the 'bulk data sources' half of the pipeline. Same storage model:
promote the analytic keys (weights, geography crosswalks, core demographics) to
typed columns; keep the ~500 survey-item columns in JSONB.
"""
