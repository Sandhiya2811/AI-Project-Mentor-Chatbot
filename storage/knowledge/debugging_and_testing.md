# Debugging and testing

## A debugging routine
1. Reproduce the problem with the smallest possible input. 2. Read the full error message. 3. Form a hypothesis about the cause. 4. Check the hypothesis by printing or inspecting values (types, shapes, lengths) just before the failing line. 5. Change one thing at a time. 6. Re-run and confirm. Rubber-duck explaining the problem aloud often reveals the cause.

## Unit tests
A unit test calls a small piece of code with known input and compares the result to the expected output. Write tests for normal input, edge cases (empty, one item, very large) and invalid input. In Python use pytest or unittest; in Java use JUnit; in JavaScript use Jest. Test names should describe the behaviour. Tests should be independent and fast.

## Version control
Commit small, meaningful changes with clear messages. Use branches for experiments. Never commit secrets such as API keys; keep them in environment variables and list .env in .gitignore.

## Documentation
A good README states what the project does, how to install it, how to run it, example usage, project structure and known limitations. Document decisions: why this model, why this metric.
