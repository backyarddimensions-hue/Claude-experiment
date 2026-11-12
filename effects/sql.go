package main

import (
	"regexp"
	"sort"
	"strconv"
	"strings"
)

var (
	reVerb    = regexp.MustCompile(`(?i)\b(SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM|TRUNCATE|CREATE\s+TABLE|ALTER\s+TABLE|DROP\s+TABLE|CREATE\s+(UNIQUE\s+)?INDEX)\b`)
	reCreate  = regexp.MustCompile(`(?i)\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-z_][a-z0-9_]*)`)
	reRename  = regexp.MustCompile(`(?i)\bRENAME\s+TO\s+([a-z_][a-z0-9_]*)`)
	reWrites  = []*regexp.Regexp{
		regexp.MustCompile(`(?i)\bINSERT\s+INTO\s+([a-z_][a-z0-9_]*)`),
		regexp.MustCompile(`(?i)\bUPDATE\s+(?:ONLY\s+)?([a-z_][a-z0-9_]*)\s+(?:AS\s+)?(?:[a-z_][a-z0-9_]*\s+)?SET\b`),
		regexp.MustCompile(`(?i)\bDELETE\s+FROM\s+(?:ONLY\s+)?([a-z_][a-z0-9_]*)`),
		regexp.MustCompile(`(?i)\bTRUNCATE\s+(?:TABLE\s+)?([a-z_][a-z0-9_]*)`),
		regexp.MustCompile(`(?i)\b(?:CREATE|ALTER|DROP)\s+TABLE\s+(?:IF\s+(?:NOT\s+)?EXISTS\s+)?([a-z_][a-z0-9_]*)`),
		regexp.MustCompile(`(?i)\bCREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+NOT\s+EXISTS\s+)?[a-z_][a-z0-9_]*\s+ON\s+([a-z_][a-z0-9_]*)`),
	}
	reDelete = regexp.MustCompile(`(?i)\bDELETE\s+FROM\s+(?:ONLY\s+)?[a-z_][a-z0-9_]*`)
	reReads  = regexp.MustCompile(`(?i)\b(?:FROM|JOIN|USING)\s+(?:ONLY\s+)?([a-z_][a-z0-9_]*)`)
)

func unquote(s string) (string, error) { return strconv.Unquote(s) }

func sqlLike(s string) bool { return reVerb.MatchString(s) }

func createdTables(s string) []string {
	var out []string
	for _, m := range reCreate.FindAllStringSubmatch(s, -1) {
		out = append(out, strings.ToLower(m[1]))
	}
	for _, m := range reRename.FindAllStringSubmatch(s, -1) {
		if strings.Contains(strings.ToUpper(s), "ALTER TABLE") {
			out = append(out, strings.ToLower(m[1]))
		}
	}
	return out
}

// parseSQL returns effects ("reads t", "writes t") for the known tables referenced by the text.
// Table names are filtered against the set of tables created anywhere in the module, which
// removes false positives such as EXTRACT(epoch FROM col).
func parseSQL(s string) []string {
	if !sqlLike(s) {
		return nil
	}
	set := map[string]bool{}
	known := func(t string) bool { return len(tables) == 0 || tables[t] }
	for _, re := range reWrites {
		for _, m := range re.FindAllStringSubmatch(s, -1) {
			if t := strings.ToLower(m[1]); known(t) {
				set["writes "+t] = true
			}
		}
	}
	// blank out DELETE FROM targets so they are not also counted as reads
	masked := reDelete.ReplaceAllStringFunc(s, func(m string) string { return strings.Repeat(" ", len(m)) })
	for _, m := range reReads.FindAllStringSubmatch(masked, -1) {
		if t := strings.ToLower(m[1]); known(t) {
			set["reads "+t] = true
		}
	}
	var out []string
	for e := range set {
		out = append(out, e)
	}
	sort.Strings(out)
	return out
}
