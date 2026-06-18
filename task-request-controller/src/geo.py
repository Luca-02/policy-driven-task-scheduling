class GeographicGroup:
    """
    Represents a geographic group as loaded from a GeoGroup CR.

    A group is either a leaf (has direct locations), a composite (includes
    other groups by name), or both.
    """

    def __init__(self, name: str, locations: list[str], includes: list[str]):
        self.name = name
        self.locations = list(locations)
        self.includes = list(includes)

    def resolve(
        self,
        registry: dict[str, "GeographicGroup"],
    ) -> set[str]:
        """
        Return the concrete set of locations for this group.

        Cycles are handled by skipping any group already in the current
        resolution path. Missing includes are silently ignored.

        Args:
            registry: mapping of group (name, GeographicGroup) for all known groups.

        Returns:
            Set of location strings.
        """
        return self._resolve_job(registry)

    def _resolve_job(
        self,
        registry: dict[str, "GeographicGroup"],
        visited: set[str] | None = None,
    ) -> set[str]:
        """
        Concrete implementation of resolve().

        Args:
            registry: mapping of group (name, GeographicGroup) for all known groups.
            visited: set of group names already in the resolution path.

        Returns:
            Set of location strings.
        """
        if visited is None:
            visited = set()

        visited |= {self.name}
        result: set[str] = set(self.locations)

        for include in self.includes:
            if include in visited:
                continue  # already in path: skip to avoid cycle

            included = registry.get(include)
            if included is None:
                continue  # missing group: skip silently

            result |= included._resolve_job(registry, visited)

        return result
