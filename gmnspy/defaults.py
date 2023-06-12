
import os
from pathlib import Path

SPEC_GITHUB_USER = "zephyr-data-specs"
SPEC_GITHUB_REPO = "GMNS"
SPEC_GITHUB_PATH = Path("Specification") / Path("gmns.spec.json")
SPEC_GITHUB_SPEC_FILE = "gmns.spec.json"
SPEC_GITHUB_REF = "master"

LOCAL_CONFIG =  os.path.join(os.path.dirname(os.path.realpath(__file__)), "spec")