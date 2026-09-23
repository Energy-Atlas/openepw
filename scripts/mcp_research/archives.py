"""Read ZIP/ZIP64 directory metadata only; never decompress an archive member."""

import re
import struct


def directory_location(tail, total_size):
    end = tail.rfind(b"PK\x05\x06")
    if end < 0 or len(tail) - end < 22:
        raise ValueError("ZIP directory locator absent")
    fields = struct.unpack_from("<4s4H2IH", tail, end)
    _, disk, cd_disk, disk_entries, entries, size, offset, comment = fields
    if disk or cd_disk or disk_entries != entries or end + 22 + comment != len(tail):
        raise ValueError("Unsupported ZIP directory layout")
    if size == 0xFFFFFFFF or offset == 0xFFFFFFFF or entries == 0xFFFF:
        start = tail.rfind(b"PK\x06\x06", 0, end)
        if start < 0 or end - start < 56:
            raise ValueError("ZIP64 locator outside bounded tail")
        fields = struct.unpack_from("<4sQ2H2I4Q", tail, start)
        if fields[4] or fields[5] or fields[6] != fields[7]:
            raise ValueError("Unsupported multi-disk ZIP64")
        entries, size, offset = fields[7:10]
    if size > 10_000_000 or offset + size > total_size or not entries:
        raise ValueError("Directory exceeds budget or archive bounds")
    return {"offset": offset, "size": size, "entries": entries}


def member_names(directory):
    pos, names = 0, []
    while pos < len(directory):
        if len(directory) - pos < 46 or directory[pos : pos + 4] != b"PK\x01\x02":
            raise ValueError("Malformed central directory")
        fields = struct.unpack_from("<4s6H3I5H2I", directory, pos)
        name_len, extra_len, comment_len = fields[10:13]
        end = pos + 46 + name_len + extra_len + comment_len
        if end > len(directory):
            raise ValueError("Truncated directory entry")
        name = directory[pos + 46 : pos + 46 + name_len].decode(
            "utf-8" if fields[3] & 0x800 else "cp437"
        )
        names.append(name)
        pos = end
    return names


def site_years(names):
    sites = {}
    for name in names:
        match = re.search(r"(?:^|/)([^/]+)_RCP(4\.5|8\.5)_(\d{4})_lat[^/]*\.epw$", name)
        if match:
            site, scenario, year = match.groups()
            sites.setdefault(site, {}).setdefault("RCP" + scenario, set()).add(int(year))
    return {
        site: {scenario: sorted(years) for scenario, years in scenarios.items()}
        for site, scenarios in sorted(sites.items())
    }
