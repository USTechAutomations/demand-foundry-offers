-- Synthetic fixture only. Three reporting procedures for source/target verification.
CREATE TABLE orders(order_id int NOT NULL, customer_id int NOT NULL, amount decimal(20,2) NULL, placed date NOT NULL, status varchar(12) NOT NULL);
CREATE TABLE adjustments(order_id int NOT NULL, delta decimal(20,2) NULL);
INSERT INTO orders VALUES (1,10,12.10,'20240201','paid'),(2,10,NULL,'20240229','paid'),(3,10,-2.10,'20240301','paid'),(4,20,NULL,'20240210','pending'),(5,30,1.00,'20240211','paid'),(6,30,2.00,'20240211','paid'),(7,40,9007199254740992.01,'20240215','paid');
INSERT INTO adjustments VALUES (1,1.00),(1,2.00),(2,NULL),(5,-1.00),(99,100.00);