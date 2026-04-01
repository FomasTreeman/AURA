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


if __name__ == "__main__":
    app()
