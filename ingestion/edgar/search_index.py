"""Create, fill and manage the Vertex AI Search index.

Usage (from the ingestion/ folder):
    python -m edgar.search_index setup                       # one time: data store + schema + search app
    python -m edgar.search_index import gs://.../a.jsonl ... # re-import files by hand
    python -m edgar.search_index test "supply chain risk"    # try a search
    python -m edgar.search_index delete --data-store OLD_ID --engine OLD_APP_ID
                                                             # remove an index you no longer use

The data store uses Vertex AI Search's default (digital) parser, which is free.
Filings are split into passages by our own code (see documents.py) before import,
so the paid layout parser and its chunking are not needed.
"""

from __future__ import annotations

import argparse
import json
import time
from typing import Any

from google.api_core.client_options import ClientOptions
from google.api_core.exceptions import AlreadyExists, NotFound
from google.cloud import discoveryengine_v1 as de

from .config import GcpSettings, load_gcp_settings
from .documents import SCHEMA

DPC = de.DocumentProcessingConfig


def _opts(gcp: GcpSettings) -> ClientOptions | None:
    if gcp.location == "global":
        return None
    return ClientOptions(api_endpoint=f"{gcp.location}-discoveryengine.googleapis.com")


def create_data_store(gcp: GcpSettings) -> None:
    """A data store of plain-text passages, parsed with the free digital parser."""
    client = de.DataStoreServiceClient(client_options=_opts(gcp))
    data_store = de.DataStore(
        display_name="SEC filings (S&P 100), passages",
        industry_vertical=de.IndustryVertical.GENERIC,
        solution_types=[de.SolutionType.SOLUTION_TYPE_SEARCH],
        content_config=de.DataStore.ContentConfig.CONTENT_REQUIRED,
        document_processing_config=DPC(
            default_parsing_config=DPC.ParsingConfig(
                digital_parsing_config=DPC.ParsingConfig.DigitalParsingConfig()
            ),
        ),
    )
    try:
        op = client.create_data_store(
            parent=gcp.collection, data_store=data_store, data_store_id=gcp.data_store_id
        )
        print("Creating data store...")
        op.result(timeout=600)
        print(f"  created {gcp.data_store_id}")
    except AlreadyExists:
        print(f"  data store {gcp.data_store_id} already exists")


ANNOTATIONS = ("retrievable", "indexable", "searchable", "dynamicFacetable",
               "completable", "keyPropertyMapping")


def merge_schema(existing: dict[str, Any], wanted: dict[str, Any]) -> dict[str, Any]:
    """Add our filter/search annotations onto the data store's current schema.

    If documents were imported before the schema was set, Vertex AI Search has already
    detected each field's type and refuses to change it, so existing types are kept and
    only the annotations are copied. Fields marked as a key property (title) may not be
    searchable or indexable.
    """
    merged: dict[str, Any] = {
        "$schema": wanted.get("$schema"), "type": "object", **(existing or {}),
    }
    props = {k: dict(v) for k, v in (merged.get("properties") or {}).items()}
    for name, want in wanted["properties"].items():
        if name in props:
            for key in ANNOTATIONS:
                if key in want:
                    props[name][key] = want[key]
        else:
            props[name] = dict(want)
        if "keyPropertyMapping" in props[name]:
            props[name].pop("searchable", None)
            props[name].pop("indexable", None)
    merged["properties"] = props
    return merged


def update_schema(gcp: GcpSettings) -> None:
    """Mark ticker / form_type / filing_year as filterable and passage fields retrievable."""
    client = de.SchemaServiceClient(client_options=_opts(gcp))
    name = f"{gcp.data_store}/schemas/default_schema"
    try:
        current = de.Schema.to_dict(client.get_schema(name=name))
        existing = current.get("struct_schema") or json.loads(current.get("json_schema") or "{}")
    except NotFound:
        existing = {}
    merged = merge_schema(existing, SCHEMA)
    print("Setting the metadata schema...")
    request = de.UpdateSchemaRequest(
        schema=de.Schema(name=name, json_schema=json.dumps(merged)), allow_missing=True
    )
    client.update_schema(request=request).result(timeout=600)
    print("  schema set")


def create_engine(gcp: GcpSettings) -> None:
    """The search app ("engine") that serves queries over the data store."""
    client = de.EngineServiceClient(client_options=_opts(gcp))
    engine = de.Engine(
        display_name="SEC filings search (passages)",
        solution_type=de.SolutionType.SOLUTION_TYPE_SEARCH,
        industry_vertical=de.IndustryVertical.GENERIC,
        data_store_ids=[gcp.data_store_id],
        search_engine_config=de.Engine.SearchEngineConfig(
            search_tier=de.SearchTier.SEARCH_TIER_ENTERPRISE,
        ),
    )
    try:
        op = client.create_engine(parent=gcp.collection, engine=engine, engine_id=gcp.engine_id)
        print("Creating search app...")
        op.result(timeout=600)
        print(f"  created {gcp.engine_id}")
    except AlreadyExists:
        print(f"  search app {gcp.engine_id} already exists")


def import_documents(gcp: GcpSettings, manifest_uris: list[str] | str, wait: bool = True) -> None:
    """Import JSONL files. INCREMENTAL adds/updates documents and never deletes."""
    uris = [manifest_uris] if isinstance(manifest_uris, str) else list(manifest_uris)
    client = de.DocumentServiceClient(client_options=_opts(gcp))
    request = de.ImportDocumentsRequest(
        parent=f"{gcp.data_store}/branches/default_branch",
        gcs_source=de.GcsSource(input_uris=uris, data_schema="document"),
        reconciliation_mode=de.ImportDocumentsRequest.ReconciliationMode.INCREMENTAL,
        error_config=de.ImportErrorConfig(gcs_prefix=f"gs://{gcp.bucket}/import-errors/"),
    )
    op = client.import_documents(request=request)
    print(f"Import started ({len(uris)} file(s)): {op.operation.name}")
    if not wait:
        return
    print("Waiting for Vertex AI Search to index the passages (a few minutes to an hour)...")
    start = time.monotonic()
    while not op.done():
        time.sleep(30)
        meta = op.metadata
        if meta is not None:
            print(f"  {int(time.monotonic() - start) // 60} min: "
                  f"{meta.success_count} indexed, {meta.failure_count} failed")
    response = op.result()
    meta = op.metadata
    print(f"Import finished: {meta.success_count} indexed, {meta.failure_count} failed.")
    if meta.failure_count:
        print(f"  details: gs://{gcp.bucket}/import-errors/")
        for err in list(response.error_samples)[:5]:
            print(f"  - {err.message}")


def test_search(gcp: GcpSettings, query: str, filter_: str = "") -> None:
    client = de.SearchServiceClient(client_options=_opts(gcp))
    spec = de.SearchRequest.ContentSearchSpec
    request = de.SearchRequest(
        serving_config=gcp.serving_config,
        query=query,
        page_size=5,
        filter=filter_,
        content_search_spec=spec(search_result_mode=spec.SearchResultMode.DOCUMENTS),
    )
    results = list(client.search(request=request).results)[:5]
    if not results:
        print("No results. If the import finished only minutes ago, wait a little and retry.")
    for i, r in enumerate(results, 1):
        data = de.Document.to_dict(r.document).get("struct_data") or {}
        section = f" · {data['section']}" if data.get("section") else ""
        print(f"\n[{i}] {data.get('title', r.document.id)}{section}")
        print("    " + str(data.get("text", ""))[:300].replace("\n", " ") + "...")


def delete_index(gcp: GcpSettings, data_store_id: str, engine_id: str | None) -> None:
    """Delete a search app and its data store (the app has to go first)."""
    if engine_id:
        client = de.EngineServiceClient(client_options=_opts(gcp))
        try:
            print(f"Deleting search app {engine_id}...")
            client.delete_engine(name=f"{gcp.collection}/engines/{engine_id}").result(timeout=900)
            print("  deleted")
        except NotFound:
            print("  not found (already deleted)")
    client = de.DataStoreServiceClient(client_options=_opts(gcp))
    try:
        print(f"Deleting data store {data_store_id} (can take a few minutes)...")
        client.delete_data_store(
            name=f"{gcp.collection}/dataStores/{data_store_id}"
        ).result(timeout=1800)
        print("  deleted")
    except NotFound:
        print("  not found (already deleted)")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup")
    imp = sub.add_parser("import")
    imp.add_argument("manifest_uris", nargs="+")
    t = sub.add_parser("test")
    t.add_argument("query")
    t.add_argument("--filter", default="", help='e.g. ticker: ANY("AAPL")')
    d = sub.add_parser("delete", help="delete a data store and its search app")
    d.add_argument("--data-store", required=True)
    d.add_argument("--engine", help="the search app attached to that data store")
    args = parser.parse_args(argv)

    gcp = load_gcp_settings()
    if args.cmd == "setup":
        create_data_store(gcp)
        update_schema(gcp)  # before any import, so field types come from our schema
        create_engine(gcp)
        print("\nDone. Next: python -m edgar.publish")
    elif args.cmd == "import":
        import_documents(gcp, args.manifest_uris)
    elif args.cmd == "test":
        test_search(gcp, args.query, args.filter)
    else:
        if args.data_store == gcp.data_store_id:
            raise SystemExit(
                f"{args.data_store} is the data store this project is set to use "
                "(VERTEX_SEARCH_DATA_STORE_ID). Refusing to delete it."
            )
        answer = input(f"Permanently delete data store '{args.data_store}'"
                       + (f" and search app '{args.engine}'" if args.engine else "")
                       + "? Type yes: ")
        if answer.strip().lower() != "yes":
            raise SystemExit("Cancelled.")
        delete_index(gcp, args.data_store, args.engine)


if __name__ == "__main__":
    main()
