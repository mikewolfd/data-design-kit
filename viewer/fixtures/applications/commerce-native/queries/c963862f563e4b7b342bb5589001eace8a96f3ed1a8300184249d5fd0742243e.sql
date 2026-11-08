-- Independently authored example. Compile this through the chosen producer;
-- fixture tests must consume the saved plan rather than rerun this SQL.
SELECT o.order_day, c.region, COALESCE(SUM(o.amount_cents), CAST(0 AS BIGINT)) AS amount_cents
FROM orders AS o
INNER JOIN customers AS c ON o.customer_id = c.customer_id
WHERE o.status <> 'cancelled'
GROUP BY o.order_day, c.region
