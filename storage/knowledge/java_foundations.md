# Java project foundations

## Object-oriented programming
A class defines fields and methods; an object is an instance. Encapsulation keeps fields private and exposes behaviour through methods. Inheritance lets a class reuse another; interfaces define contracts; polymorphism lets code work with the interface type. Prefer composition and small classes with one responsibility.

## Collections
List keeps order (ArrayList), Set stores unique items (HashSet), Map stores key-value pairs (HashMap). Choose by access pattern. Use generics to keep collections type-safe. Iterating, filtering and sorting are common tasks; the Streams API offers declarative alternatives.

## Exceptions
Checked exceptions must be handled or declared; unchecked exceptions signal programming errors. Use try-with-resources for anything that must be closed. Catch specific exceptions and never swallow them silently.

## JDBC, Maven and JUnit
JDBC connects Java to relational databases: obtain a connection, create a prepared statement with parameters (never concatenate user input into SQL), execute, read the result set and close resources. Maven manages dependencies and the build through pom.xml and a standard folder layout (src/main/java, src/test/java). JUnit runs unit tests; test methods are annotated and use assertions to compare expected and actual values.
