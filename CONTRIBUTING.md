# Development

## Basic Setup

```bash
pip install -r dev-requirements.txt
pip install -e .
```

## General Process

1. [Create an issue](#issues)
2. [Discuss approach](#consensus)
3. [Complete contribution](#coding) in a fork or branch.
4. [Submit a pull-request](#pull-requests)
5. [Respond to reviews](#review-and-approval-process)

Periodically the `develop` branch will be merged with master and a tagged release will be made and distributed to PyPI.

By making any contribution to the projects, contributors self-certify to the [Contributor Agreement](#contributor-agreement).

## Issues

- Search existing issues to see if your issue has already been brought up.
- Create new issues to start discussion on a new topic, feature requests, and bugs; linking to any other relevant issues.
- Fill out issue template to the best of your ability.
- Indiciate urgency and if you are willing to work on it either using tags or in issue text.

*Issues which do not have a clear user story may not be addressed*

### Consensus

If issue is not super obvious/straightforward, please discuss approach with the maintainers/owner and reach a consensus.

*Contributions which do not have consensus with the owner may not be approved*

## Coding

Get assigned. If you are working on issue, please tag yourself as the assignee (or ask to be tagged if you do not have privledges).

Generally:

- Try to be backwards compatable to Python 3.10.
- Be compatable with Numpy 2+, Pandas 2+, OSMNX 1+, PyProj 3.3+
- Use PEP8 and autoformat with `black`
- Use Google-style docstrings for all classes and methods
- Test formatting and autoformat using `pre-commit`
- Use logging
- All code should have an associated test
- [Documentation](#documentation) is in the `docs` folder and is built using `mkdocs`
- Additions to public API should be documented in `docs/api.md`
- Changes to architecture should be documented in `docs/architecture.md`
- Right now, this repo prioritizes Legibility/Simplicity >> Efficiency. That might change later.

*Contributions which do not meet these requirements may not be approved*

## Testing and CI

Tests are located in the `tests` folder and leverage `pytest`

Running tests:

```bash
pytest
```

Tests are automatically run when commits are pushed to Github using the `.github/workflows/tests.yml` workflow.

## Documentation

Documentation uses `mkdocs` and can be built by:

1. Install documentation requirements

```bash
pip install docs/requirements.txt
```

2. Building and serving a local copy from the `GMNSpy` folder

```bash
mkdocs serve
```

General settings for documentation can be found in `mkdocs.yml`

Code associated with including files and auto-generation of spec-related documentation can be found in `main.py`

PRs and releases will have a documentation version generated using a github workflow `.github/workflows/documentation.yml` using the versioning of `mkdocs` using `mike` package.

## Pull Requests

Use the following guidance in creating and responding to pull requests

- Generally, submit PRs to the `develop` branch.
- Keep pull requests small and focused. One issue is best.
- Link Pull Requests to Issues as appropriate.
- Complete the pull request template as best you can.
- PRs which don't pass the automatic checks should either address issues causing them to fail or comment as to why they aren't.
- Tag an available reviewer to review your PR.

*Pull Requests which do not meet these requirements may not be approved*

### Review and Approval Process

- PRs which don't pass the automatic checks should either address issues causing them to fail or comment as to why they aren't.
- Tag an available reviewer to review your PR.
- Respond to conversation and requests

*Pull Requests which do not respond to reviews may not be approved*

## Contributor Agreement

By making any contribution to the projects, contributors self-certify to the following Contributor Agreement:

By making a contribution to this project, I certify that:
>  
> a. The contribution was created in whole or in part by me and I have the right to submit it under the open source license indicated in the file; or
>  
> b. The contribution is based upon previous work that, to the best of my knowledge, is covered under an appropriate open source license and I have the right under that license to submit that work with modifications, whether created in whole or in part by me, under the same open source license (unless I am permitted to submit under a different license), as indicated in the file; or
>  
> c. The contribution was provided directly to me by some other person who certified (a), (b) or (c) and I have not modified it.
>  
> d. I understand and agree that this project and the contribution are public and that a record of the contribution (including all personal information I submit with it, including my sign-off) is maintained indefinitely and may be redistributed consistent with this project or the open source license(s) involved.
>  
Attribution: This Contributor Agreement is adapted from the node.js project available here: <https://github.com/nodejs/node/blob/main/CONTRIBUTING.md>.
