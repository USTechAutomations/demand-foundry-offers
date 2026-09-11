-- Synthetic fixture only. Three reporting procedures for source/target verification.
CREATE TABLE orders(order_id int NOT NULL, customer_id int NOT NULL, amount decimal(20,2) NULL, placed date NOT NULL, status varchar(12) NOT NULL);
CREATE TABLE adjustments(order_id int NOT NULL, delta decimal(20,2) NULL);
INSERT INTO orders VALUES (1,10,12.10,'20240201','paid'),(2,10,NULL,'20240229','paid'),(3,10,-2.10,'20240301','paid'),(4,20,NULL,'20240210','pending'),(5,30,1.00,'20240211','paid'),(6,30,2.00,'20240211','paid'),(7,40,9007199254740992.01,'20240215','paid');
INSERT INTO adjustments VALUES (1,1.00),(1,2.00),(2,NULL),(5,-1.00),(99,100.00);
GO
CREATE PROCEDURE customer_report @customer_id int = NULL, @status varchar(12) = NULL AS
SELECT customer_id, COUNT(*) AS order_count, ISNULL(SUM(amount),0) AS total
FROM orders WHERE (@customer_id IS NULL OR customer_id=@customer_id) AND (@status IS NULL OR status=@status)
GROUP BY customer_id ORDER BY customer_id;
GO
CREATE PROCEDURE adjusted_month @month date AS
SELECT order_id, SUM(delta) AS delta INTO #adj FROM adjustments GROUP BY order_id;
SELECT o.order_id, CAST(ISNULL(o.amount,0)+ISNULL(a.delta,0) AS decimal(21,2)) AS net
FROM orders o LEFT JOIN #adj a ON a.order_id=o.order_id
WHERE placed>=@month AND placed<DATEADD(month,1,@month) ORDER BY o.order_id;
DROP TABLE #adj;
GO
CREATE PROCEDURE ranked_orders @customer_id int AS
SELECT order_id, ROW_NUMBER() OVER(ORDER BY placed,order_id) AS position,
SUM(ISNULL(amount,0)) OVER(ORDER BY placed,order_id ROWS UNBOUNDED PRECEDING) AS running_total
FROM orders WHERE customer_id=@customer_id ORDER BY placed,order_id;
GO
