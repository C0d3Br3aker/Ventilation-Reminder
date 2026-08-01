#!/usr/bin/env bash
# Cut a release: bump the manifest, tag it and push both in the right order.
# The Release workflow turns the pushed tag into a GitHub release, which is
# what HACS actually reads.
#
# Usage: scripts/release.sh 0.3.0
set -euo pipefail

repo_root=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
cd "$repo_root"

manifest="custom_components/ventilation_reminder/manifest.json"
branch="main"

die() {
    echo "error: $*" >&2
    exit 1
}

[ $# -eq 1 ] || die "usage: scripts/release.sh <version>   (e.g. 0.3.0)"

# Accept both 0.3.0 and v0.3.0, but the manifest never carries the v
version=${1#v}
tag="v$version"

[[ $version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "'$version' is not a x.y.z version"

command -v jq >/dev/null || die "jq is required"

current=$(git rev-parse --abbrev-ref HEAD)
[ "$current" = "$branch" ] || die "on branch '$current', expected '$branch'"

[ -z "$(git status --porcelain)" ] || die "working tree is not clean"

git fetch --quiet origin "$branch" --tags
[ "$(git rev-parse HEAD)" = "$(git rev-parse "origin/$branch")" ] ||
    die "local $branch differs from origin/$branch - pull or push first"

git rev-parse -q --verify "refs/tags/$tag" >/dev/null &&
    die "tag $tag already exists"

previous=$(jq -r .version "$manifest")
[ "$previous" != "$version" ] || die "manifest is already at $version"

echo "Releasing $previous -> $version"

# Patch only the version line - jq would reformat the compact arrays and
# bury the bump in unrelated churn
tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
sed -E "s/(\"version\"[[:space:]]*:[[:space:]]*\")[^\"]*(\")/\1$version\2/" \
    "$manifest" >"$tmp"
mv "$tmp" "$manifest"

[ "$(jq -r .version "$manifest")" = "$version" ] ||
    die "failed to patch the version in $manifest"

git add "$manifest"
git commit -m "chore: bump version to $version"

# main first: a tag pointing at a commit that is not on the branch yet would
# make the release reference something nobody can see
git push origin "$branch"
git tag "$tag"
git push origin "$tag"

echo
echo "Pushed $tag. The Release workflow is now creating the GitHub release:"
echo "  https://github.com/C0d3Br3aker/Ventilation-Reminder/actions"
