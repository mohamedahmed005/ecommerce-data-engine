-- Medallion-style layers
CREATE SCHEMA IF NOT EXISTS raw;        -- untouched copy of source CSVs
CREATE SCHEMA IF NOT EXISTS staging;    -- cleaned / typed
CREATE SCHEMA IF NOT EXISTS warehouse;  -- star schema for analytics
CREATE SCHEMA IF NOT EXISTS dq;         -- data quality results
