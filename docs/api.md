# Usage

## Read a single file

Returns a dataframe that conforms to the specified schema and have been
validated.

```python
df = gmnspy.in_out.read_gmns_csv(data_filename, schema_file=schemafilename)
```

## Read a network

Returns a dictionary of dataframes that conform to the specified schema
and have been validated.

Checks foreign keys between files.

```python
net = gmnspy.in_out.read_gmns_network(data_directory, config: "gmns.spec.json")
```

## API

### Read/Write

::: gmnspy.in_out.read_gmns_csv

::: gmnspy.in_out.read_gmns_network

### Validation

::: gmnspy.validate

::: gmnspy.schema.read_schema

::: gmnspy.schema.read_config

### Conversions

TKTK

### Auto Documentation

::: gmnspy.schema.document_schema

::: gmnspy.utils.list_to_md_table
