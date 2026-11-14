# SQL and databases

## Relational basics
Tables have rows and columns; a primary key identifies a row; a foreign key references another table. Normalisation avoids duplicated data. SQLite is a file-based database ideal for learning and small applications and ships with Python.

## Core SQL
SELECT reads data, WHERE filters, ORDER BY sorts, GROUP BY with aggregates (COUNT, SUM, AVG) summarises, JOIN combines tables, INSERT/UPDATE/DELETE change data. Always use parameterised queries from application code to prevent SQL injection. Add indexes for columns used heavily in filters and joins. Wrap related changes in a transaction.

## Using a database from code
Open a connection, create a cursor, execute a parameterised statement, fetch results, commit changes and close the connection. Handle errors such as locked databases or constraint violations. Keep database access in one module so the rest of the project is independent of the storage details.
