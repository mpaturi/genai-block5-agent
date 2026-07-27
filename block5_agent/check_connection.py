"""Confirms every external dependency this agent needs is reachable, per
docs/spec.md's Configuration section: the search service, the graph
database, the language model key, and the tracing service.
"""
import os
import sys

import requests
from dotenv import load_dotenv
from langsmith import Client
from neo4j import GraphDatabase
from neo4j.exceptions import AuthError, ServiceUnavailable

load_dotenv()


def check_search_service() -> None:
    url = os.environ.get("RAG_API_URL", "http://localhost:8000")
    response = requests.get(f"{url}/docs", timeout=5)
    response.raise_for_status()
    print(f"Search service OK ({url})")


def check_graph_database() -> None:
    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USER"]
    password = os.environ["NEO4J_PASSWORD"]
    database = os.environ.get("NEO4J_DATABASE", "neo4j")
    with GraphDatabase.driver(uri, auth=(user, password)) as driver:
        driver.verify_connectivity()
        with driver.session(database=database) as session:
            result = session.run("RETURN 1 AS ok")
            assert result.single()["ok"] == 1
    print(f"Graph database OK ({uri})")


def check_language_model_key() -> None:
    key = os.environ["ANTHROPIC_API_KEY"]
    if not key.startswith("sk-ant-"):
        raise ValueError("ANTHROPIC_API_KEY doesn't look like a real Anthropic key")
    print("Language model key present")


def check_tracing_service() -> None:
    key = os.environ["LANGCHAIN_API_KEY"]
    project = os.environ["LANGCHAIN_PROJECT"]
    client = Client(api_key=key)
    # A lightweight call that only succeeds with valid auth.
    next(iter(client.list_projects(limit=1)), None)
    print(f"Tracing service OK (project: {project})")


def main() -> None:
    checks = [
        ("search service", check_search_service),
        ("graph database", check_graph_database),
        ("language model key", check_language_model_key),
        ("tracing service", check_tracing_service),
    ]
    failed = False
    for name, check in checks:
        try:
            check()
        except KeyError as exc:
            print(f"ERROR: Missing environment variable {exc} for {name}.", file=sys.stderr)
            failed = True
        except (ServiceUnavailable, AuthError) as exc:
            print(f"ERROR: {name} not reachable: {exc}", file=sys.stderr)
            failed = True
        except requests.exceptions.RequestException as exc:
            print(f"ERROR: {name} not reachable: {exc}", file=sys.stderr)
            failed = True
        except Exception as exc:  # noqa: BLE001 - report any check failure, don't crash the rest
            print(f"ERROR: {name} check failed: {exc}", file=sys.stderr)
            failed = True

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
