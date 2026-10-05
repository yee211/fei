"""Install a wheel outside the checkout and smoke-test imports/entry point."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import venv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel_dir", type=Path)
    parser.add_argument("--reuse-dependencies", action="store_true")
    args = parser.parse_args()
    wheels = list(args.wheel_dir.resolve().glob("fei-*.whl"))
    if len(wheels) != 1:
        parser.error("expected exactly one fei wheel")
    with tempfile.TemporaryDirectory(prefix="fei-install-") as folder:
        root = Path(folder)
        env_dir = root / "venv"
        venv.EnvBuilder(with_pip=True, system_site_packages=args.reuse_dependencies).create(env_dir)
        bin_dir = env_dir / ("Scripts" if os.name == "nt" else "bin")
        python = bin_dir / ("python.exe" if os.name == "nt" else "python")
        env = os.environ.copy()
        for key in list(env):
            if key.startswith("FEI_") or key == "PYTHONPATH":
                env.pop(key, None)
        env["FEI_API_KEY"] = "installation-smoke-placeholder"
        env["FEI_WORKDIR"] = str(root)
        argv = [str(python), "-m", "pip", "install"]
        if args.reuse_dependencies:
            argv.append("--no-deps")
        subprocess.run(argv + [str(wheels[0])], cwd=root, env=env, check=True, timeout=180)
        probe = "import pathlib,sys,fei; from fei import cli,delegation,runtime_limits,skills; from fei.tools import schemas; assert pathlib.Path(fei.__file__).resolve().is_relative_to(pathlib.Path(sys.prefix).resolve()); assert schemas(); print('Installed imports OK')"
        subprocess.run([str(python), "-c", probe], cwd=root, env=env, check=True, timeout=30)
        entry = bin_dir / ("fei.exe" if os.name == "nt" else "fei")
        result = subprocess.run([str(entry)], input="/exit\n", text=True, capture_output=True, cwd=root, env=env, timeout=30)
        if result.returncode or "Traceback" in result.stderr:
            raise RuntimeError(result.stdout + result.stderr)
        print("Installed console entry OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
