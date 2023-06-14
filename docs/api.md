# Usage

## Read a single file

Returns a dataframe that conforms to the specified schema and have been
validated.

=== "Specify Local Schema File"

    ```python
    df = gmnspy.in_out.read_gmns_csv(data_filename, schema_path=schemafilename)
    ```

=== "Use local spec and schema name"

    ```python
    spec = gmnspy.SpecConfig(gmnspy.defaults.LOCAL_SPEC)
    df = gmnspy.in_out.read_gmns_csv(data_filename, spec=spec, schema_name = "link")
    ```

=== "Use canonical spec and infer schema from filename"

    ```python
    spec = gmnspy.SpecConfig()
    df = gmnspy.in_out.read_gmns_csv(data_filename, spec=spec)
    ```

## Read a network

Returns a dictionary of dataframes that conform to the specified schema
and have been validated. Also checks foreign keys between files.

=== "Use local spec"

    ```python
    net = gmnspy.in_out.read_gmns_network(data_directory, config_path: gmnspy.defaults.LOCAL_SPEC)
    ```

=== "Use canonical spec"

    ```python
    net = gmnspy.in_out.read_gmns_network(data_directory, official_version="master")
    ```

## API

::: gmnspy.schema.json_from_path

::: gmnspy.schema.GithubFile


### Read/Write

::: gmnspy.in_out.read_gmns_csv

::: gmnspy.in_out.read_gmns_network

### Schema

::: gmnspy.schema.SpecConfig

::: gmnspy.schema.official_spec_config

::: gmnspy.schema.local_spec_config

### Validation

::: gmnspy.validation.apply_schema_to_df

::: gmnspy.validation.update_resources_based_on_existance

::: gmnspy.validation.check_required_files

::: gmnspy.validation.apply_schema_to_df

### Conversions

TKTK

### Auto Documentation

::: gmnspy.schema.document_schemas_to_md

::: gmnspy.utils.list_to_md_table
