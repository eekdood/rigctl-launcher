# Release preparation

Use `main` as the only permanent branch. Create a short-lived branch for each change and open a pull request into `main`. Pull requests and pushes to `main` run CI. A version tag matching `pyproject.toml`, such as `v0.1.0`, triggers the build workflow only when its commit belongs to `main`. The workflow creates a **draft prerelease**, with downloads and checksums, for review before publication. A push to `main` without a version tag does not publish a release.

CI work is staged to avoid rebuilding the same change after merge:

| Trigger | Work performed |
| --- | --- |
| Pull request | Tests on all three platforms, native builds/smoke tests, notices and source collection, native artifact uploads |
| Ordinary push to `main` | Tests on all three platforms, using test dependencies only |
| Version tag push | Tests, native builds and sources, combined release assets, draft prerelease |
| Manual run | Full build and combined assets by default; optional tests-only mode; no release creation |

New commits cancel obsolete runs for the same PR or `main`. Version-tag release runs are not automatically canceled. Python dependency downloads are cached using `pyproject.toml`. Required check names remain unchanged so branch protection continues to apply.

The initial public history must start with a sanitized snapshot. Earlier private commits contained local profile configuration and must not be pushed as ancestors, branches or tags. Keep any private history archive outside the publication repository. Before publishing, review tracked files, reachable history, Git author identity, examples, documentation and build contents. Do not use a mirror push or blindly push all refs from a private development repository.

Fresh builds start with no radio profiles and use application defaults. User profiles/settings, serial identities, device paths, executable overrides, diagnostics and signing material do not belong in release assets. Examples are generic and are not automatically loaded. Existing user configuration remains outside the installed application and is not reset by upgrades.

Builds are created separately on their target operating system. PyInstaller packages the application runtime; it does not install or bundle Hamlib and does not produce an installer by itself. The initial workflow uses app/binary directory archives. Disk images, installers and signing can be added when platform testing justifies specific instructions. An unsigned build must be identified as such in release notes.

Before the first public release:

1. GPLv3 is selected in `license.txt`. Include the applicable dependency notices with distributable builds.
2. Confirm that the required build checks and pull-request protections on `main` are active.
3. Verify the packaged application on the advertised targets, including first launch, executable selection, serial discovery, fake-daemon lifecycle and saved configuration.
4. Decide signing/notarization requirements and provide credentials through protected release secrets when needed.
5. Review the version, then tag the reviewed `main` commit and push that specific branch/tag. Review the resulting draft before publishing it.

Automated builds are not equivalent to confirmed native radio support. Hardware testing requires explicit authorization and is separate from CI. The initial release workflow does not run real radio sessions or automatically install Hamlib.

## GitHub workflow

The publication repository is `https://github.com/eekdood/rigctl-launcher`. `main` is the default and only permanent branch. Start each change from current `main`, work on a descriptive branch, and open a pull request back to `main`. External contributors can work in a fork and submit the same kind of pull request without repository write access.

Review the change after its checks pass, then squash and merge. GitHub automatically deletes the merged branch. Update local `main` before starting the next change. There is no separate integration branch or extra merge step before a release.

`main` requires pull requests, blocks force pushes/deletion, and applies its protections to administrators. Zero approving reviews are required for solo maintenance. The matrix checks `build (macos-14)`, `build (windows-2022)` and `build (ubuntu-22.04)` are required, with the branch up to date and results supplied by GitHub Actions.

Keep Actions default permissions at read-only and leave workflow approval of pull requests disabled. The draft-release job grants write permission only where it creates a release. The official actions in the workflow use Node.js 24. Issues are enabled for bug reports; project boards and a wiki are optional. Review pull requests and CI results before tagging a release.

For local GitHub CLI setup, use GitHub's `noreply` commit address when email privacy is enabled. The CLI must have the `workflow` scope to push Actions workflow files; add it with `gh auth refresh --hostname github.com --scopes workflow` and complete the browser authorization. Do not disable email privacy protection to work around a rejected push.

Each build writes a `.inventory.json` sidecar alongside its archive. It records collected modules, native package providers, exact known versions, file hashes, relative symlinks, Qt/Python versions and build tools. Installation paths and local configuration are omitted. Unknown native providers are explicitly marked; embedded third-party code still needs upstream attribution records. The inventory is not presented as a complete SPDX SBOM.

Builds download matching upstream source archives into ignored `build/notice-cache/`. They ship `third-party-notices.txt`, a `licenses/` directory and `inventory.json` beside the application. Legal texts are also embedded in the application for offline access through About / Licenses. Homebrew/Debian provider notices and CPython Windows external-library notices are included where applicable. A missing attribution file or unknown license provider fails the build. PDF, virtual-keyboard and optional software OpenGL plugins are excluded from this QWidget application. Desktop platform plugins remain.

After building, `python packaging/sources.py` creates a platform-specific `_sources.tar.gz` asset and checksum. It includes the tracked application snapshot, matching upstream archive bytes verified against notice provenance, inventory, source manifest and build instructions. Native Homebrew sources include the installed formula and pinned source/patch downloads; Debian/Ubuntu sources include exact source versions with `.dsc` and distribution patch/build files. Linux source repositories (`deb-src`) must be enabled before collecting sources; CI configures this on its runner. Missing sources, recipes or checksum mismatches fail collection. Source trees stay out of Git and application downloads. Publish source assets beside the matching application assets and preserve them for each release. The manifest identifies versions and archives; it does not claim byte-for-byte reproducible binaries.

The public release assembler (`python packaging/release_assets.py INPUT OUTPUT`) verifies all three platform inputs and creates just the three application archives, one `rigctl-launcher_VERSION_sources.zip`, and `checksums.txt`. Inventories remain inside the application archives and the source ZIP. The source ZIP retains each platform's manifest, provider patches and build instructions; identical application/upstream source archives are stored once under `shared/`. Automated tests cover the assembled layout; tag pushes and full manual runs assemble the actual native outputs. Native PR artifacts retain their fuller working layout.

Dependabot checks Python dependencies and GitHub Actions weekly. Review its pull requests through the normal build/source-collection checks so dependency upgrades also update the generated notices and source assets.

`pyproject.toml` supplies the application version for archive/checksum/inventory filenames, Qt application metadata, macOS bundle metadata and Windows executable version resources. For example, version `0.1.0` produces `rigctl-launcher_0.1.0_macos-arm64.zip`. The stable macOS bundle identifier is `io.github.eekdood.rigctl-launcher`. Numeric native versions use the three release components (Windows adds a fourth zero); full prerelease versions remain in public application metadata and archive names. Each build verifies its packaged metadata before the smoke test. Generated specs and resource files stay in ignored build storage; only the public name, version and identifier are included in the application metadata. Builds replace the generated `artifacts/builds/` output directory so stale assets cannot enter a later release.
