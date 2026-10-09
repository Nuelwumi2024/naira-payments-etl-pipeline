-- Example analytics served from the star schema

-- 1. Monthly successful transaction volume (NGN) and success rate
SELECT d.year, d.month, count(*) AS txns,
       round(sum(CASE WHEN f.status = 'success' THEN f.amount_ngn END) / 1e6, 2) AS volume_m_ngn,
       round(100.0 * avg(CASE WHEN f.status = 'success' THEN 1 ELSE 0 END), 2) AS success_rate_pct
FROM fact_transactions f JOIN dim_date d USING (date_key)
GROUP BY 1, 2 ORDER BY 1, 2;

-- 2. Channel reliability: where do failures concentrate?
SELECT channel, count(*) AS txns,
       round(100.0 * avg(CASE WHEN status = 'failed' THEN 1 ELSE 0 END), 2) AS failure_rate_pct
FROM fact_transactions GROUP BY 1 ORDER BY failure_rate_pct DESC;

-- 3. Top states by value, with share of total (window function)
SELECT c.state, round(sum(f.amount_ngn) / 1e6, 1) AS volume_m_ngn,
       round(100 * sum(f.amount_ngn) / sum(sum(f.amount_ngn)) OVER (), 1) AS share_pct
FROM fact_transactions f JOIN dim_customer c USING (customer_id)
WHERE f.status = 'success' GROUP BY 1 ORDER BY 2 DESC;

-- 4. Data-quality monitoring: what did we reject and why?
SELECT reject_reason, count(*) AS rows FROM rejected_transactions GROUP BY 1 ORDER BY 2 DESC;
