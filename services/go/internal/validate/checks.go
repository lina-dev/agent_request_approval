// Package validate runs deterministic, auditable reimbursement checks.
// All money is integer cents to avoid floating-point drift. Checks are pure
// functions of their input and never make the decision themselves — they emit
// additive flags the adjudicator reads.
package validate

import "fmt"

// Item is a single claimed line item.
type Item struct {
	AmountCents int64
}

// Claim is the submitted expense claim.
type Claim struct {
	AmountCents int64
	Currency    string
	Date        string // yyyy-mm-dd
	Category    string
	Items       []Item
}

// Receipt is one extracted receipt used as proof.
type Receipt struct {
	AmountCents int64
	Date        string
}

// Input bundles everything the checks need.
type Input struct {
	Claim    Claim
	Receipts []Receipt
}

// Validate runs all deterministic checks and returns additive flags.
// The returned slice is always non-nil (possibly empty).
func Validate(in Input) []string {
	flags := []string{}

	// Math sanity: a non-positive claim is malformed.
	if in.Claim.AmountCents <= 0 {
		flags = append(flags, "math_fail")
	}

	// Receipt-proof completeness (spec core rule).
	if len(in.Receipts) == 0 {
		flags = append(flags, "missing_receipt")
		return flags // nothing more to compare against
	}

	// Amount reconciliation: receipts must total the claim.
	var receiptTotal int64
	for _, r := range in.Receipts {
		receiptTotal += r.AmountCents
	}
	if receiptTotal != in.Claim.AmountCents {
		flags = append(flags, "amount_mismatch")
	}

	// Duplicate detection: identical (amount, date) receipts.
	seen := make(map[string]bool, len(in.Receipts))
	for _, r := range in.Receipts {
		key := fmt.Sprintf("%d|%s", r.AmountCents, r.Date)
		if seen[key] {
			flags = append(flags, "duplicate")
			break
		}
		seen[key] = true
	}

	return flags
}
