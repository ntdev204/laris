"""Abstract persistence interface, schema migration registry, and reference adapter for Layer 5."""

from __future__ import annotations

import copy
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional

from laris.core.errors import GraphIntegrityError, SchemaMigrationError
from laris.layers.layer5_graph.schemas import EvidenceGraph

# Migration function type: receives dict representation of a graph, returns migrated dict
MigrationFn = Callable[[Dict[str, Any]], Dict[str, Any]]



class GraphSchemaMigrationRegistry:
    """Registry managing versioned migrations for EvidenceGraph schema definitions."""

    def __init__(self) -> None:
        self._migrations: Dict[tuple[str, str], MigrationFn] = {}

    def register_migration(
        self,
        source_version: str,
        target_version: str,
        migrator: MigrationFn,
    ) -> None:
        """Registers a schema migration function from source_version to target_version."""
        self._migrations[(source_version, target_version)] = migrator

    def has_migration(self, source_version: str, target_version: str) -> bool:
        """Checks if a direct migration path is registered between two versions."""
        return (source_version, target_version) in self._migrations

    def migrate(self, data: Dict[str, Any], target_version: str) -> Dict[str, Any]:
        """Applies migration pipeline to transform serialized graph dict to target_version."""
        current_version = data.get("schema_version", "1.0.0")
        if current_version == target_version:
            return copy.deepcopy(data)

        key = (current_version, target_version)
        if key not in self._migrations:
            raise SchemaMigrationError(
                f"No registered migration path from schema version '{current_version}' "
                f"to target version '{target_version}'."
            )

        migrator = self._migrations[key]
        migrated = migrator(copy.deepcopy(data))
        migrated["schema_version"] = target_version
        return migrated


class BaseGraphPersistenceAdapter(ABC):
    """Abstract persistence interface for EvidenceGraph storage backends (ADR-009).

    Decouples in-memory graph reasoning and retrieval operations from
    concrete storage backends (SQLite, file system, or in-memory).
    """

    def __init__(
        self,
        migration_registry: Optional[GraphSchemaMigrationRegistry] = None,
    ) -> None:
        self.migration_registry = migration_registry or GraphSchemaMigrationRegistry()

    @abstractmethod
    def save(self, graph: EvidenceGraph) -> None:  # pragma: no cover
        """Persists an EvidenceGraph to storage."""
        pass

    @abstractmethod
    def load(self, graph_id: str) -> EvidenceGraph:  # pragma: no cover
        """Retrieves and deserializes an EvidenceGraph from storage."""
        pass

    @abstractmethod
    def exists(self, graph_id: str) -> bool:  # pragma: no cover
        """Checks if a graph with graph_id exists in storage."""
        pass

    @abstractmethod
    def delete(self, graph_id: str) -> bool:  # pragma: no cover
        """Deletes a graph by its identifier. Returns True if deleted, False if not found."""
        pass

    @abstractmethod
    def list_graphs(self) -> List[str]:  # pragma: no cover
        """Returns a list of all persisted graph identifiers."""
        pass

    @abstractmethod
    def get_schema_version(self, graph_id: str) -> str:  # pragma: no cover
        """Returns the schema version of a persisted graph."""
        pass

    @abstractmethod
    def migrate(self, graph_id: str, target_version: str) -> EvidenceGraph:  # pragma: no cover
        """Migrates a stored graph to target_version and saves the updated graph."""
        pass



class InMemoryGraphPersistenceAdapter(BaseGraphPersistenceAdapter):
    """Reference in-memory persistence adapter for zero-overhead unit testing."""


    def __init__(
        self,
        migration_registry: Optional[GraphSchemaMigrationRegistry] = None,
    ) -> None:
        super().__init__(migration_registry=migration_registry)
        self._store: Dict[str, Dict[str, Any]] = {}

    def save(self, graph: EvidenceGraph) -> None:
        """Saves a deep copy of the graph dictionary in memory."""
        if not isinstance(graph, EvidenceGraph):
            raise GraphIntegrityError("Expected EvidenceGraph instance.")
        graph.validate_integrity()
        self._store[graph.graph_id] = copy.deepcopy(graph.to_dict())

    def load(self, graph_id: str) -> EvidenceGraph:
        """Loads and deserializes an EvidenceGraph from in-memory dictionary."""
        if graph_id not in self._store:
            raise KeyError(f"Graph '{graph_id}' does not exist in memory store.")
        data = copy.deepcopy(self._store[graph_id])
        return EvidenceGraph.from_dict(data)

    def exists(self, graph_id: str) -> bool:
        """Checks existence in memory store."""
        return graph_id in self._store

    def delete(self, graph_id: str) -> bool:
        """Removes graph from memory store."""
        if graph_id in self._store:
            del self._store[graph_id]
            return True
        return False

    def list_graphs(self) -> List[str]:
        """Lists all graph identifiers in memory store."""
        return sorted(self._store.keys())

    def get_schema_version(self, graph_id: str) -> str:
        """Returns recorded schema version."""
        if graph_id not in self._store:
            raise KeyError(f"Graph '{graph_id}' does not exist in memory store.")
        return str(self._store[graph_id].get("schema_version", "1.0.0"))

    def migrate(self, graph_id: str, target_version: str) -> EvidenceGraph:
        """Migrates a stored graph dictionary to target_version and updates store."""
        if graph_id not in self._store:
            raise KeyError(f"Graph '{graph_id}' does not exist in memory store.")
        data = self._store[graph_id]
        migrated_dict = self.migration_registry.migrate(data, target_version)
        self._store[graph_id] = migrated_dict
        return EvidenceGraph.from_dict(migrated_dict)
