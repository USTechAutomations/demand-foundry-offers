-- PostgreSQL translations of the three synthetic T-SQL reporting procedures.
-- Column names, row order, and null behavior match source.sql / tests.
-- SUM of decimal(20,2) is left unconstrained numeric (SQL Server widens SUM
-- to decimal(38, s)); do not recast aggregate or running totals to decimal(20,2).

CREATE OR REPLACE FUNCTION customer_report(p_customer_id integer, p_status text)
RETURNS TABLE(customer_id integer, order_count bigint, total numeric)
LANGUAGE sql
STABLE
AS $$
    SELECT o.customer_id,
           COUNT(*) AS order_count,
           COALESCE(SUM(o.amount), 0) AS total
    FROM orders o
    WHERE (p_customer_id IS NULL OR o.customer_id = p_customer_id)
      AND (p_status IS NULL OR o.status = p_status)
    GROUP BY o.customer_id
    ORDER BY o.customer_id;
$$;

CREATE OR REPLACE FUNCTION adjusted_month(p_month date)
RETURNS TABLE(order_id integer, net numeric)
LANGUAGE sql
STABLE
AS $$
    WITH adj AS (
        SELECT a.order_id, SUM(a.delta) AS delta
        FROM adjustments a
        GROUP BY a.order_id
    )
    SELECT o.order_id,
           CAST(COALESCE(o.amount, 0) + COALESCE(a.delta, 0) AS decimal(21,2)) AS net
    FROM orders o
    LEFT JOIN adj a ON a.order_id = o.order_id
    WHERE o.placed >= p_month
      AND o.placed < CAST(p_month + INTERVAL '1 month' AS date)
    ORDER BY o.order_id;
$$;

CREATE OR REPLACE FUNCTION ranked_orders(p_customer_id integer)
RETURNS TABLE(order_id integer, "position" bigint, running_total numeric)
LANGUAGE sql
STABLE
AS $$
    SELECT o.order_id,
           ROW_NUMBER() OVER (ORDER BY o.placed, o.order_id) AS "position",
           SUM(COALESCE(o.amount, 0)) OVER (
               ORDER BY o.placed, o.order_id
               ROWS UNBOUNDED PRECEDING
           ) AS running_total
    FROM orders o
    WHERE o.customer_id = p_customer_id
    ORDER BY o.placed, o.order_id;
$$;
