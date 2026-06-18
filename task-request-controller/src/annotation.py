from src.geo import GeographicGroup


def compute_effective_beta(
    beta_t: dict[str, int],
    dataset_requirements: list[dict[str, int]],
) -> dict[str, int]:
    """
    Compute the effective property class `beta*(t)` for a given set of datasets and task beta values.

    This is defined as `beta*(t) = LUB(beta(t), beta(d1), beta(d2), ...), where `beta(t)` is the
    base task beta and `beta(d)` are fetched from the dataset service.

    Args:
        beta_t: Base property requirements of the task.
        dataset_requirements: List of requirements dicts, one per dataset.

    Returns:
        The computed effective beta as a dictionary.

    Raises:
        DatasetNotFoundError: If any dataset is not found (HTTP 404).
        DatasetServiceError: If there is any other error communicating with the dataset service.
    """
    result: dict[str, int] = dict(beta_t)

    for reqs in dataset_requirements:
        for prop, level in (reqs or {}).items():
            result[prop] = max(result.get(prop, 0), int(level))

    return result


def compute_effective_geo(
    geo_t: str | None,
    dataset_geos: list[str | None],
    geo_groups: dict[str, GeographicGroup],
) -> set[str] | None:
    """
    Compute the effective geographic regions `geo*(t)` for a given set of datasets and task
    geographic groups.

    This is defined as `geo*(t) = geo(t) intersection geo(d1) intersection geo(d2) intersection ...`, 
    where `geo(t)` is the geographic group specified for the task and `geo(d)` are the geographic groups 
    specified for each dataset. 

    Args:
        geo_t: geographic group name for the task, or None for `Omega` (no constraint).
        dataset_geos: list of geo group names (or None for `Omega`) for each dataset.
        geo_groups: registry of all known GeographicGroup objects.

    Returns:
        The computed effective geographic regions as a set of location strings, or
        None if there are no geographic constraints (i.e. if geo*(t) = `Omega`). An empty set means
        no node satisfies all constraints, there are not an intersection of the geographic groups.
    """
    geo_names = [g for g in [geo_t, *dataset_geos] if g is not None]

    if not geo_names:
        return None  # No geographic constraints, return None (Omega)

    result: set[str] | None = None
    for geo in geo_names:
        group = geo_groups.get(geo)
        if group is None:
            continue  # Skip unknown geo groups

        locations = group.resolve(geo_groups)
        if result is None:
            result = set(locations)
        else:            
            result.intersection_update(locations)
            
    return result
