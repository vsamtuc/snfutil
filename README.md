# snfutil

A Python library for managing cloud resources on **Synnefo** clouds.

This repository is an initial project skeleton; cloud management APIs will be
added as the library develops. Python 3.14 or newer is required.

## Runtime requirements

Python dependencies, including PyYAML for YAML parsing, are installed with the
package. Cloud operations also require a configured `kamaki` CLI on `PATH`.
Generating SSH known-hosts entries requires the OpenSSH `ssh-keyscan` command.

## Development

Create a virtual environment and install the package with development tools:

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

On Windows, activate the environment with `.venv\Scripts\activate`.

Run the tests:

```sh
python -m pytest
```

Expensive tests are excluded by default. Run only the expensive tests (requires
a configured Kamaki CLI and access to the referenced cloud resources):

```sh
python -m pytest -m expensive
```

To run all tests, including expensive tests:

```sh
python -m pytest -m ""
```

Library code lives in `src/snfutil/` and tests live in `tests/`. The editable
installation makes the package available for imports while developing.

## Building distributions

The package uses `pyproject.toml` and setuptools. From a clean checkout with
the development dependencies installed, build and validate a source distribution
and wheel:

```sh
python -m build
python -m twine check dist/*
```

Build artifacts are written to `dist/`. Before each release, update the version
in `pyproject.toml` and remove any artifacts from previous releases in `dist/`.
Choose a license and add its file and project metadata before distributing the
library; add author and repository information to `pyproject.toml` as appropriate.

## Publishing to PyPI

You need a PyPI account with permission to publish the `snfutil` project. Name
availability has not been verified. Use an API token when prompted by Twine
(username `__token__`, password your token); keep tokens out of the repository.

Optionally upload the built artifacts to TestPyPI first:

```sh
python -m twine upload --repository testpypi dist/*
```

Publish the validated artifacts to PyPI:

```sh
python -m twine upload dist/*
```

PyPI versions cannot be reused; increment the version for each new release.
