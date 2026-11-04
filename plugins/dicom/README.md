# rw-dicom

DICOM → NIfTI conversion with resumable, verified outputs that ct_viewer imports directly.
It is the converter ct_viewer runs; this package also works on its own, from Python or a terminal.
Linux and Python 3.12. Requirements and design: `docs/domain/DICOM_CONVERTER.md` (DCM-26..34), ADR-0042.

## Install (Conda or any virtual environment)

```bash
conda create -n rwdicom python=3.12
conda activate rwdicom
pip install -e 'path/to/radioccrcc-webui/plugins/dicom[yaml]'   # [yaml] only for YAML configs
rw-dicom --version
```

## Convert

```bash
rw-dicom convert /data/dicom /data/out                      # one dataset
rw-dicom convert /data/dicom /data/out --workers auto       # series in parallel
rw-dicom convert /data/dicom /data/out --set anonymize=basic
rw-dicom convert /data/dicom /data/out --batch-size 40      # one dataset per 40 patient folders
rw-dicom convert /data/dicom /data/out --dry-run            # plan only: nothing written, no pixels read
rw-dicom convert /data/dicom /data/out --retry-failed       # only the series that failed
rw-dicom status /data/out
```

- **Resume:** run the same command again. Verified series are kept (their SHA-256 is checked), the rest is converted. A changed source or changed settings refuse to resume; use a new output folder.
- **Stop:** Ctrl-C, closing the terminal or `kill` let running series finish and record the run as interrupted; a second signal stops at once. Nothing keeps running after the terminal closes: use `tmux`, `screen`, `nohup rw-dicom … > log 2>&1 &` or `systemd-run --user` for long runs.
- **Workers:** `--workers auto` (the default: available CPUs, at most 8) or `--workers N`, with `--memory-mb` as the total budget of all workers (default: half of the SLURM allocation, or of physical memory). `--workers 1` converts in one process. Outputs are identical for any worker count.
- **Settings:** the keys of `dicom.convert` (`target_profile`, `anonymize`, `sidecars`, `convert_primary`, …; see `rw_dicom/task_settings.json`). Unknown keys are refused.
- **Config file:** `--config run.yaml` (or `.json`) with `source`, `output`, `settings` and `execution` (`workers`, `memory_mb`, `max_failures`, `allow_mixed_versions`, `batch_size`, `inventory_mb`, `state_dir`). The converter's original YAML keys (`dataset_root`, `output_root`, `conversion`, `outputs`, `mode`) still work: `rw-dicom old.yaml`.
- **Cluster:** run inside `sbatch`, and when the output is on Lustre, GPFS or NFS add `--state-dir` on node-local disk: SQLite's write-ahead log does not work on those file systems. Losing that folder only costs a new header scan. The output's file system must support `flock`. Example: `docs/ops/DEPLOYMENT.md` §HPC.
- **Exit code:** 0 when the dataset is complete; 1 when series failed or are pending, or the run was refused.

## Python

```python
from rw_dicom import api

summary = api.convert("/data/dicom", "/data/out", settings={"anonymize": "basic"}, workers=4)
plan = api.convert("/data/dicom", "/data/out", mode="dry_run")
batches = api.convert_batches("/data/dicom", "/data/out", batch_size=40)
api.status("/data/out")
```

## Output and ct_viewer

An output folder is a ct_viewer dataset: `metadata.jsonl`, `nifti/`, `sidecars/`, `annotations.jsonl`, `diagnostics.jsonl`, `summary.json` and `dataset.json` once every selected series converted (`dataset.incomplete.json` otherwise). Open it in ct_viewer or import it into a project with Import data; an incomplete dataset imports only after you acknowledge it, with failed and pending series excluded and their reasons kept.

**Privacy.** Run state (`.rw-runs/`: cached headers, pins, journal) is private (0700). The dataset itself can contain patient data even with `anonymize: basic` (folder names in `commit.json` and `diagnostics.jsonl`, the source path in `dataset.json`). Do not share a converted folder as-is.
