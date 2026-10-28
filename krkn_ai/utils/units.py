def format_bytes(value: int, suffixes: tuple[str, str, str]) -> str:
    """Format a byte count with the largest of (bytes, KiB, MiB) that divides it.

    Rounding down to a whole unit would run a different value than the one the
    genetic algorithm recorded, e.g. 2097151 bytes as 1Mi.
    """
    byte_suffix, kib_suffix, mib_suffix = suffixes
    if value >= 1024 * 1024 and value % (1024 * 1024) == 0:
        return f"{value // (1024 * 1024)}{mib_suffix}"
    if value >= 1024 and value % 1024 == 0:
        return f"{value // 1024}{kib_suffix}"
    return f"{value}{byte_suffix}"
