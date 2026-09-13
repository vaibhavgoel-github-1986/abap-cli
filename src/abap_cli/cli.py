"""Command line interface."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.tree import Tree

from abap_cli import __version__, config, layout
from abap_cli.client import ImportResult, SapClient, SapError
from abap_cli.config import ConfigError, System
from abap_cli.manifest import Entry, Manifest, sha256

app = typer.Typer(
    name="abap",
    help="Bulk export/import of ABAP objects between SAP and a local folder.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()
err_console = Console(stderr=True)

SystemOpt = Annotated[str, typer.Option("--system", "-s", help="Named system from config.")]
DestOpt = Annotated[Path, typer.Option("--dest", "-d", help="Local folder for the package.")]
PackageArg = Annotated[str, typer.Argument(help="SAP package, e.g. ZGET_SUBS_API_V2")]


def _fail(message: str) -> None:
    err_console.print(f"[bold red]error[/] {message}")
    raise typer.Exit(1)


def _connect(system_name: str) -> tuple[System, str]:
    try:
        system = config.resolve(name=system_name)
    except ConfigError as exc:
        _fail(str(exc))
        raise  # unreachable, keeps type checkers happy

    password = config.password_for(system)
    if not password:
        password = typer.prompt(f"SAP password for {system.describe()}", hide_input=True)
        if not password:
            _fail("no password supplied")
        console.print(
            f"[dim]tip: 'abap login --system {system.name}' stores this in your keychain[/]"
        )
    return system, password


def _resolve_dest(dest: Path | None, package: str) -> Path:
    return (dest or Path.cwd() / package.upper()).resolve()


# --------------------------------------------------------------------------- commands


@app.command()
def version() -> None:
    """Show the CLI version."""
    console.print(f"abap-cli {__version__}")


@app.command()
def init(
    name: Annotated[str, typer.Option(prompt="System name (e.g. dha-110)")],
    host: Annotated[str, typer.Option(prompt="Host URL (https://host:port)")],
    user: Annotated[str, typer.Option(prompt="SAP user")],
    client: Annotated[str, typer.Option(prompt="SAP client")],
    description: Annotated[str, typer.Option(help="Free text, shown by 'abap systems'.")] = "",
    insecure: Annotated[bool, typer.Option(help="Skip TLS verification.")] = False,
    default: Annotated[bool, typer.Option(help="Make this the default system.")] = True,
) -> None:
    """Add a system to ~/.abap-cli/config.json."""
    system = System(
        name=name,
        host=host.rstrip("/"),
        user=user,
        client=client,
        verify_tls=not insecure,
        description=description,
    )
    config.save_system(system, make_default=default)
    console.print(f"saved [bold]{name}[/] to {config.CONFIG_HOME}")
    console.print(f"next: [bold]abap login --system {name}[/]")


@app.command()
def use(system: Annotated[str, typer.Argument(help="System to make the default.")]) -> None:
    """Set the default system used when --system is omitted."""
    try:
        config.set_default(system)
    except ConfigError as exc:
        _fail(str(exc))
        return
    console.print(f"default system is now [bold]{system}[/]")


@app.command()
def remove(system: Annotated[str, typer.Argument(help="System to forget.")]) -> None:
    """Remove a system from the config."""
    try:
        config.remove_system(system)
    except ConfigError as exc:
        _fail(str(exc))
        return
    console.print(f"removed [bold]{system}[/]")


@app.command(name="config")
def show_config() -> None:
    """Show where the config lives and how to override it."""
    exists = config.CONFIG_HOME.is_file()
    console.print(f"config file : [bold]{config.CONFIG_HOME}[/]{'' if exists else ' (not created yet)'}")
    console.print(f"default     : {config.default_system() or '(none)'}")
    console.print("\n[dim]environment overrides, useful for CI:[/]")
    for name, purpose in (
        ("ABAP_SYSTEM", "which system to use when --system is omitted"),
        ("ABAP_HOST", "host URL"),
        ("ABAP_USER", "SAP user"),
        ("ABAP_CLIENT", "SAP client"),
        ("ABAP_PASSWORD", "password, bypasses the keychain"),
    ):
        console.print(f"  {name:<14} {purpose}")


@app.command()
def systems() -> None:
    """List configured systems."""
    configured = config.list_systems()
    if not configured:
        console.print(f"no systems configured, run [bold]abap init[/] ({config.CONFIG_HOME})")
        return

    current = config.default_system()
    table = Table(box=None, header_style="dim")
    table.add_column("")
    table.add_column("system", style="bold")
    table.add_column("host")
    table.add_column("client")
    table.add_column("user")
    table.add_column("password")
    table.add_column("description", style="dim")
    for name, profile in sorted(configured.items()):
        account = f"{name}:{profile.get('user', '')}"
        table.add_row(
            "*" if name == current else " ",
            name,
            str(profile.get("host", "")),
            str(profile.get("client", "")),
            str(profile.get("user", "")),
            "saved" if config.keychain_get(account) else "-",
            str(profile.get("description", "")),
        )
    console.print(table)


@app.command()
def login(system: SystemOpt = "") -> None:
    """Store the SAP password for a system in the OS keychain."""
    try:
        target = config.resolve(name=system)
    except ConfigError as exc:
        _fail(str(exc))
        return
    console.print(f"storing credentials for [bold]{target.describe()}[/]")
    if config.keychain_store(target.keychain_account):
        console.print("[green]stored[/]")
    else:
        _fail("could not store the password (keychain is macOS only; use $ABAP_PASSWORD)")


@app.command()
def logout(system: SystemOpt = "") -> None:
    """Remove stored credentials for a system."""
    try:
        target = config.resolve(name=system)
    except ConfigError as exc:
        _fail(str(exc))
        return
    console.print("[green]removed[/]" if config.keychain_delete(target.keychain_account)
                  else "nothing stored")


@app.command()
def ping(system: SystemOpt = "") -> None:
    """Check that the ZSYNC endpoint is reachable."""
    target, password = _connect(system)
    try:
        with SapClient(target, password) as sap:
            reply = sap.ping()
    except SapError as exc:
        _fail(str(exc))
        return
    console.print(f"[green]{reply.get('message', reply)}[/]")


@app.command()
def pull(
    package: PackageArg,
    system: SystemOpt = "",
    dest: Optional[Path] = typer.Option(None, "--dest", "-d", help="Target folder."),
    subpackages: Annotated[bool, typer.Option(help="Include sub-package objects.")] = True,
    se80: Annotated[
        bool, typer.Option("--se80", help="Lay files out as an SE80 folder tree.")
    ] = False,
) -> None:
    """Download a package into a local folder.

    The default is abapGit's flat src/ layout, the same as you would see in a
    GitHub repo. Pass --se80 to mirror the SE80 object tree instead.
    """
    target, password = _connect(system)
    root = _resolve_dest(dest, package)

    try:
        with SapClient(target, password) as sap:
            archive = sap.export(package.upper(), include_subpackages=subpackages)
    except SapError as exc:
        _fail(str(exc))
        return

    manifest = Manifest(
        root=root,
        package=package.upper(),
        system=target.name,
        include_subpackages=subpackages,
    )
    refs = []
    with zipfile.ZipFile(io.BytesIO(archive)) as archive_file:
        for info in archive_file.infolist():
            if info.is_dir():
                continue
            ref = layout.to_local_path(info.filename, package)
            local = ref.local if se80 else info.filename.lstrip("/")
            if ".." in Path(local).parts:
                _fail(f"refusing unsafe path in archive: {info.filename}")

            data = archive_file.read(info)
            written = root / local
            written.parent.mkdir(parents=True, exist_ok=True)
            written.write_bytes(data)

            manifest.files[local] = Entry(
                canonical=info.filename,
                sha256=sha256(data),
                obj_type=ref.obj_type,
                obj_name=ref.obj_name,
            )
            refs.append(ref)

    manifest.save()

    console.print(
        f"pulled [bold]{manifest.package}[/] from [bold]{target.name}[/] "
        f"- {len(manifest.files)} files, {len(archive):,} bytes"
    )
    console.print(f"[dim]{root}[/]\n")
    _print_tree(manifest.package, layout.tree_summary(refs))


@app.command()
def status(
    package: PackageArg = "",
    dest: Optional[Path] = typer.Option(None, "--dest", "-d", help="Local folder."),
) -> None:
    """Show locally modified objects. Works offline, no credentials needed."""
    root = _resolve_dest(dest, package) if (dest or package) else Path.cwd()
    manifest = Manifest.load(root)
    if not manifest.exists:
        _fail(f"no manifest in {root}, run 'abap pull' first")

    modified, deleted = manifest.scan()
    console.print(
        f"[bold]{manifest.package}[/] from {manifest.system}, pulled {manifest.pulled_at}"
    )
    for local in modified:
        console.print(f"  [yellow]M[/]  {local}")
    for local in deleted:
        console.print(f"  [red]D[/]  {local}")
    if not modified and not deleted:
        console.print("  [green]clean[/] - no local changes")
        return

    objects = manifest.objects_for(modified)
    console.print(
        f"\n{len(modified)} modified, {len(deleted)} deleted, "
        f"{len(objects)} object(s) affected"
    )


@app.command()
def push(
    package: PackageArg = "",
    system: SystemOpt = "",
    dest: Optional[Path] = typer.Option(None, "--dest", "-d", help="Local folder."),
    transport: Annotated[str, typer.Option(help="Transport request.")] = "",
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Validate without writing.")] = False,
    snapshot: Annotated[bool, typer.Option(help="Save a rollback zip before writing.")] = True,
) -> None:
    """Upload locally modified objects and activate them."""
    root = _resolve_dest(dest, package) if (dest or package) else Path.cwd()
    manifest = Manifest.load(root)
    if not manifest.exists:
        _fail(f"no manifest in {root}, run 'abap pull' first")

    modified, deleted = manifest.scan()
    if deleted:
        console.print(f"[yellow]note[/] {len(deleted)} deleted file(s) are ignored by push")
    if not modified:
        console.print("nothing to push - no local changes")
        return

    objects = manifest.objects_for(modified)
    selected = manifest.files_of_objects(objects)
    extra = len(selected) - len(modified)

    console.print(f"edited   {len(modified)} file(s) in {len(objects)} object(s)")
    for obj_type, obj_name in sorted(objects):
        console.print(f"  [bold]{obj_type}[/] {obj_name}")
    if extra > 0:
        console.print(f"[dim]including {extra} sibling file(s) so each object is complete[/]")

    target, password = _connect(system or manifest.system)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive_file:
        for local in selected:
            archive_file.writestr(manifest.files[local].canonical, (root / local).read_bytes())
    payload = buffer.getvalue()

    try:
        with SapClient(target, password) as sap:
            if snapshot and not dry_run:
                path = manifest.snapshot_path()
                path.write_bytes(sap.export(manifest.package, manifest.include_subpackages))
                console.print(f"[dim]snapshot {path.relative_to(root)}[/]")

            console.print(
                f"pushing  {len(selected)} file(s), {len(payload):,} bytes"
                + ("  [DRY RUN]" if dry_run else "")
            )
            result = sap.import_zip(
                package=manifest.package,
                archive=payload,
                transport=transport,
                dry_run=dry_run,
            )
    except SapError as exc:
        _fail(str(exc))
        return

    _print_result(result)
    if result.failed:
        raise typer.Exit(1)


# --------------------------------------------------------------------------- output


def _print_tree(package: str, summary: dict[str, int]) -> None:
    tree = Tree(f"[bold]{package}[/]")
    nodes: dict[str, Tree] = {}
    for folder, count in summary.items():
        parent = tree
        trail = ""
        for part in folder.split("/"):
            trail = f"{trail}/{part}" if trail else part
            if trail not in nodes:
                nodes[trail] = parent.add(part)
            parent = nodes[trail]
        parent.label = f"{parent.label} [dim]({count})[/]"
    console.print(tree)


def _print_result(result: ImportResult) -> None:
    colour = "red" if result.failed else "green"
    console.print(
        f"status   [{colour}]{result.status}[/]   objects={result.object_count} "
        f"errors={result.error_count} warnings={result.warning_count}"
    )
    for obj in result.objects:
        message = obj.get("message", "")
        if not message or message == "No message":
            continue
        mark = {"E": "[red]ERROR[/]", "W": "[yellow]warn [/]", "S": "[green]ok   [/]"}.get(
            obj.get("status", ""), obj.get("status", "")
        )
        name = f"{obj.get('obj_type', ''):5} {obj.get('obj_name', '')}".strip()
        console.print(f"  {mark} {name} {message}")


if __name__ == "__main__":
    app()
