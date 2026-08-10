# Contributing to TuxDrive

Thank you for helping improve TuxDrive. The repository is publicly readable, while direct writes to the main repository remain restricted to maintainers. Public contributions should use GitHub Issues or pull requests.

## Ways to contribute

- Report a reproducible bug with the **Bug report** issue form.
- Suggest a feature or workflow improvement with the **Feature request** form.
- Comment on an existing issue to add evidence, logs, testing results, or design feedback.
- Fork the repository and open a pull request with an implementation.
- Improve user documentation, packaging, accessibility, or translations.
- Review or refine the [top-20 feature roadmap](docs/ROADMAP.md).

## Before reporting a bug

1. Install the newest `.deb` from the repository.
2. Check the [illustrated user guide](docs/USER_GUIDE.md) and existing issues.
3. Reproduce the problem once with the live activity log open.
4. Remove passwords, OAuth tokens, client secrets, private URLs, personal file names, and confidential cloud content from screenshots and logs.

Useful diagnostics:

```bash
tuxdrive --diagnostics
tail -n 150 ~/.local/state/tuxdrive/tuxdrive.log
tail -n 150 ~/.local/state/tuxdrive/crash.log
tail -n 150 ~/.cache/tuxdrive/logs/*.log
```

## Development workflow

1. Fork `tpluharik/Tuxdrive`.
2. Create a focused branch from `main`.
3. Make a small, reviewable change.
4. Add or update tests for behaviour changes.
5. Run:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m compileall -q src
```

6. Update documentation when controls, configuration, packaging, or user-visible behaviour changes.
7. Open a pull request and complete the checklist.

The [testing guide](docs/TESTING.md) describes the current 69-test suite, release matrix, safety invariants and known coverage gaps. Recovery, integrity, mass-change, conflict-resolution, peer authorization, lease, discovery, Nautilus, streaming-mount, provider-URL, or encryption changes must include focused safety tests and document trust, expiry, authoritative-side, and rollback behavior.

## Pull-request expectations

- Explain the user problem and the proposed behaviour.
- Keep unrelated changes out of the pull request.
- Preserve existing configuration compatibility.
- Do not commit OAuth tokens, rclone configuration, credentials, real user logs, or personal paths.
- Treat synchronization and deletion changes as safety-sensitive. Describe failure and recovery behaviour.
- Maintain support for Ubuntu 26.04, Google Drive, and Microsoft OneDrive.
- Use public provider APIs and compatible open-source components; do not copy proprietary client code or branding.

Maintainers may request changes, close incomplete proposals, or decline features that create unacceptable data-loss, privacy, security, or maintenance risk.

## Community conduct

Participation is governed by [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Be specific, constructive, and respectful.
