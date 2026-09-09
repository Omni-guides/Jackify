"""Shared version-gating for remote-fetched manifests (tools_manifest.json, problem_mods.json).

A manifest fetched from GitHub, or loaded from the local disk cache a past fetch wrote, only
ever overrides Jackify's own bundled copy if its version is genuinely newer. Before this
existed, a successful HTTP 200 with valid JSON was all it took to win outright, no matter how
old or wrong its content was - a missed publish step (confirmed live, 2026-09-08) left the
public tools_manifest.json and problem_mods.json without a tool entry and a mod fix that had
already shipped in a release. Worse, once a bad manifest had been fetched successfully even
once, its disk-cached copy kept winning over the correct bundled one on every subsequent
launch, since nothing ever compared the two - fixing the publish gap alone would not have
self-healed any install that had already cached the bad version.
"""


def is_newer(candidate_version: int, baseline_version: int) -> bool:
    """Whether a fetched or disk-cached manifest version should be trusted over the baseline
    (the version bundled in this build). A missing/zero version - including every manifest
    written before this versioning existed - is always treated as older than any real bundled
    version, so a stale cache from before this fix self-heals the moment a version-aware build
    runs, without needing the cache file to be manually cleared."""
    return candidate_version > baseline_version
