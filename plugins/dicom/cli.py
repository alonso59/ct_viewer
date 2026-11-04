"""`python -m plugins.dicom.cli config.yaml` keeps working; the command is `rw-dicom` (rw_dicom.cli)."""

import sys

from rw_dicom.cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
