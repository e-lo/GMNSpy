"""Functions used to create documentation by mkdocs-macros.

Typical Usage:
   
    ```markdown
    {{ include_file(`file_path`) }}
    {{ frictionless_spec(`file_path`) }}
    {{ frictionless_schemas(`dir_path`) }}
    ```
"""

import os
import re
from typing import Union

import pandas as pd

from gmnspy import document_spec_to_md, document_schemas_to_md

FIND_REPLACE = {  # original relative to /docs : redirect target
    "<CONTRIBUTING.md>": "[Contributing Section](development/#CONTRIBUTING)",
    "(CODE_OF_CONDUCT.md)": "(development/#CODE_OF_CONDUCT)",
    "CONTRIBUTING.md)": "development/#CONTRIBUTING)",
    "<LICENSE>": "[LICENSE](https://github.com/e-lo/GMNSpy/blob/main/LICENSE)",
    "contributors.md)": "development/#contributors)",
    "architecture.md)": "architecture)",
}

_md_heading_re = {
    1: re.compile(r"(#{1}\s)(.*)"),
    2: re.compile(r"(#{2}\s)(.*)"),
    3: re.compile(r"(#{3}\s)(.*)"),
    4: re.compile(r"(#{4}\s)(.*)"),
    5: re.compile(r"(#{5}\s)(.*)"),
}


def _downshift_md(md: str) -> str:
    md = re.sub(_md_heading_re[5], r"#\1\2", md)
    md = re.sub(_md_heading_re[4], r"#\1\2", md)
    md = re.sub(_md_heading_re[3], r"#\1\2", md)
    md = re.sub(_md_heading_re[2], r"#\1\2", md)
    md = re.sub(_md_heading_re[1], r"#\1\2", md)
    return md


def define_env(env):
    """
    Define variables, macros and filters.

    - variables: the dictionary that contains the environment variables
    - macro: a decorator function, to declare a macro.
    """

    @env.macro
    def include_file(filename: str, downshift_h1=True, start_line: int = 0, end_line: int = None):
        """
        Include a file, optionally indicating start_line and end_line and optionally downshifting.

        Will create redirects if specified in FIND_REPLACE in main.py.

        args:
            filename: file to include, relative to the top directory of the documentation project.
            downshift_h1: If true, will downshift headings by 1 if h1 heading found.
                Defaults to True.
            start_line (Optional): if included, will start including the file from this line
                (indexed to 0)
            end_line (Optional): if included, will stop including at this line (indexed to 0)
        """
        full_filename = os.path.join(env.project_dir, filename)
        with open(full_filename, "r") as f:
            lines = f.readlines()
        line_range = lines[start_line:end_line]
        content = "".join(line_range)

        # Downshift headings if h1 found and downshift_h1 is true
        if _md_heading_re[1].search(content) and downshift_h1:
            content = _downshift_md(content)

        _filenamebase = env.page.file.url
        for _find, _replace in FIND_REPLACE.items():
            if _filenamebase in _replace:
                _replace = _replace.replace(_filenamebase, "")

            content = content.replace(_find, _replace)
        return content

    @env.macro
    def frictionless_spec(
        spec_path: str = None,
    ) -> str:
        """Translate the frictionless .spec file to a markdown table.

        Args:
            spec_path (str, optional): base path of repo. Defaults to two directories
                up from this file.

        Returns: a markdown table string
        """
        return document_spec_to_md(spec_path)

    @env.macro
    def frictionless_schemas(
        schema_path: str = None,
    ) -> None:
        """Document frictionless table schema files as markdown tables.

        Args:
            schema_path (str, optional): Schema path in glob format.
                Defaults to "**/*.schema.json".
        """
        return document_schemas_to_md(schema_path)
