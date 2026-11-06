# Dated record register fixture

The product declares one dataset keyed by a binary record number and a Gregorian issue date. A citation repeats both fields inside an ordered list. The field name `record.id` contains a literal dot. A separate relationship uses a virtual position scoped to one release.

The [fixture rows and expected matches](rows.expected.json) specify the matches independently. The first citation reuses the source record's number with a different date. The second citation adds one byte to the number. The fixture encodes binary IDs in hexadecimal and dates as ISO calendar days for transport.
