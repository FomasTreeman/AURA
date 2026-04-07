"""
AURA CLI – quick testing interface using Typer + Rich.
Usage:
  python -m backend.cli ingest --dir ./data/documents
  python -m backend.cli query "What is our Q3 revenue target?"
  python -m backend.cli stats
  python -m backend.cli reset
"""
import asyncio
import json
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from backend.config import INGEST_DIR

app = typer.Typer(
    name="aura",
    help="AURA – Sovereign Local Node CLI",
    add_completion=False,
)
console = Console()


@app.command()
def ingest(
    dir: Path = typer.Option(
        INGEST_DIR,
        "--dir",
        "-d",
        help="Directory containing PDF files to ingest.",
    ),
) -> None:
    """Ingest all PDF files from a directory into the AURA vector store."""
    from backend.ingestion.pipeline import ingest_directory

    if not dir.is_dir():
        console.print(f"[red]Error:[/red] Directory not found: {dir}")
        raise typer.Exit(code=1)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task(f"Ingesting PDFs from {dir}…", total=None)
        results = ingest_directory(dir)
        progress.remove_task(task)

    if not results:
        console.print("[yellow]No PDFs found.[/yellow]")
        return

    table = Table(title="Ingestion Results", show_header=True)
    table.add_column("File")
    table.add_column("Chunks", justify="right")
    table.add_column("CID (first 12)")
    table.add_column("Status")

    total_chunks = 0
    for r in results:
        chunks = r.get("chunks_added", 0)
        total_chunks += chunks  # type: ignore[operator]
        error = r.get("error")
        status = "[red]ERROR[/red]" if error else "[green]OK[/green]"
        cid = str(r.get("cid", ""))[:12] if not error else "—"
        table.add_row(str(r.get("file")), str(chunks), cid, status)

    console.print(table)
    console.print(f"\n[bold]Total chunks stored:[/bold] {total_chunks}")


@app.command()
def query(
    question: str = typer.Argument(..., help="Question to ask the AURA knowledge base."),
    stream: bool = typer.Option(True, help="Stream tokens to terminal as they arrive."),
) -> None:
    """Ask a question and receive a streamed answer from the local LLM."""
    from backend.rag.generator import check_ollama, stream_answer

    try:
        check_ollama()
    except RuntimeError as exc:
        console.print(f"[red]Ollama error:[/red] {exc}")
        raise typer.Exit(code=1)

    console.print(Panel(question, title="[bold]Question[/bold]", border_style="blue"))
    console.print("\n[bold]Answer:[/bold]")

    async def _run() -> None:
        full_text = ""
        sources: list[dict] = []
        async for line in stream_answer(question):
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "token" in msg:
                token = msg["token"]
                full_text += token
                if stream:
                    console.print(token, end="", highlight=False)
            elif "done" in msg:
                sources = msg.get("sources", [])
            elif "error" in msg:
                console.print(f"\n[red]Error:[/red] {msg['error']}")

        if stream:
            console.print()  # newline after streaming

        if sources:
            console.print("\n[dim]Sources:[/dim]")
            for s in sources:
                console.print(
                    f"  [dim]• {s['source']} p.{s['page']} (dist={s['distance']})[/dim]"
                )

    asyncio.run(_run())


@app.command()
def stats() -> None:
    """Show current vector store statistics."""
    from backend.database.chroma import get_collection

    collection = get_collection()
    count = collection.count()
    console.print(f"[bold]Collection:[/bold] {collection.name}")
    console.print(f"[bold]Document chunks:[/bold] {count}")


@app.command()
def reset() -> None:
    """Delete all vectors from the AURA collection (irreversible)."""
    from backend.database.chroma import reset_collection

    confirmed = typer.confirm("This will delete ALL vectors. Are you sure?")
    if not confirmed:
        console.print("[yellow]Aborted.[/yellow]")
        raise typer.Exit()

    reset_collection()
    console.print("[green]Collection reset.[/green]")


# ── Key management command group ─────────────────────────────────────────────

key_app = typer.Typer(name="key", help="Manage this node's DID keypair.", add_completion=False)
app.add_typer(key_app)


@key_app.command("show")
def key_show() -> None:
    """Display the current node's DID and public key information."""
    from backend.config import P2P_KEY_DIR
    from backend.network.peer import PeerIdentity
    identity = PeerIdentity.load_or_create(P2P_KEY_DIR)
    console.print(f"[bold]DID:[/bold]          did:key:{identity.peer_id}")
    console.print(f"[bold]Peer ID:[/bold]       {identity.peer_id}")
    console.print(f"[bold]Ed25519 pubkey:[/bold] {identity.ed25519_pubkey_b64[:32]}…")
    console.print(f"[bold]X25519 pubkey:[/bold]  {identity.x25519_pubkey_b64[:32]}…")


@key_app.command("export")
def key_export(
    output: Path = typer.Argument(..., help="Output path for the encrypted keystore JSON."),
    passphrase: str = typer.Option(
        ...,
        prompt=True,
        hide_input=True,
        confirmation_prompt=True,
        help="Passphrase to encrypt the exported keystore.",
    ),
) -> None:
    """Export an encrypted keystore file protected by a passphrase."""
    from backend.config import P2P_KEY_DIR
    from backend.network.peer import PeerIdentity
    from backend.security.did import create_keystore
    identity = PeerIdentity.load_or_create(P2P_KEY_DIR)
    # Re-create keystore with exported identity
    from backend.security.did import DIDKeystore, _encrypt_seed
    import json
    ed_seed, x_seed = identity.export_seeds()
    ks_data = {
        "version": 1,
        "peer_id": identity.peer_id,
        "ed25519": _encrypt_seed(ed_seed, passphrase),
        "x25519": _encrypt_seed(x_seed, passphrase),
        "rotation_history": [],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(ks_data, indent=2))
    console.print(f"[green]Keystore exported to:[/green] {output}")
    console.print(f"[dim]peer_id: {identity.peer_id[:24]}…[/dim]")


@key_app.command("import")
def key_import(
    keystore_file: Path = typer.Argument(..., help="Path to the encrypted keystore JSON."),
    passphrase: str = typer.Option(
        ...,
        prompt=True,
        hide_input=True,
        help="Passphrase to decrypt the keystore.",
    ),
) -> None:
    """Import an encrypted keystore and set it as the active identity."""
    from backend.security.did import load_keystore
    try:
        ks = load_keystore(keystore_file, passphrase)
        console.print(f"[green]Keystore imported successfully.[/green]")
        console.print(f"[bold]Peer ID:[/bold] {ks.peer_id}")
        console.print(f"[bold]DID:[/bold]     {ks.did}")
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]Import failed:[/red] {exc}")
        raise typer.Exit(code=1)


@key_app.command("rotate")
def key_rotate(
    passphrase: str = typer.Option(
        ..., prompt=True, hide_input=True,
        help="Current keystore passphrase.",
    ),
    new_passphrase: str = typer.Option(
        None, "--new-passphrase", prompt=False, hide_input=True,
        help="New passphrase (leave empty to keep same).",
    ),
) -> None:
    """Rotate this node's keypair. Generates a new key and signs the rotation record."""
    from backend.config import P2P_KEY_DIR
    from backend.security.did import create_keystore, load_keystore, rotate_key
    ks_path = P2P_KEY_DIR / "keystore.json"
    # Bootstrap: create encrypted keystore from seed files if not exists
    if not ks_path.exists():
        from backend.network.peer import PeerIdentity
        identity = PeerIdentity.load_or_create(P2P_KEY_DIR)
        ed_seed, x_seed = identity.export_seeds()
        from backend.security.did import _encrypt_seed
        import json
        ks_data = {
            "version": 1,
            "peer_id": identity.peer_id,
            "ed25519": _encrypt_seed(ed_seed, passphrase),
            "x25519": _encrypt_seed(x_seed, passphrase),
            "rotation_history": [],
        }
        ks_path.parent.mkdir(parents=True, exist_ok=True)
        ks_path.write_text(json.dumps(ks_data, indent=2))
    try:
        old_ks = load_keystore(ks_path, passphrase)
    except ValueError as exc:
        console.print(f"[red]Wrong passphrase:[/red] {exc}")
        raise typer.Exit(code=1)
    old_peer_id = old_ks.peer_id
    new_ks = rotate_key(old_ks, passphrase, new_passphrase or None)
    console.print(f"[green]Key rotated successfully.[/green]")
    console.print(f"  Old peer_id: [dim]{old_peer_id}[/dim]")
    console.print(f"  New peer_id: [bold]{new_ks.peer_id}[/bold]")
    console.print("[yellow]Restart the node to activate the new identity.[/yellow]")


if __name__ == "__main__":
    app()
