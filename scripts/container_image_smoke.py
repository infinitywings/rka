"""Start a Core image in an isolated container and verify its public health API."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import uuid
from typing import Any

LABEL_KEY = "org.rka.core.image-smoke"


def _run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args],
        check=check,
        capture_output=True,
        text=True,
    )


def _inspect(container: str) -> dict[str, Any]:
    result = _run("inspect", container)
    payload = json.loads(result.stdout)
    if len(payload) != 1:
        raise RuntimeError(f"expected one container inspection, got {len(payload)}")
    return payload[0]


def _logs(container: str) -> str:
    result = _run("logs", container, check=False)
    return (result.stdout + result.stderr).strip()


def _cleanup(container: str, token: str) -> None:
    result = _run("inspect", container, check=False)
    if result.returncode != 0:
        return

    payload = json.loads(result.stdout)
    actual = payload[0].get("Config", {}).get("Labels", {}).get(LABEL_KEY)
    if actual != token:
        raise RuntimeError(
            f"refusing to remove {container}: ownership label is {actual!r}, expected {token!r}"
        )
    _run("rm", "--force", "--volumes", container)


def smoke(image: str, expected_version: str, timeout: float) -> dict[str, Any]:
    token = uuid.uuid4().hex
    container = f"rka-core-image-smoke-{token[:12]}"
    created = False

    try:
        _run(
            "run",
            "--detach",
            "--name",
            container,
            "--label",
            f"{LABEL_KEY}={token}",
            "--env",
            "RKA_EMBEDDINGS_ENABLED=false",
            "--tmpfs",
            "/data:rw,noexec,nosuid,size=256m",
            image,
        )
        created = True

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            details = _inspect(container)
            state = details.get("State", {})
            if state.get("Status") == "exited":
                raise RuntimeError(
                    f"container exited with code {state.get('ExitCode')}:\n{_logs(container)}"
                )
            if state.get("Health", {}).get("Status") == "healthy":
                break
            time.sleep(1)
        else:
            raise RuntimeError(
                f"container did not become healthy within {timeout:g}s:\n{_logs(container)}"
            )

        details = _inspect(container)
        if details.get("HostConfig", {}).get("PortBindings"):
            raise RuntimeError("image smoke unexpectedly published a host port")

        tmpfs = details.get("HostConfig", {}).get("Tmpfs") or {}
        if "/data" not in tmpfs:
            raise RuntimeError(f"expected a tmpfs /data mount, got {tmpfs!r}")
        persistent_data_mounts = [
            mount
            for mount in details.get("Mounts", [])
            if mount.get("Destination") == "/data" and mount.get("Type") != "tmpfs"
        ]
        if persistent_data_mounts:
            raise RuntimeError(f"unexpected persistent /data mount: {persistent_data_mounts!r}")

        probe = (
            "import json,os,urllib.request; "
            "payload=json.load(urllib.request.urlopen('http://127.0.0.1:9712/api/health')); "
            "print(json.dumps(payload,sort_keys=True)); "
            "assert payload['status']=='ok'; "
            "assert payload['version']==os.environ['EXPECTED_VERSION']"
        )
        response = _run(
            "exec",
            "--env",
            f"EXPECTED_VERSION={expected_version}",
            container,
            "python",
            "-c",
            probe,
        )

        return {
            "container": container,
            "health": json.loads(response.stdout),
            "image": image,
            "published_host_ports": [],
            "storage": "tmpfs",
        }
    finally:
        if created:
            _cleanup(container, token)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()

    print(
        json.dumps(smoke(args.image, args.expected_version, args.timeout), indent=2, sort_keys=True)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
