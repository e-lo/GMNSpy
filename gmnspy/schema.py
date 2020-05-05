import json

SCHEMA_TO_PANDAS_TYPES = {
    "integer": "int64",
    "number": "float",
    "string": "string",
    "any": "object",
}

FORMAT_TO_REGEX = {
    # https://emailregex.com/
    "email": r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$",
    # https://www.regextester.com/94092
    "uri": r"^\w+:(\/?\/?)[^\s]+$",
}

def read_schema(schema_file: str) -> dict:
    with open(schema_file, encoding="utf-8") as f:
        schema = json.load(f)
    ## todo validate schema
    return schema

def read_config(config_file: str) --> dict:
    with open(config_file, encoding="utf-8") as f:
        config = json.load(f)
    ## todo validate config
    return config
