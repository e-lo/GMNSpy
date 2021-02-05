from setuptools import setup
from distutils.util import convert_path

classifiers = [
    "Development Status :: 1 - Planning",
    "License :: OSI Approved :: Apache Software License",
    "Natural Language :: English",
    "Operating System :: OS Independent",
    "Programming Language :: Python",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.6",
    "Programming Language :: Python :: 3.7",
]

with open("README.md") as f:
    long_description = f.read()

with open("requirements.txt") as f:
    requirements = f.readlines()

stored_vars = {}
version_path = convert_path('gmnspy/_version.py')
with open(version_path) as version_file:
    exec(version_file.read(), stored_vars)


install_requires = [r.strip() for r in requirements]

setup(
    name="gmnspy",
    version=stored_vars['__version__'],
    description="",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/e-lo/GMNSpy",
    license="Apache 2",
    platforms="any",
    packages=["gmnspy"],
    include_package_data=True,
    install_requires=install_requires,
)
