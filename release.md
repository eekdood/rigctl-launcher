# Release preparation

Use `dev` for development and `main` for reviewed release-ready snapshots. Pushes to either branch run CI. A version tag matching `pyproject.toml`, such as `v0.1.0`, triggers the build workflow only when its commit belongs to `main`. The workflow creates a **draft prerelease**, with downloads and checksums, for review before publication. A push to `main` without a version tag does not publish a release.

The initial public history must start with a sanitized snapshot. Earlier private commits contained local profile configuration and must not be pushed as ancestors, branches or tags. Keep any private history archive outside the publication repository. Before publishing, review tracked files, reachable history, Git author identity, examples, documentation and build contents. Do not use a mirror push or blindly push all refs from a private development repository.

Fresh builds start with no radio profiles and use application defaults. User profiles/settings, serial identities, device paths, executable overrides, diagnostics and signing material do not belong in release assets. Examples are generic and are not automatically loaded. Existing user configuration remains outside the installed application and is not reset by upgrades.

Builds are created separately on their target operating system. PyInstaller packages the application runtime; it does not install or bundle Hamlib and does not produce an installer by itself. The initial workflow uses app/binary directory archives. Disk images, installers and signing can be added when platform testing justifies specific instructions. An unsigned build must be identified as such in release notes.

Before the first public release:

1. Choose a project license and add the applicable dependency notices.
2. Connect the intended GitHub repository and configure branch protections after the first push.
3. Verify the packaged application on the advertised targets, including first launch, executable selection, serial discovery, fake-daemon lifecycle and saved configuration.
4. Decide signing/notarization requirements and provide credentials through protected release secrets when needed.
5. Review the version, then tag the reviewed `main` commit and push that specific branch/tag. Review the resulting draft before publishing it.

Automated builds are not equivalent to confirmed native radio support. Hardware testing requires explicit authorization and is separate from CI. The initial release workflow does not run real radio sessions or automatically install Hamlib.
