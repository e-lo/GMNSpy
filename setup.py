"""Installs GMNSpy package.

Typical Usage:

    ```bash
    python setup.py install # installs by using this file explicitly
    pip install . # installs using pip from local directory
    pip install -e . # installs using pip in developer mode
    ```
"""

from setuptools import find_packages, setup

classifiers = [
    "Development Status :: 1 - Planning",
    "License :: OSI Approved :: Apache Software License",
    "Natural Language :: English",
    "Operating System :: OS Independent",
    "Programming Language :: Python",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.7",
    "Programming Language :: Python :: 3.8",
    "Programming Language :: Python :: 3.9",
    "Programming Language :: Python :: 3.10",
]

pkgs = [pkg for pkg in find_packages()]

pkg_data = {"gmnspy": ["spec/*.*"]}

with open("README.md") as f:
    long_description = f.read()

with open("requirements.txt") as f:
    requirements = f.readlines()

install_requires = [r.strip() for r in requirements]

setup(
    name="gmnspy",
    version="0.0.3",
    description="",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/e-lo/GMNSpy",
    license="Apache 2",
    platforms="any",
    packages=pkgs,
    package_data=pkg_data,
    include_package_data=True,
    zip_safe=False,
    install_requires=install_requires,
)
