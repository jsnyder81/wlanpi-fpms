# Development Setup Instructions

## Initial Setup

The following steps are the initial instructions to clone the codebase locally and setup a virtualenv.

1. Clone repo:

```
git clone git@github.com:WLAN-Pi/wlanpi-fpms.git && cd wlanpi-fpms
```

2. Create virtualenv:

```
python3 -m venv venv
```

3. Activate venv:

```
source venv/bin/activate
```

5. Update pip, setuptool, and wheel (this is only done once)

```
pip install -U pip setuptools wheel pip-tools
```

6. Install requirements along with the extras

```
pip install -e .[testing]
```

The `testing` extras install tools like ruff, mypy, pytest, etc.

## Executing the wlanpi-fpms module

Ok, now should be ready to run the code. This version of the fpms is packaged into a module. So, we need to instruct Python to run it as a module with the `-m` option.

1. Activate the virtualenv

```
source venv/bin/activate
```

2. We need to run fpms as sudo, which means we'll need to pass along the location of the Python environment to sudo like this:

```
sudo venv/bin/python3 -m fpms
```

Or do you want to enable keyboard interactive mode? You can capture screenshots with `g` with this mode! Add the `-e` arg like this:

```
sudo venv/bin/python3 -m fpms -e
```

Further reading on executing modules with Python at <https://docs.python.org/3/library/runpy.html>.

## Running without a WLAN Pi

The panel is a client of `wlanpi-menud`, so development needs a menu service to talk to. `wlanpi-menud` ships one that runs on a fake `wlanpi-core`, with no device and no root for the service itself:

```
# in a wlanpi-menud checkout
.venv/bin/python demo/serve_fake.py /tmp/menud-dev
```

Then point fpms at that socket. With no SPI display present it uses the virtual screen, which prints each screen as text; `g` saves a PNG of the 128x128 frame.

```
sudo FPMS_MENUD_SOCKET=/tmp/menud-dev/local.sock FPMS_DISPLAY=virtual venv/bin/python3 -m fpms -e
```

Stop the fake service and the panel switches to the "Menu unavailable" screen with the machine's IP addresses; start it again and it reattaches.

## Tests

```
tox -e py313        # or: python -m pytest
tox -e lint
tox -e formatcheck
```

`tests/menud_client/` runs the panel headless: a scripted fake `wlanpi-menud` on a Unix socket (`fake_menud.py`, every frame checked against the vendored `frames.schema.json`) and the virtual screen, so tests assert on both the frames exchanged and the pixels drawn. Set `FPMS_MENUD_TRANSCRIPT=/path/file` to save the frame transcript of each test. `test_live_menud.py` runs against the real service when a `wlanpi-menud` checkout with a `.venv` sits next to this repo, and is skipped otherwise.

When `frames.schema.json` changes in `wlanpi-menud`, copy it to `tests/menud_client/fixtures/`; `test_protocol.py` fails while the two differ.

## Cheatsheat

Is your development environment already setup?

```
cd <root of repo>
source venv/bin/activate
sudo venv/bin/python3 -m fpms
sudo venv/bin/python3 -m fpms -e
```