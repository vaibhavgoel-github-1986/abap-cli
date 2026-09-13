# abap-cli

Pull ABAP objects out of SAP into a folder, edit them with any editor, push them back.

One command downloads a whole package. One command sends back only what you changed
and activates it. No SAP GUI, no Eclipse, no git required.

```bash
abap pull ZEXAMPLE_API        # SAP  ->  ./ZEXAMPLE_API/src/*.abap
# ...edit files...
abap status                   # what did I change?
abap push                     # back to SAP, activated
```

---

## Contents

- [Before you start](#before-you-start)
- [Install](#install)
- [First run](#first-run)
- [Everyday use](#everyday-use)
- [Command reference](#command-reference)
- [Where things are stored](#where-things-are-stored)
- [Using it in CI](#using-it-in-ci)
- [Troubleshooting](#troubleshooting)
- [How it works](#how-it-works)
- [Limitations](#limitations)

---

## Before you start

Two things must be true, or nothing will work:

**1. Your machine needs Python 3.10 or newer.**

```bash
python3 --version
```

**2. The SAP system needs the ZSYNC endpoint installed.**

`abap-cli` is only a client. It talks to `/sap/bc/zsync`, an HTTP service that has to
exist in each SAP system you want to use. That service wraps abapGit's object layer,
so abapGit must be installed there too.

Check with `abap ping` once you are set up. If you get
`/sap/bc/zsync not found`, ask your Basis or ABAP team to install it — the CLI
cannot install it for you.

You also need an SAP user with normal developer authorisation (`S_DEVELOP`) in that
system.

---

## Install

```bash
pipx install "git+https://github.com/vaibhavgoel-github-1986/abap-cli@release/v1"
```

No `pipx`? Install it first with `brew install pipx` (macOS) or
`python3 -m pip install --user pipx`.

If pipx complains about `uv`, add `--backend pip`:

```bash
pipx install --backend pip "git+https://github.com/vaibhavgoel-github-1986/abap-cli@release/v1"
```

Check it worked:

```bash
abap version      # abap-cli 1.0.0
```

To upgrade later, run the same install command with `--force`.

---

## First run

Three commands and you are ready.

### 1. Add your system

```bash
abap init
```

It asks four questions:

```
System name (e.g. dev-100):  dev-100
Host URL (https://host:port): https://sap-dev.example.com:44300
SAP user:                     MYUSER
SAP client:                   100
```

**System name** is your own label — anything you like. Use it later with `--system`.
A good convention is `<system-id>-<client>`, so `dev-100`, `qa-300`, `sbx-320`.

Add `--insecure` if the server uses a certificate your machine does not trust
(common with internal CAs).

Repeat `abap init` for every system you use. The first one becomes your default.

### 2. Save your password

```bash
abap login
```

macOS prompts you, and the password goes into your **login keychain** — never into a
file, never into your shell history. You only do this once per system.

### 3. Check the connection

```bash
abap ping
```

```
ZSYNC alive on DEV client 100 as MYUSER
```

If you see that, you are done setting up.

---

## Everyday use

### Download a package

```bash
abap pull ZEXAMPLE_API
```

```
pulled ZEXAMPLE_API from dev-100 - 83 files, 67,117 bytes
/Users/you/ZEXAMPLE_API
```

You now have a folder with real `.abap` files. Open it in VS Code, grep it, edit it —
they are ordinary text files.

By default the folder is created in your current directory. Use `--dest` to choose
somewhere else:

```bash
abap pull ZEXAMPLE_API --dest ~/work/example
```

### See what you changed

```bash
abap status
```

```
ZEXAMPLE_API from dev-100, pulled 2026-09-13T14:20:11
  M  src/zcl_example_provider.clas.abap

1 modified, 0 deleted, 1 object(s) affected
```

This is **completely offline** — no password, no connection to SAP. It compares your
files against hashes recorded when you pulled.

Run it from inside the package folder, or pass `--dest`.

### Preview the deployment

```bash
abap push --dry-run
```

Nothing is written to SAP. You see exactly which objects would change. Always worth
doing first.

### Deploy

```bash
abap push --transport DEVK900123
```

```
edited   1 file(s) in 1 object(s)
  CLAS ZCL_EXAMPLE_PROVIDER
snapshot .abap/snapshots/ZEXAMPLE_API-20260913-142530.zip
pushing  2 file(s), 22,631 bytes
status   S   objects=1 errors=0 warnings=0
```

Only the objects you touched are sent. Everything is activated together in one go.

Leave out `--transport` for packages that are not transport-relevant; SAP will tell
you if one is required.

If activation fails you get a non-zero exit code and a per-object error message, and
the previously active version keeps running in SAP.

---

## Command reference

### Setting up systems

| Command | What it does |
|---|---|
| `abap init` | Add a system (asks for name, host, user, client) |
| `abap systems` | List systems; `*` marks the default |
| `abap use <system>` | Change the default system |
| `abap remove <system>` | Forget a system |
| `abap config` | Show where config lives and which env vars override it |
| `abap version` | Print the installed version |

```bash
abap systems
```

```
    system   host                             client  user    password  description
 *  dev-100  https://sap-dev.example.com:…    100     MYUSER  saved     Development
    qa-300   https://sap-qa.example.com:…     300     MYUSER  -         Quality
```

### Credentials

| Command | What it does |
|---|---|
| `abap login` | Save the password for a system in the OS keychain |
| `abap logout` | Delete the saved password |

Both take `--system` to target a system other than the default.

### Working with code

| Command | What it does | Needs SAP |
|---|---|---|
| `abap ping` | Check the endpoint is reachable | yes |
| `abap pull <package>` | Download a package | yes |
| `abap status` | Show local changes | **no** |
| `abap push` | Upload changed objects and activate | yes |

### Options you will actually use

**`abap pull`**

| Option | Meaning |
|---|---|
| `--dest <path>` | Where to put the folder (default: `./<PACKAGE>`) |
| `--no-subpackages` | Only this package, skip sub-packages |
| `--se80` | Arrange files as an SE80 object tree instead of flat `src/` |
| `--system <name>` | Pull from a system other than the default |

**`abap push`**

| Option | Meaning |
|---|---|
| `--dry-run` | Show what would happen, write nothing |
| `--transport <id>` | Transport request to record the changes in |
| `--no-snapshot` | Skip the rollback zip (not recommended) |
| `--dest <path>` | Package folder, if you are not inside it |

Every command supports `--help`:

```bash
abap pull --help
```

---

## Where things are stored

### Your systems

`~/.abap-cli/config.json`, readable only by you. It holds host, user and client —
**never a password**.

```json
{
  "default_system": "dev-100",
  "systems": {
    "dev-100": {
      "host": "https://sap-dev.example.com:44300",
      "user": "MYUSER",
      "client": "100",
      "insecure": true,
      "description": "Development"
    }
  }
}
```

You can edit this file by hand. `abap config` prints its path.

### Your password

In the **macOS login keychain**, one entry per system:

```
service: abap-cli
account: dev-100:MYUSER
```

Manage it with `abap login` / `abap logout`, or search for `abap-cli` in
Keychain Access. On Linux and Windows there is no keychain support yet — use the
`ABAP_PASSWORD` environment variable, or let it prompt you each time.

### Your downloaded code

```
ZEXAMPLE_API/
├── .abap/
│   ├── manifest.json     # file hashes - powers status and push
│   └── snapshots/        # rollback zips taken before each push
├── .abapgit.xml
└── src/
    ├── package.devc.xml
    ├── zcl_example_provider.clas.abap
    ├── zcl_example_provider.clas.xml
    └── zif_example_api.intf.abap
```

That flat `src/` layout is the same one abapGit uses, so it looks identical to an
ABAP repo on GitHub. With `--se80` you get folders like
`Class Library/Classes/ZCL_EXAMPLE_PROVIDER/` and
`Core Data Services/Data Definitions/` instead, with sub-packages under
`Subpackages/<NAME>/`.

Both push back identically — the layout is only how files sit on your disk.

**Do not delete `.abap/`.** Without it, `status` and `push` have no baseline and you
will have to pull again.

---

## Using it in CI

Skip the keychain and pass everything through the environment:

```bash
export ABAP_SYSTEM=dev-100
export ABAP_PASSWORD="$SAP_PASSWORD"   # from your secret store

abap pull ZEXAMPLE_API
abap push --transport "$TRANSPORT" || exit 1
```

| Variable | Purpose |
|---|---|
| `ABAP_SYSTEM` | Which configured system to use |
| `ABAP_HOST` | Host URL, if you have no config file |
| `ABAP_USER` | SAP user |
| `ABAP_CLIENT` | SAP client |
| `ABAP_PASSWORD` | Password — bypasses the keychain entirely |

`abap push` exits non-zero when any object fails to activate, so it fails the build
for you.

---

## Troubleshooting

**`zsh: command not found: abap`**
The install did not put it on your `PATH`. Run `pipx ensurepath`, then open a new
terminal. Check with `which abap`.

**`/sap/bc/zsync not found on <host>`**
The endpoint is not installed in that SAP system. It has to be installed there
before the CLI can do anything. Try another system with `--system`.

**`authentication failed`**
Wrong or expired password. Run `abap login` again to replace the stored one.

**`no manifest in <folder>, run 'abap pull' first`**
You are not inside a pulled package folder. Either `cd` into it, or pass
`--dest /path/to/package`.

**`several systems configured, pick one with --system`**
No default set. Run `abap use <system>`, or add `--system` to the command.

**`nothing to push - no local changes`**
Your files match what was pulled. Check with `abap status`.

**SSL certificate errors**
Internal CAs are often not trusted by Python. Re-add the system with
`abap init --insecure`, or set `"insecure": true` in the config file.

---

## How it works

```
abap-cli  ──HTTPS──▶  /sap/bc/zsync  ──▶  abapGit object layer  ──▶  SAP
```

- **Pull** asks SAP to serialize the package and returns a zip. The CLI unpacks it and
  records a hash of every file.
- **Status** compares your files against those hashes. Purely local.
- **Push** works out which objects changed, zips just those (plus their metadata
  files, which SAP needs), and sends one request. SAP deserializes and activates
  everything in a single pass, in dependency order.

All the heavy lifting happens inside SAP. The CLI only moves a zip, which is why a
package of 80+ objects transfers in about a second.

---

## Limitations

- The `/sap/bc/zsync` endpoint must be installed in every SAP system you target.
- Deleting objects is not supported. Deleted local files are reported, then ignored.
- A package already managed by an abapGit repo bound to a *different* package (for
  example a parent) is rejected, to avoid deploying against the wrong scope.
- Keychain storage is macOS-only. Elsewhere, use `ABAP_PASSWORD`.
- Pull and push work a package at a time, not on individual objects.

---

## Licence

MIT
