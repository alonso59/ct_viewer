# Prerequisites Setup (Step by Step)

Use this guide once on a new machine before running this repository.

## Path A (Recommended): Remote Server / No `sudo`

Use this path when you do not have admin permissions.

### Step 1: Install Miniconda

```bash
cd /tmp
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash Miniconda3-latest-Linux-x86_64.sh
```

Then create and activate the backend environment:

```bash
source ~/miniconda3/etc/profile.d/conda.sh
conda create -n ccrcc python=3.11 -y
conda activate ccrcc
```

### Step 2: Use repository uDocker (already included)

This repository already includes uDocker (`udocker.py` + `udocker-1.3.17/`), so no global install is required.

From repository root:

```bash
make setup-udocker
make setup-node
```

### Step 3: Bootstrap the repository

From repository root:

```bash
make setup
```

This will check prerequisites, initialize local uDocker state, prepare the frontend Node container, and install backend Python dependencies.

## Path B (Optional): Local Machine with Docker

Use this only if you can install system packages and want Docker Compose deployment.

### Step 1: Check Docker

```bash
docker --version
docker compose version
```

### Step 2: Install Docker if missing

Use official docs:

- https://docs.docker.com/engine/install/
- https://docs.docker.com/compose/install/linux/

### Step 3: Validate Docker

```bash
docker run --rm hello-world
```

## Optional: External uDocker installation

Only needed if you want uDocker outside this repository.

Official project:

- https://github.com/indigo-dc/udocker

Option A (`pip`):

```bash
pip install --user udocker
udocker install
```

Option B (`git clone`):

```bash
cd /tmp
git clone https://github.com/indigo-dc/udocker.git
cd udocker
python3 udocker.py install
```
