# Python foundations

## Virtual environments and packages
A virtual environment is an isolated copy of Python with its own installed packages. Create one per project, activate it, then install packages into it. Most "ModuleNotFoundError" problems happen because the package was installed into a different Python than the one running the script. Check which interpreter is active and list the packages installed for that interpreter. Keep dependencies in requirements.txt so the project can be reproduced.

## Reading files and working with paths
Open files with a context manager so they close automatically. Use pathlib for paths so code works on Windows, macOS and Linux. Always specify the encoding for text files. Relative paths are resolved from the current working directory, not from the script's folder - a very common source of FileNotFoundError.

## Functions and modules
A function should do one job, take inputs as parameters and return a result instead of printing it. Split a project into modules (files) by responsibility: loading data, cleaning, modelling, evaluation, interface. Guard script entry points so importing a module does not run the program.

## Reading error messages
Read a traceback from the bottom: the last line names the error type and message, the lines above show the call chain. The deepest frame inside your own file is usually where to start investigating. Common errors: SyntaxError (invalid code structure), NameError (name not defined yet or misspelled), TypeError (wrong type or number of arguments), KeyError (missing dictionary key or DataFrame column), IndexError (position out of range), AttributeError (object has no such attribute), ImportError/ModuleNotFoundError (package missing or wrong environment), FileNotFoundError (wrong path or working directory).
