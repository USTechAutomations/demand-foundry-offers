# SQL Server to PostgreSQL reporting proof

Three synthetic reporting procedures, eleven captured result sets.

**Discuss your reporting migration:** [Request a workload assessment](https://ustechautomations.com/partner?interest=database-migration). No customer data. This is a worked example, not a general SQL translator or migration guarantee.

Run `python3 verify.py` with Python 3, Docker, and an already available `postgres:15.7-alpine` image. The script does not download images. It starts a uniquely named, network-isolated disposable PostgreSQL instance, loads the fixture and translated functions, compares exact numeric rows to the saved SQL Server results, and removes its container. Exit 0 means all captured result sets match; 1 means a mismatch; 2 means unavailable or malformed evidence. A startup or cleanup failure is never reported as success.

SQL Server was executed separately in a public browser compiler using synthetic SQL only. Source locations are in source-url.txt and source-precision-url.txt. To inspect or repeat that source experiment, use source.sql plus the EXEC statements in cases.json; source-precision.sql contains the additional large-total experiment. The local script replays saved source evidence, not a new SQL Server run.

Coverage: optional filters, missing customer and empty month results, month boundaries, aggregated adjustments, deterministic window ordering, null amounts, negative values and widened decimal totals. Numeric values are compared exactly; numeric display scale is ignored. Native metadata equivalence, collation, overflow beyond demonstrated ranges, timezone behavior, transactions, concurrency, error semantics and arbitrary stored procedures are not proved. The translated SQL uses PostgreSQL numeric for widened aggregates; this is not a claim of identical SQL Server decimal limits.

For a workload assessment, use https://ustechautomations.com/partner?interest=database-migration . Describe authorized reporting objects and migration goals without sending credentials or confidential SQL through a public tool. A proposed engagement would supply converted reporting SQL, reproducible comparisons, discrepancy/unsupported-case notes and handoff instructions. Scope, price, delivery and acceptance require review before any payment. No payment link or customer acceptance is contained in this example.
