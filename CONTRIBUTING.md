# Contributing to Bluehour

Thank you for helping. The most valuable contribution right now is **a test on real hardware**: see
[docs/hardware-testing.md](docs/hardware-testing.md) and open a "Hardware report" issue.

## Set up

```bash
git clone https://github.com/Mosberg/bluehour-vr.git
cd bluehour-vr
python -m venv .venv && . .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[dev,camera]"
```

## Before you open a pull request

```bash
python -m unittest discover -s tests -t .       # all tests must pass
ruff check .                                    # no lint errors
```

- Keep changes focused: one fix or feature per pull request.
- Add or update tests for logic that can run without hardware (decoders, maths, mappings, parsers).
- Update the docs and `CHANGELOG.md` (under _Unreleased_) when behaviour changes.
- The window, shader and device code cannot run in CI. Say in the pull request how you tried it.
- Describe user-visible changes in plain words. State clearly what you could not verify.

## Style

- Python 3.9 compatible. No new runtime dependency without a good reason; heavy ones go into an extra.
- Follow the existing code: short functions, comments that explain why, plain names.
- Commit messages: imperative, short subject line, details in the body.

## Reporting bugs

Use the issue templates. For tracking problems include the output of `bluehour --debug`, your OS, and
which devices are connected. For device problems say which USB port and which Bluetooth adapter.

By contributing you agree that your work is released under the [MIT License](LICENSE).
Everyone taking part is expected to follow the [Code of Conduct](CODE_OF_CONDUCT.md).
