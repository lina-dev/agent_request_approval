// Package expense writes decisions back to the source expense tool through a
// stable adapter interface, so the concrete vendor (Concur/Expensify/Ramp) is
// pluggable without touching the rest of the platform.
package expense

import (
	"context"
	"errors"
)

// Decision is the platform's verdict written back to the expense tool.
type Decision struct {
	Status    string // APPROVE | DENY | ESCALATE
	Rationale string
	Citations []string
}

// ExpenseAdapter is the single seam to a vendor expense system.
type ExpenseAdapter interface {
	WriteDecision(ctx context.Context, caseID string, d Decision) error
}

// ErrInvalidDecision is returned for a malformed writeback request.
var ErrInvalidDecision = errors.New("invalid decision for writeback")

// Writeback is the single entrypoint app code uses to push a decision.
func Writeback(ctx context.Context, a ExpenseAdapter, caseID string, d Decision) error {
	if caseID == "" {
		return ErrInvalidDecision
	}
	switch d.Status {
	case "APPROVE", "DENY", "ESCALATE":
	default:
		return ErrInvalidDecision
	}
	return a.WriteDecision(ctx, caseID, d)
}

// RecordingAdapter is a test double; swap for a real vendor client.
type RecordingAdapter struct {
	Last     Decision
	LastCase string
	Calls    int
}

// WriteDecision records the call.
func (r *RecordingAdapter) WriteDecision(_ context.Context, caseID string, d Decision) error {
	r.Last = d
	r.LastCase = caseID
	r.Calls++
	return nil
}
