# SuperCode Desktop Packaging

This is the first-pass Tauri desktop shell for SuperCode. The desktop app keeps the Python/FastAPI backend as a local sidecar process and lets Tauri choose the loopback port at startup.

## Backend sidecar

Install backend dependencies in the conda `base` environment, then install PyInstaller if needed:

```powershell
conda activate base
python -m pip install -r fastapi_app/requirements.txt
python -m pip install pyinstaller
```

Package the sidecar for Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\package-backend-sidecar.ps1
```

The script writes `src-tauri/binaries/supercode-backend-x86_64-pc-windows-msvc.exe`, which matches the sidecar name configured in `src-tauri/tauri.conf.json`.

## Desktop dev

Start the Vite frontend yourself:

```powershell
cd frontend
pnpm dev --host 0.0.0.0 --port 8888
```

In another terminal, run Tauri dev:

```powershell
cd frontend
pnpm desktop:dev
```

The Tauri shell starts the backend sidecar, waits for `/api/health`, and injects the real backend URL into the frontend.

## Desktop build

After the sidecar exists and the frontend has been built, run:

```powershell
cd frontend
pnpm desktop:build
```

This repository intentionally does not wire `beforeBuildCommand` or `beforeDevCommand` into Tauri yet, so desktop commands do not auto-run Vite build/dev behind your back.
