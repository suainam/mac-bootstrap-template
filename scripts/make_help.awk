# Render `make help` from annotations placed next to the targets they describe.
#
# Convention: one comment line per help entry, directly above the rule it
# documents (stack several lines when a rule belongs to more than one section):
#
#   ## <section-rank>.<entry-rank> <Section title> | <display> | <description>
#
# <section-rank> orders sections (ascending, ties keep first appearance);
# <entry-rank> orders entries inside a section; <display> is the left-hand name
# shown in help, so an entry that takes an argument can say so (for example
# `enable-dev USER=<name>`); <description> is the right-hand text.
#
# Usage: awk -f make_help.awk Makefile

function trim(s) {
	sub(/[ \t]+$/, "", s)
	sub(/^[ \t]+/, "", s)
	return s
}

function key(rank,   parts) {
	split(rank, parts, ".")
	return sprintf("%04d.%04d", parts[1] + 0, parts[2] + 0)
}

/^##[ \t]/ {
	payload = trim(substr($0, 3))

	sep = index(payload, " ")
	if (!sep)
		next
	rank = substr(payload, 1, sep - 1)
	if (rank !~ /^[0-9]+\.[0-9]+$/)
		next
	rest = trim(substr(payload, sep + 1))

	sep = index(rest, " | ")
	if (!sep)
		next
	section = trim(substr(rest, 1, sep - 1))
	rest = substr(rest, sep + 3)

	sep = index(rest, " | ")
	if (!sep)
		next
	display = trim(substr(rest, 1, sep - 1))
	description = trim(substr(rest, sep + 3))

	if (section == "" || display == "" || description == "")
		next

	sort = key(rank)
	if (!(section in sections)) {
		sections[section] = sort
		order[++count] = section
		widths[section] = 0
	} else if (sort < sections[section]) {
		sections[section] = sort
	}
	rows[section, ++total[section]] = sort SUBSEP display SUBSEP description
	if (length(display) > widths[section])
		widths[section] = length(display)
}

END {
	for (i = 2; i <= count; i++) {
		value = order[i]
		for (j = i - 1; j >= 1 && sections[order[j]] > sections[value]; j--)
			order[j + 1] = order[j]
		order[j + 1] = value
	}

	for (i = 1; i <= count; i++) {
		section = order[i]
		for (a = 2; a <= total[section]; a++) {
			value = rows[section, a]
			for (b = a - 1; b >= 1 && rows[section, b] > value; b--)
				rows[section, b + 1] = rows[section, b]
			rows[section, b + 1] = value
		}
		print ""
		print "\342\224\200\342\224\200 " section " \342\224\200\342\224\200"
		for (k = 1; k <= total[section]; k++) {
			split(rows[section, k], pair, SUBSEP)
			printf "  %-" widths[section] "s  %s\n", pair[2], pair[3]
		}
	}
}
