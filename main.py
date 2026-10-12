import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import urlopen


def _get_pypi_project(package_name: str) -> dict[str, Any] | None:
    normalized_name = re.sub(r"[-_.]+", "-", package_name).lower()
    url = f"https://pypi.org/pypi/{quote(normalized_name, safe='')}/json"

    try:
        with urlopen(url, timeout=10) as response:
            return json.loads(response.read())
    except HTTPError as error:
        if error.code == 404:
            return None
        raise RuntimeError(
            f"PyPI returned HTTP {error.code} for package {package_name!r}"
        ) from error
    except URLError as error:
        raise RuntimeError(f"Could not reach PyPI for package {package_name!r}") from error


def _release_upload_time(release_files: list[dict[str, Any]]) -> datetime | None:
    upload_times: list[datetime] = []
    for release_file in release_files:
        upload_time = (
            release_file.get("upload_time_iso_8601")
            or release_file.get("upload_time")
        )
        if upload_time:
            parsed_time = datetime.fromisoformat(upload_time.replace("Z", "+00:00"))
            upload_times.append(parsed_time.astimezone(timezone.utc))

    return min(upload_times) if upload_times else None


def check_requirements(requirements: str) -> str:
    """Check pinned requirements against the PyPI JSON API and summarize the results."""
    dependencies: list[tuple[str, str]] = []
    for line_number, line in enumerate(requirements.splitlines(), start=1):
        requirement = line.split("#", maxsplit=1)[0].strip()
        if not requirement:
            continue

        match = re.fullmatch(
            r"([A-Za-z0-9][A-Za-z0-9._-]*)\s*==\s*([^\s;]+)",
            requirement,
        )
        if match is None:
            raise ValueError(
                f"Expected an exact package==version pin on line {line_number}: "
                f"{requirement!r}"
            )
        dependencies.append((match.group(1), match.group(2)))

    projects: dict[str, dict[str, Any] | None] = {}
    packages_not_found = 0
    versions_not_found = 0
    oldest_release: tuple[datetime, str, str] | None = None

    for package_name, version in dependencies:
        normalized_name = re.sub(r"[-_.]+", "-", package_name).lower()
        if normalized_name not in projects:
            projects[normalized_name] = _get_pypi_project(package_name)
        project = projects[normalized_name]

        if project is None:
            packages_not_found += 1
            continue

        releases = project.get("releases", {})
        if version not in releases:
            versions_not_found += 1
            continue

        upload_time = _release_upload_time(releases[version])
        if upload_time is not None and (
            oldest_release is None or upload_time < oldest_release[0]
        ):
            oldest_release = (upload_time, package_name, version)

    if oldest_release is None:
        oldest_release_text = "None"
    else:
        _, package_name, version = oldest_release
        oldest_release_text = (
            f"{package_name}=={version} ({oldest_release[0].year})"
        )

    return "\n".join(
        (
            f"Dependencies checked: {len(dependencies)}",
            f"Packages not on PyPI: {packages_not_found}",
            f"Versions not on PyPI: {versions_not_found}",
            f"Oldest pinned release: {oldest_release_text}",
        )
    )


if __name__ == "__main__":
    requirements_file = Path(__file__).with_name("requirements.txt")
    print(check_requirements(requirements_file.read_text(encoding="utf-8")))
