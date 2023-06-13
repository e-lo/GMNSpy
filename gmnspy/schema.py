"""
Functions related to Frictionless Data Schemas for GMNS.

Typical usage:

    ```python
    read_schema(schema_file)
    document_schemas_to_md(schema_file_dir)
    document_spec_to_md(spec_file)
    ```
"""

import glob
import json
from os.path import dirname, join, realpath
from pathlib import Path
from typing import Union

import frictionless
import pandas as pd
import requests

from .defaults import (
    SPEC_GITHUB_PATH,
    SPEC_GITHUB_REF,
    SPEC_GITHUB_REPO,
    SPEC_GITHUB_SPEC_FILE,
    SPEC_GITHUB_USER,
)
from .utils import list_to_md_table, logger

SCHEMA_TO_PANDAS_TYPES = {
    "integer": "int64",
    "number": "float",
    "string": "string",
    "any": "object",
    "boolean": "bool",
}

FORMAT_TO_REGEX = {
    # https://emailregex.com/
    "email": r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$",
    # https://www.regextester.com/94092
    "uri": r"^\w+:(\/?\/?)[^\s]+$",
}


def json_from_path(json_path: Union[Path, str]) -> dict:
    """Return json from path which is either github file or local path.

    Args:
        schema_path (Union[Path,str]): Either github URL or local path.

    Returns:
        dict: parsed json
    """
    if json_path[:4] == "http":
        r = requests.get(json_path, allow_redirects=True)
        try:
            _json = r.json()
        except Exception as e:
            logger.error(f"Error retrieving {json_path}: \n   {e.msg}")
            raise Exception(f"{json_path}: {e}")
        return _json

    else:
        with open(json_path, "r", encoding="utf-8") as f:
            return json.loads(f)


class GithubFile:
    """Wrapper object for more easily accessing a file or series of files hosted on github.

    Attributes:
        github_user: github user or organization name.
        github_repo: repo for given user.
        github_path: subdirectory within repo.
        github_file: file withing github_path.
        github_ref: branch or tag to use. Defaults to `main`.
        github_dir_url: contructed url for the girhub file
        github_file_url: specific url for the github_file
        request: requests get file to retrieve github_file_url
        as_json: github_file pulled via a request and parsed as json
        as_dataframe: github_file pulled via requests and parsed as json adn then a dataframe
    """

    def __init__(
        self,
        github_user: str = SPEC_GITHUB_USER,
        github_repo: str = SPEC_GITHUB_REPO,
        github_path: str = SPEC_GITHUB_PATH,
        github_file: str = SPEC_GITHUB_SPEC_FILE,
        github_ref: str = SPEC_GITHUB_REF,
    ):
        self.github_user = github_user
        self.github_repo = github_repo
        self.github_path = github_path
        self.github_file = github_file
        self.github_ref = github_ref

    @property
    def as_json(self):
        json = json_from_path(self.github_file_url)
        return json

    @property
    def as_dataframe(self):
        df = pd.read_csv(self.github_file_url)
        return df

    @property
    def github_dir_url(self):
        """URL to retreive spec file"""
        url = f"https://raw.githubusercontent.com/{self.github_user}/{self.github_repo}"
        url += f"/{self.github_ref}/{self.github_path}"
        return url

    @property
    def github_file_url(self):
        """URL to retreive spec file"""
        url = f"{self.github_dir_url}/{self.github_file}"
        return url


class SpecConfig:
    """Specification configuration object.

    Attributes:
        resources_df: pandas dataframe of all the tables and associated schemas.
        markdown_table: specification as a markdown table.
        data_dir: base directory for data.

    Functions:
        config_json_to_resources_df
        as_markdown
    """

    def __init__(
        self,
        spec_source: Union[GithubFile, Path, str] = None,
        official_version: str = None,
        data_dir: Union[Path, str] = ".",
    ):
        """Constructs a SpecConfig instance.

        Args:
            spec_source (Union[GithubFile,Path,str], optional): If specified, will use a config
                file from github.
            official_version: If specified, will find official version of spec with that ref on
                github per `.defaults`. If not specified, will default to `.defaults.GITHUB_REF`.
            data_dir: Base directory for data. Defaults to "." local directory where spec is.
        """
        if spec_source and official_version:
            raise ValueError("Must specified ONE of spec_source or official_version.")
        if isinstance(spec_source, str):
            spec_source = Path(spec_source)

        if spec_source is not None:
            if not spec_source.is_file():
                logger.error(f"FileNotFound: {spec_source}")
                raise ValueError("Specified spec source not a valid file.")
            self.version = "local"

        elif not official_version:
            official_version = SPEC_GITHUB_REF

        if official_version:
            spec_source = GithubFile(github_ref=official_version)
            ## TODO extract version tags from branch names
            self.version = official_version

        self._spec_source = spec_source
        self._resources_df = None
        self._data_dir = data_dir

        logger.info(f"Created spec source of type: {self._location_type}")

    @property
    def _location_type(self) -> str:
        if isinstance(self._spec_source, GithubFile):
            return "github"
        elif isinstance(self._spec_source, Path):
            return "local"
        else:
            raise ValueError(f"Don't understand spec source: {self._spec_source}")

    @property
    def resources_df(self) -> pd.DataFrame:
        if self._data_dir is None:
            raise ValueError("Must set data_dir before accessing resources_df.")
        if self._resources_df is None:
            self._resources_df = self.config_json_to_resources_df(self._config_json, self._base_path, self._data_dir)
        return self._resources_df

    @property
    def markdown_table(self) -> str:
        return self.as_markdown()

    @property
    def _config_json(self):
        if self._location_type == "github":
            return self._spec_source.as_json
        elif self._location_type == "local":
            with open(self._spec_source, "r", encoding="utf-8") as f:
                return json.load(f)
        else:
            raise ValueError(f"Don't understand spec source: {self._spec_source}")

    @property
    def _base_path(self) -> Union[Path, str]:
        if self._location_type == "github":
            return self._spec_source.github_dir_url
        elif self._location_type == "local":
            return self._spec_source.parents[0]
        else:
            raise ValueError(f"Don't understand spec source: {self._spec_source}")

    @property
    def schema_errors(self) -> list:
        schema_errors = []
        for _, row in self.resources_df.iterrows():
            try:
                self.get_schema(row.name)
            except Exception as err:
                err_info = f"File: {row.name}. Error: {err}"
                schema_errors.append(err_info)
        if schema_errors:
            logger.error(f"{len(schema_errors)} Schema Errors found in Spec.\n{schema_errors}")
        return schema_errors

    def get_schema_as_dict(self, schema_name: str) -> dict:
        """Return schema as dictionary.

        Args:
            schema_name (str): Name of schema which is part of spec.
        """
        _schema_path = self.resources_df.loc[schema_name]["schema_path"]
        return json_from_path(_schema_path)

    def get_schema(self, schema_name: str) -> dict:
        """Return schema as dictionary.

        Args:
            schema_name (str): Name of schema which is part of spec.
        """
        _schema_path = self.resources_df.loc[schema_name]["schema_path"]
        return frictionless.Schema(_schema_path)

    @staticmethod
    def config_json_to_resources_df(
        config_json: json, schema_base_path: Union[Path, str], data_dir: Union[Path, str]
    ) -> pd.DataFrame:
        """Translate json to a data table of resources.

        Args:
            config_json (json): Json of a Configuration file. A json file with a list of "resources"
                specifying the "name", "path", and "schema" for each GMNS table as well as a
                boolean value for "required".

                Example:

                ```json
                    {
                    "resources": [
                    {
                        "name":"link",
                        "path": "link.csv",
                        "schema": "link.schema.json",
                        "required": true
                    },
                    {
                        "name":"node",
                        "path": "node.csv",
                        "schema": "node.schema.json",
                        "required": true
                    }
                    }
                ```
            schema_base_path (Union[Path,str]): Path object or URL base where schemas are located.
            data_dir: base directory for data

        Returns:
            pd.DataFrame: spec configuration file as a DataFrame.
        """

        resources_df = pd.DataFrame(config_json["resources"])
        resources_df["required"].fillna(False, inplace=True)
        if isinstance(schema_base_path, Path):
            resources_df["schema_path"] = resources_df["schema"].apply(lambda x: schema_base_path / x)
        else:
            resources_df["schema_path"] = resources_df["schema"].apply(lambda x: f"{schema_base_path}/{x}")

        resources_df["fullpath"] = resources_df["path"].apply(lambda x: join(data_dir, x))

        resources_df.set_index("name", drop=False, inplace=True)
        return resources_df

    def as_markdown(self, out_path: str = None) -> str:
        """
        Output and optionally write to file spec to markdown table

        args:
            out_path (str, optional): If specified, will write out resulting markdown to this file.
                Defaults to None.
        """
        DROP_COLS = ["fullpath", "schema_path", "path", "schema"]

        # Generate a table for overall file requirements
        spec_df = self.resources_df.drop(columns=DROP_COLS).reset_index()
        spec_df["name"] = spec_df["name"].apply(lambda x: f"[`{x}`](#{x})".replace("_", "-"))

        spec_markdown = spec_df.to_markdown(index=False)

        if out_path:
            with open(out_path, "w") as f:
                logger.debug(f"Writing spec to markdown: {out_path}")
                f.write(str(spec_markdown))

        return spec_markdown


def official_spec_config(version: str = SPEC_GITHUB_REF) -> SpecConfig:
    """Return official spec config of tagged version.

    Args:
        version (str, optional): Tagged version or branch to pull spec from.
            Defaults to SPEC_GITHUB_REF which defaults to master.
    """
    return SpecConfig(official_version=version)


def document_schemas_to_md(schema_path: str = None, out_path: str = None) -> str:
    """Create markdown for each **.schema.json file in schema_path.

    Args:
        schema_path (str, optional): Path fo tlook for schema files.
            Defaults to join(dirname(realpath(__file__)), "spec")
        out_path (str, optional): If specified, will write out resulting markdown to this file.
            Defaults to None.

    Returns:
        str: Markdown string
    """
    schema_path = schema_path or join(dirname(realpath(__file__)), "spec")
    logger.info(f"Documenting Schemas in:\n {schema_path}")

    schema_files = glob.glob(join(schema_path, "**/*.schema.json"), recursive=True)

    # Create markdown with a table for each schema file
    schema_markdown = ""

    for sf in schema_files:
        logger.info(f"Adding to MD: {sf}")
        s = frictionless.Schema(sf)
        md = s.to_markdown()
        _name = f"## {Path(sf).stem.split('.')[-2]}"
        md = md.replace("## `schema`", _name)

        schema_markdown += f"\n{md}\n"

    if out_path:
        with open(out_path, "w") as f:
            f.write(str(schema_markdown))

    return schema_markdown
