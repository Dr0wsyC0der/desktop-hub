import subprocess


def get_gpu_load_percent() -> float:
    create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    startupinfo = None
    if hasattr(subprocess, "STARTUPINFO"):
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)

    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=2,
            creationflags=create_no_window,
            startupinfo=startupinfo,
        )
    except Exception:
        return 0.0

    if result.returncode != 0:
        return 0.0

    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            return max(0.0, min(100.0, float(line)))
        except ValueError:
            continue

    return 0.0
