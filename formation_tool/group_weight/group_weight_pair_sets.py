"""Helpers for group-specific group_weight rebate/weight pairs."""

PAIR_SET_MARKER = "__group_weight_pair_set__"


def get_group_suffix(group_id):
    """Return the group-rule suffix used by a group_id."""
    return int(group_id) % 10


def get_weight_group_suffixes(weight_group_ids):
    return tuple(sorted({get_group_suffix(group_id) for group_id in weight_group_ids or []}))


def make_pair_set(pairs_by_suffix, stats_by_suffix=None):
    return {
        PAIR_SET_MARKER: True,
        "pairs_by_suffix": {
            str(suffix): list(pairs)
            for suffix, pairs in (pairs_by_suffix or {}).items()
        },
        "stats_by_suffix": {
            str(suffix): dict(stats)
            for suffix, stats in (stats_by_suffix or {}).items()
        },
    }


def is_pair_set(value):
    return isinstance(value, dict) and value.get(PAIR_SET_MARKER) is True


def get_pairs_for_group(pair_source, group_id):
    """Return pairs for a specific group_id, while accepting legacy list inputs."""
    if not is_pair_set(pair_source):
        return pair_source or []
    suffix = str(get_group_suffix(group_id))
    return list(pair_source.get("pairs_by_suffix", {}).get(suffix, []))


def get_stats_for_group(pair_source, group_id):
    if not is_pair_set(pair_source):
        return {}
    suffix = str(get_group_suffix(group_id))
    return dict(pair_source.get("stats_by_suffix", {}).get(suffix, {}))


def get_pairs_for_mode_group(mode_pairs, mode, group_id):
    return get_pairs_for_group((mode_pairs or {}).get(mode, []), group_id)


def has_any_pairs(pair_source):
    if not is_pair_set(pair_source):
        return bool(pair_source)
    return any(bool(pairs) for pairs in pair_source.get("pairs_by_suffix", {}).values())


def mode_has_any_pairs(mode_pairs, mode):
    return has_any_pairs((mode_pairs or {}).get(mode, []))


def describe_pair_set_counts(pair_source):
    if not is_pair_set(pair_source):
        return ""
    parts = []
    for suffix, pairs in sorted(pair_source.get("pairs_by_suffix", {}).items(), key=lambda item: int(item[0])):
        parts.append(f"分组{suffix}:{len(pairs)}")
    return "，".join(parts)
